"""Live viewer for amatelier roundtables.

Tails the SQLite database under ``paths.user_db_path()`` and renders
messages in real time. Zero API cost — polls the DB; never calls an LLM.

Uses ``rich`` for colorized output, bordered Judge GATE panels, stable
per-agent colors, a live session header, and a post-session summary.
Falls back to plain ANSI when ``rich`` isn't importable (unusual since
it's a runtime dep in 0.2.0+, but the degraded path still works).

CLI::

    amatelier watch                    # tails active, else most recent
    amatelier watch --rt rt-abc123     # tails a specific roundtable
    amatelier watch --no-rich          # forces plain output
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from datetime import datetime

from amatelier import paths

try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text

    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _RICH_AVAILABLE = False


# ── Colors and roles ──────────────────────────────────────────────────

_AGENT_COLORS = {
    "elena": "cyan",
    "marcus": "red",
    "clare": "magenta",
    "simon": "yellow",
    "naomi": "green",
    "judge": "bold bright_yellow",
    "therapist": "bright_magenta",
    "opus-therapist": "bright_magenta",
    "opus-admin": "bold bright_white",
    "runner": "dim white",
    "steward": "bright_blue",
    "haiku-assistant": "dim white",
}

_PALETTE = ["cyan", "green", "magenta", "yellow", "bright_blue", "bright_green"]


def agent_color(name: str) -> str:
    lower = name.lower()
    if lower in _AGENT_COLORS:
        return _AGENT_COLORS[lower]
    digest = hashlib.md5(lower.encode("utf-8")).hexdigest()
    return _PALETTE[int(digest[:2], 16) % len(_PALETTE)]


def agent_role(name: str) -> str:
    lower = name.lower()
    if lower == "judge":
        return "judge"
    if lower in ("therapist", "opus-therapist"):
        return "therapist"
    if lower == "runner":
        return "runner"
    if lower == "steward":
        return "steward"
    if lower == "opus-admin":
        return "admin"
    if lower in ("elena", "marcus", "clare", "simon", "naomi"):
        return "worker"
    return "agent"


# ── DB helpers ─────────────────────────────────────────────────────────


def _open_db() -> sqlite3.Connection | None:
    db_path = paths.user_db_path()
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _find_roundtable(conn: sqlite3.Connection, rt_id: str | None) -> sqlite3.Row | None:
    if rt_id:
        return conn.execute(
            "SELECT id, topic, status, created_at FROM roundtables WHERE id=?",
            (rt_id,),
        ).fetchone()
    active = conn.execute(
        "SELECT id, topic, status, created_at FROM roundtables "
        "WHERE status='open' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if active:
        return active
    return conn.execute(
        "SELECT id, topic, status, created_at FROM roundtables "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()


def _parse_ts(value) -> datetime | None:
    if value is None:
        return None
    # DB stores as REAL (unix timestamp); try that first
    try:
        return datetime.fromtimestamp(float(value))
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def is_gate(agent: str, text: str) -> bool:
    if agent.lower() != "judge":
        return False
    upper = (text or "").upper()
    return "GATE:" in upper or upper.startswith("GATE ")


# Research results posted by the runner have a stable header shape:
#   "[Research result for {agent} | {model} | {elapsed:.1f}s]:\n{body}"
#   "[Research result for {agent} | TIMEOUT after {N}s]:\n..."
#   "[Research result for {agent} | ERROR]:\n..."
_RESEARCH_RE = __import__("re").compile(
    r"^\[Research result for\s+(?P<agent>\S+)\s*\|\s*(?P<meta>[^\]]+)\]:\s*\n?",
)


def parse_research(agent: str, text: str) -> dict | None:
    """Return parsed research metadata if `text` is a runner-posted research
    result, else None. Result keys: target, meta, body."""
    if agent.lower() != "runner" or not text:
        return None
    m = _RESEARCH_RE.match(text)
    if not m:
        return None
    body = text[m.end():]
    return {
        "target": m.group("agent"),
        "meta": m.group("meta").strip(),
        "body": body,
    }


def _human_size(n_chars: int) -> str:
    if n_chars < 1024:
        return f"{n_chars} B"
    if n_chars < 1024 * 1024:
        return f"{n_chars / 1024:.1f} KB"
    return f"{n_chars / (1024 * 1024):.2f} MB"


# Runner messages emit phase markers in mixed case:
#   "ROUND 1: begin"                 (all caps)
#   "--- SPEAK PHASE (Round 2) ---"  (title case)
#   "YOUR TURN: clare -> SPEAK (Round 1, ...)"
# Case-insensitive so every variant yields the round number.
_ROUND_RE = __import__("re").compile(r"round\s+(\d+)", __import__("re").IGNORECASE)


def extract_round(message: str) -> int | None:
    if not message:
        return None
    m = _ROUND_RE.search(message)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


# ── Rich renderer ──────────────────────────────────────────────────────


class RichWatcher:
    POLL_SECONDS = 2.0

    def __init__(
        self,
        conn: sqlite3.Connection,
        rt_row: sqlite3.Row,
        research_mode: str = "collapsed",
    ) -> None:
        self.conn = conn
        self.rt_id = rt_row["id"]
        self.topic = rt_row["topic"] or "(no topic set)"
        self.status = rt_row["status"]
        self.started_at = time.time()
        self.messages_seen = 0
        self.gates_seen = 0
        self.research_seen = 0
        self.per_agent: dict[str, int] = {}
        self.last_id = 0
        self._current_round: int | None = None
        self.research_mode = research_mode  # collapsed | preview | full
        self.console = Console()

    def _elapsed(self) -> str:
        s = int(time.time() - self.started_at)
        return f"{s // 60}m{s % 60:02d}s"

    def _header(self) -> Panel:
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(justify="left", ratio=2)
        grid.add_column(justify="right", ratio=1)
        grid.add_row(
            Text(f"RT {self.rt_id}", style="bold"),
            Text(
                f"{self.messages_seen} msg \u00b7 {self.gates_seen} GATE \u00b7 "
                f"{self.research_seen} \U0001f4ce \u00b7 {self._elapsed()}",
                style="dim",
            ),
        )
        grid.add_row(
            Text(f"Topic: {self.topic}"),
            Text(f"status: {self.status}", style="dim"),
        )
        return Panel(
            grid,
            title="[bold]amatelier watcher[/bold]",
            border_style="blue",
            padding=(0, 1),
        )

    def _footer(self) -> Panel:
        summary = Table.grid(expand=True)
        summary.add_column(justify="left")
        summary.add_column(justify="right")
        summary.add_row("Session summary", "")
        summary.add_row("  Roundtable", self.rt_id)
        summary.add_row("  Topic", self.topic)
        summary.add_row("  Messages observed", str(self.messages_seen))
        summary.add_row("  GATEs observed", str(self.gates_seen))
        summary.add_row("  Final status", self.status)
        summary.add_row("  Duration", self._elapsed())
        if self.per_agent:
            summary.add_row("", "")
            summary.add_row("  Per agent:", "")
            for name, count in sorted(self.per_agent.items(), key=lambda kv: -kv[1]):
                summary.add_row(
                    Text(f"    {name}", style=agent_color(name)),
                    Text(str(count), style="dim"),
                )
        return Panel(summary, border_style="blue", padding=(0, 1))

    def _render_research(self, parsed: dict, ts_str: str):
        target = parsed["target"]
        meta = parsed["meta"]
        body = parsed["body"]
        size = _human_size(len(body))
        target_color = agent_color(target)

        # Try to extract a request preview from the body — first non-empty line
        first_line = ""
        for line in body.splitlines():
            stripped = line.strip()
            if stripped:
                first_line = stripped[:100]
                if len(stripped) > 100:
                    first_line += "\u2026"
                break

        title = (
            f"[bold cyan]\U0001f4ce research[/bold cyan]  \u2192  "
            f"[bold {target_color}]{target}[/bold {target_color}]  "
            f"[dim]\u00b7 {size} \u00b7 {meta} \u00b7 {ts_str}[/dim]"
        )
        if self.research_mode == "preview":
            preview_lines = [ln for ln in body.splitlines()[:5]]
            preview = "\n".join(preview_lines)
            content = Text(preview, style="dim")
            return Panel(content, title=title, border_style="cyan", padding=(0, 1))
        # collapsed (default)
        if first_line:
            return Panel(
                Text(first_line, style="dim italic"),
                title=title,
                border_style="cyan",
                padding=(0, 1),
            )
        return Panel("", title=title, border_style="cyan", padding=(0, 1))

    def _render_message(self, row: sqlite3.Row):
        agent = (row["agent_name"] or "unknown").lower()
        text = (row["message"] or "").strip()
        # Real schema column is `timestamp` (REAL / unix epoch)
        ts = _parse_ts(row["timestamp"])
        ts_str = ts.strftime("%H:%M:%S") if ts else time.strftime("%H:%M:%S")
        color = agent_color(agent)
        role = agent_role(agent)

        # Research-result collapse (Tier 1)
        if self.research_mode != "full":
            parsed = parse_research(agent, text)
            if parsed is not None:
                return self._render_research(parsed, ts_str)

        if is_gate(agent, text):
            return Panel(
                Text(text),
                title=(
                    f"[bold yellow]\u2605 GATE[/bold yellow]  "
                    f"[bold {color}]{agent}[/bold {color}]  "
                    f"[dim]{ts_str}[/dim]"
                ),
                border_style="yellow",
                padding=(0, 1),
            )

        byline = Text()
        byline.append(f"{agent}  ", style=f"bold {color}")
        byline.append(role, style="dim italic")
        pad = max(1, 50 - len(agent) - len(role) - 2)
        byline.append(" " * pad)
        byline.append(ts_str, style="dim")
        body = Text(text)
        table = Table.grid(expand=True)
        table.add_column()
        table.add_row(byline)
        table.add_row(body)
        table.add_row(Text(""))
        return table

    def _poll(self, live: Live) -> bool:
        # Real schema: messages table has (id, roundtable_id, agent_name,
        # message, timestamp). Round isn't stored as a column — it's derived
        # from runner phase markers like "ROUND 1: begin" or "--- SPEAK
        # PHASE (Round 2) ---".
        rows = self.conn.execute(
            "SELECT id, agent_name, message, timestamp FROM messages "
            "WHERE roundtable_id=? AND id > ? ORDER BY id",
            (self.rt_id, self.last_id),
        ).fetchall()

        for row in rows:
            self.last_id = row["id"]
            self.messages_seen += 1
            agent = (row["agent_name"] or "unknown").lower()
            self.per_agent[agent] = self.per_agent.get(agent, 0) + 1
            if is_gate(agent, row["message"] or ""):
                self.gates_seen += 1
            if parse_research(agent, row["message"] or "") is not None:
                self.research_seen += 1
            # Track round from runner phase markers
            if agent == "runner":
                round_num = extract_round(row["message"] or "")
                if round_num and round_num != self._current_round:
                    self._current_round = round_num
                    self.console.print(
                        Rule(title=f"[bold]Round {round_num}[/bold]", style="blue")
                    )
            self.console.print(self._render_message(row))

        status_row = self.conn.execute(
            "SELECT status FROM roundtables WHERE id=?", (self.rt_id,)
        ).fetchone()
        if status_row and status_row["status"] != self.status:
            self.status = status_row["status"]

        live.update(self._header(), refresh=True)
        return self.status == "open"

    def run(self) -> int:
        self.console.print(self._header())
        self.console.print(
            Text(
                f"Tailing {paths.user_db_path()} \u00b7 "
                f"poll every {int(self.POLL_SECONDS)}s \u00b7 Ctrl-C to exit",
                style="dim",
            )
        )
        self.console.print()
        try:
            with Live(
                self._header(),
                console=self.console,
                refresh_per_second=2,
                transient=False,
                auto_refresh=False,
            ) as live:
                still_open = True
                while still_open:
                    still_open = self._poll(live)
                    if not still_open:
                        break
                    time.sleep(self.POLL_SECONDS)
                # Drain anything that landed as the RT closed
                self._poll(live)
        except KeyboardInterrupt:
            self.console.print()
        self.console.print()
        self.console.print(self._footer())
        return 0


# ── Plain ANSI fallback ────────────────────────────────────────────────


def plain_watch(
    conn: sqlite3.Connection,
    rt_row: sqlite3.Row,
    research_mode: str = "collapsed",
) -> int:
    """Degraded renderer used when rich isn't importable."""
    print("=" * 60)
    print(f" amatelier watcher - RT {rt_row['id']}")
    print(f" Topic: {rt_row['topic']}")
    print("=" * 60)
    print("Waiting for messages. Ctrl-C to exit.\n")

    colors = {
        "judge": "\033[93m",
        "runner": "\033[90m",
        "naomi": "\033[96m",
        "steward": "\033[94m",
        "therapist": "\033[95m",
    }
    reset = "\033[0m"
    cyan = "\033[96m"

    last_id = 0
    try:
        while True:
            rows = conn.execute(
                "SELECT id, agent_name, message FROM messages "
                "WHERE roundtable_id=? AND id > ? ORDER BY id",
                (rt_row["id"], last_id),
            ).fetchall()
            for row in rows:
                agent = (row["agent_name"] or "?").lower()
                text = (row["message"] or "").strip()
                # Research-result collapse
                if research_mode != "full":
                    parsed = parse_research(agent, text)
                    if parsed is not None:
                        size = _human_size(len(parsed["body"]))
                        first = next(
                            (ln.strip() for ln in parsed["body"].splitlines() if ln.strip()),
                            "",
                        )[:100]
                        print(f"{cyan}[research -> {parsed['target']} | "
                              f"{size} | {parsed['meta']}]{reset}")
                        if research_mode == "preview":
                            for ln in parsed["body"].splitlines()[:5]:
                                print(f"  {ln}")
                        elif first:
                            print(f"  \"{first}\"")
                        print("-" * 60)
                        last_id = row["id"]
                        continue
                color = colors.get(agent, "\033[92m")
                print(f"{color}[{agent.upper()}]{reset}")
                print(text)
                print("-" * 60)
                last_id = row["id"]
            status_row = conn.execute(
                "SELECT status FROM roundtables WHERE id=?", (rt_row["id"],)
            ).fetchone()
            if status_row and status_row["status"] != "open":
                print(f"\nRoundtable closed (status={status_row['status']}).")
                break
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nViewer closed.")
    return 0


