"""Render an amatelier roundtable session to SVG + markdown artifacts.

Reads the SQLite database under ``user_data_dir()``, reconstructs the
rich-rendered view (same visual language as ``amatelier watch``), and
writes self-contained SVG files plus a human-readable transcript.

Output is deterministic — running this twice against the same RT produces
byte-identical SVGs. Commit the result to ``examples/sessions/<slug>/`` so
GitHub renders the scenes inline in the README and tutorials.

Usage::

    python scripts/render_session.py --rt <ID> --out examples/sessions/my-run
    python scripts/render_session.py --latest --out examples/sessions/my-run

Scenes written:

    01-header-and-opening.svg   header panel + first 3-5 messages
    02-gate.svg                 a Judge GATE moment (falls back to a Judge
                                moderation message if no GATE fired)
    03-round-transition.svg     round transition rule + opening of later round
    04-session-summary.svg      final summary panel (per-agent breakdown)

Plus:

    transcript.md               full markdown transcript
    digest.json                 copy of the runner's digest (if present)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from amatelier import paths
from amatelier.tools.watch_roundtable import (
    agent_color,
    agent_role,
    is_gate,
)

# Rich is a runtime dep in 0.2.0+.
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text


SVG_WIDTH = 120  # terminal columns; 120 renders GATE panels without wrap


# ── DB access ──────────────────────────────────────────────────────────


def _open_db() -> sqlite3.Connection:
    db = paths.user_db_path()
    if not db.exists():
        raise SystemExit(f"No DB at {db}. Run a roundtable first.")
    conn = sqlite3.connect(str(db), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _pick_rt(conn: sqlite3.Connection, rt_id: str | None, latest: bool) -> sqlite3.Row:
    if rt_id:
        row = conn.execute(
            "SELECT id, topic, status, created_at FROM roundtables WHERE id=?",
            (rt_id,),
        ).fetchone()
        if not row:
            raise SystemExit(f"Roundtable {rt_id!r} not found.")
        return row
    if latest:
        row = conn.execute(
            "SELECT id, topic, status, created_at FROM roundtables "
            "WHERE status='closed' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT id, topic, status, created_at FROM roundtables "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            raise SystemExit("No roundtables in the database.")
        return row
    raise SystemExit("Specify --rt ID or --latest.")


def _messages(conn: sqlite3.Connection, rt_id: str) -> list[dict]:
    """Fetch messages, augmenting with a derived `round` field.

    Real schema is (id, roundtable_id, agent_name, message, timestamp).
    Round isn't a column — runner messages like "ROUND 2: begin" mark
    transitions. Walk in order, latch current round, attach to each row.
    """
    from amatelier.tools.watch_roundtable import extract_round

    rows = conn.execute(
        "SELECT id, agent_name, message, timestamp FROM messages "
        "WHERE roundtable_id=? ORDER BY id",
        (rt_id,),
    ).fetchall()
    current_round = 1
    out: list[dict] = []
    for row in rows:
        agent = (row["agent_name"] or "").lower()
        msg = row["message"] or ""
        if agent == "runner":
            found = extract_round(msg)
            if found is not None:
                current_round = found
        out.append(
            {
                "id": row["id"],
                "agent_name": row["agent_name"],
                "message": row["message"],
                "timestamp": row["timestamp"],
                "round": current_round,
            }
        )
    return out


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            return datetime.fromtimestamp(float(value))
        except (ValueError, TypeError):
            return None


# ── Renderables ───────────────────────────────────────────────────────


def _fmt_time(ts_value) -> str:
    ts = _parse_ts(ts_value)
    return ts.strftime("%H:%M:%S") if ts else "--:--:--"


def _header_panel(rt: sqlite3.Row, msg_count: int, gate_count: int, duration: str) -> Panel:
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(justify="left", ratio=2)
    grid.add_column(justify="right", ratio=1)
    grid.add_row(
        Text(f"RT {rt['id']}", style="bold"),
        Text(f"{msg_count} msg \u00b7 {gate_count} GATE \u00b7 {duration}", style="dim"),
    )
    grid.add_row(
        Text(f"Topic: {rt['topic']}"),
        Text(f"status: {rt['status']}", style="dim"),
    )
    return Panel(
        grid,
        title="[bold]amatelier watcher[/bold]",
        border_style="blue",
        padding=(0, 1),
    )


def _message_renderable(row: sqlite3.Row):
    agent = (row["agent_name"] or "unknown").lower()
    text = (row["message"] or "").strip()
    ts_str = _fmt_time(row["timestamp"])
    color = agent_color(agent)
    role = agent_role(agent)

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
    table = Table.grid(expand=True)
    table.add_column()
    table.add_row(byline)
    table.add_row(Text(text))
    table.add_row(Text(""))
    return table


def _summary_panel(rt: sqlite3.Row, messages: list[sqlite3.Row]) -> Panel:
    per_agent: dict[str, int] = {}
    gates = 0
    for m in messages:
        agent = (m["agent_name"] or "unknown").lower()
        per_agent[agent] = per_agent.get(agent, 0) + 1
        if is_gate(agent, m["message"] or ""):
            gates += 1

    first_ts = _parse_ts(messages[0]["timestamp"]) if messages else None
    last_ts = _parse_ts(messages[-1]["timestamp"]) if messages else None
    if first_ts and last_ts:
        delta = int((last_ts - first_ts).total_seconds())
        duration = f"{delta // 60}m{delta % 60:02d}s"
    else:
        duration = "--"

    summary = Table.grid(expand=True)
    summary.add_column(justify="left")
    summary.add_column(justify="right")
    summary.add_row("Session summary", "")
    summary.add_row("  Roundtable", rt["id"])
    summary.add_row("  Topic", rt["topic"])
    summary.add_row("  Messages observed", str(len(messages)))
    summary.add_row("  GATEs observed", str(gates))
    summary.add_row("  Final status", rt["status"])
    summary.add_row("  Duration", duration)
    if per_agent:
        summary.add_row("", "")
        summary.add_row("  Per agent:", "")
        for name, count in sorted(per_agent.items(), key=lambda kv: -kv[1]):
            summary.add_row(
                Text(f"    {name}", style=agent_color(name)),
                Text(str(count), style="dim"),
            )
    return Panel(summary, border_style="blue", padding=(0, 1))


# ── Scene composition ─────────────────────────────────────────────────


def _render_to_svg(renderables: list, output: Path, title: str) -> None:
    # Use an in-memory StringIO as rich's backing file so Unicode arrows
    # in message text don't crash on Windows cp1252 console.
    import io as _io

    console = Console(
        record=True,
        width=SVG_WIDTH,
        color_system="truecolor",
        force_terminal=True,
        file=_io.StringIO(),
    )
    for r in renderables:
        console.print(r)
    output.parent.mkdir(parents=True, exist_ok=True)
    console.save_svg(str(output), title=title)
    print(f"  wrote {output}")


def render_scene_header(
    rt: sqlite3.Row, messages: list[sqlite3.Row], output: Path
) -> None:
    """Header panel + first 3-5 messages."""
    gate_count = sum(
        1 for m in messages[:5] if is_gate((m["agent_name"] or "").lower(), m["message"] or "")
    )
    head = _header_panel(rt, len(messages), gate_count, duration="0m15s")
    scene = [head]
    scene.append(Rule(title="[bold]Round 1[/bold]", style="blue"))
    for m in messages[:5]:
        scene.append(_message_renderable(m))
    _render_to_svg(scene, output, title="amatelier watcher — opening")


def render_scene_gate(
    rt: sqlite3.Row, messages: list[sqlite3.Row], output: Path
) -> bool:
    """GATE moment; returns True if a real GATE was found, False if a
    Judge moderation message was used as fallback."""
    # Find a GATE
    for i, m in enumerate(messages):
        if is_gate((m["agent_name"] or "").lower(), m["message"] or ""):
            # Two messages of context before + the GATE + one after if present
            start = max(0, i - 2)
            end = min(len(messages), i + 2)
            scene = [
                _header_panel(rt, i + 1, 1, duration="-"),
                *[_message_renderable(msg) for msg in messages[start:end]],
            ]
            _render_to_svg(scene, output, title="amatelier watcher — GATE moment")
            return True

    # Fallback — grab any Judge message
    for i, m in enumerate(messages):
        if (m["agent_name"] or "").lower() == "judge":
            start = max(0, i - 2)
            end = min(len(messages), i + 2)
            scene = [
                _header_panel(rt, i + 1, 0, duration="-"),
                *[_message_renderable(msg) for msg in messages[start:end]],
            ]
            _render_to_svg(scene, output, title="amatelier watcher — Judge moderation")
            return False

    return False


def render_scene_round_transition(
    rt: sqlite3.Row, messages: list[sqlite3.Row], output: Path
) -> bool:
    """Round-transition rule + opening of round 2. Returns True if a
    later round exists, False if the RT was single-round."""
    rounds = sorted({m["round"] for m in messages if m["round"]})
    if len(rounds) < 2:
        return False
    target_round = rounds[1]
    idx = next(i for i, m in enumerate(messages) if m["round"] == target_round)
    scene = [
        _header_panel(rt, idx, 0, duration="-"),
        Rule(title=f"[bold]Round {target_round}[/bold]", style="blue"),
    ]
    # Up to 4 messages of the new round
    for m in messages[idx : idx + 4]:
        scene.append(_message_renderable(m))
    _render_to_svg(scene, output, title=f"amatelier watcher — round {target_round}")
    return True


def render_scene_summary(
    rt: sqlite3.Row, messages: list[sqlite3.Row], output: Path
) -> None:
    """Final session summary panel."""
    scene = [_summary_panel(rt, messages)]
    _render_to_svg(scene, output, title="amatelier watcher — session summary")


# ── Transcript + artifacts ────────────────────────────────────────────


def write_transcript(
    rt: sqlite3.Row, messages: list[sqlite3.Row], output: Path
) -> None:
    lines = [
        f"# Transcript — RT {rt['id']}",
        "",
        f"- **Topic:** {rt['topic']}",
        f"- **Status:** {rt['status']}",
        f"- **Messages:** {len(messages)}",
        f"- **Created:** {_fmt_time(rt['created_at'])}",
        "",
        "---",
        "",
    ]
    current_round: int | None = None
    for m in messages:
        round_num = m["round"]
        if round_num and round_num != current_round:
            current_round = round_num
            lines.append(f"\n## Round {round_num}\n")
        agent = (m["agent_name"] or "unknown").lower()
        role = agent_role(agent)
        ts = _fmt_time(m["timestamp"])
        gate = " ★" if is_gate(agent, m["message"] or "") else ""
        lines.append(f"### {agent} · {role} · {ts}{gate}\n")
        lines.append((m["message"] or "").strip())
        lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote {output}")


def copy_digest_if_present(rt: sqlite3.Row, output_dir: Path) -> None:
    digest_src = paths.user_digest_dir() / f"digest-{rt['id']}.json"
    if digest_src.exists():
        dst = output_dir / "digest.json"
        shutil.copy2(digest_src, dst)
        print(f"  wrote {dst}")
    else:
        print(f"  (no digest file found at {digest_src})")


def copy_latest_result(output_dir: Path) -> None:
    src = paths.user_digest_dir() / "latest-result.md"
    if src.exists():
        dst = output_dir / "latest-result.md"
        shutil.copy2(src, dst)
        print(f"  wrote {dst}")


# ── CLI ────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render_session.py",
        description=(
            "Render an amatelier roundtable to SVG scenes + markdown transcript. "
            "Use for committing example sessions to examples/sessions/."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--rt", help="Roundtable ID to render")
    group.add_argument(
        "--latest",
        action="store_true",
        help="Render the most recent roundtable (closed if possible, else any)",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output directory (will be created; existing files overwritten)",
    )
    ns = parser.parse_args(argv)

    conn = _open_db()
    rt = _pick_rt(conn, ns.rt, ns.latest)
    messages = _messages(conn, rt["id"])

    if not messages:
        print(f"RT {rt['id']} has no messages yet. Nothing to render.", file=sys.stderr)
        return 1

    out_dir = Path(ns.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = out_dir / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)

    print(f"\nRendering RT {rt['id']!r} ({len(messages)} messages) -> {out_dir}\n")

    render_scene_header(rt, messages, screenshots_dir / "01-header-and-opening.svg")
    had_gate = render_scene_gate(rt, messages, screenshots_dir / "02-gate.svg")
    had_round_2 = render_scene_round_transition(
        rt, messages, screenshots_dir / "03-round-transition.svg"
    )
    render_scene_summary(rt, messages, screenshots_dir / "04-session-summary.svg")

    write_transcript(rt, messages, out_dir / "transcript.md")
    copy_digest_if_present(rt, out_dir)
    copy_latest_result(out_dir)

    print("\nDone.")
    print(f"  GATE scene: {'real GATE' if had_gate else 'fallback (Judge moderation)'}")
    print(f"  Round transition: {'round 2+ rendered' if had_round_2 else 'single-round RT, skipped'}")
    print(f"  Output: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