# ── CLI entry ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="amatelier watch",
        description=(
            "Tail the live roundtable chat from the SQLite DB in user_data_dir. "
            "Zero API cost - reads the database; does not call LLMs."
        ),
    )
    parser.add_argument(
        "--rt",
        metavar="RT_ID",
        help="Roundtable ID to follow (default: active; else most recent)",
    )
    parser.add_argument(
        "--no-rich",
        action="store_true",
        help="Force plain ANSI renderer instead of rich",
    )
    parser.add_argument(
        "--research",
        choices=("collapsed", "preview", "full"),
        default="collapsed",
        help=(
            "How to render Steward research-result pastes: "
            "collapsed=1-line summary (default), preview=summary+5 lines, "
            "full=show entire body in transcript"
        ),
    )
    ns = parser.parse_args(argv)

    conn = _open_db()
    if conn is None:
        print(
            f"No database at {paths.user_db_path()}.\n"
            "Run a roundtable first: amatelier roundtable --topic \"...\" --briefing ...",
            file=sys.stderr,
        )
        return 1

    rt_row = _find_roundtable(conn, ns.rt)
    if rt_row is None:
        if ns.rt:
            print(f"Roundtable {ns.rt!r} not found.", file=sys.stderr)
        else:
            print("No roundtables in the database yet.", file=sys.stderr)
        return 1

    if _RICH_AVAILABLE and not ns.no_rich:
        return RichWatcher(conn, rt_row, research_mode=ns.research).run()
    return plain_watch(conn, rt_row, research_mode=ns.research)


if __name__ == "__main__":
    sys.exit(main())
