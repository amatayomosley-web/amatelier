"""Shared database access for roundtable agents.

Single source of truth for get_db(), listen(), speak(), and related functions.
Used by claude_agent.py, gemini_agent.py, and roundtable_runner.py.

Includes auto-migration: versioned .sql files in engine/migrations/ are applied
on first connection. Safe for concurrent access (WAL mode + busy_timeout).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SUITE_ROOT = Path(__file__).resolve().parent.parent

# Amatayo Standard dual-layer paths: bundled assets stay in SUITE_ROOT
# (read-only post-install); mutable runtime state goes to WRITE_ROOT.
try:
    from amatelier import paths as _amatelier_paths
    _amatelier_paths.ensure_user_data()
    WRITE_ROOT = _amatelier_paths.user_data_dir()
except Exception:
    WRITE_ROOT = SUITE_ROOT

DB_PATH = WRITE_ROOT / "roundtable-server" / "roundtable.db"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_migrated = False  # module-level flag — migrate once per process


def get_db() -> sqlite3.Connection:
    global _migrated
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")  # 15s — concurrent RT processes on Windows
    conn.row_factory = sqlite3.Row
    if not _migrated:
        _apply_migrations(conn)
        _migrated = True
    return conn


def _apply_migrations(conn: sqlite3.Connection):
    """Apply any unapplied SQL migrations. Idempotent, safe for concurrent access."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            applied_at REAL NOT NULL
        )
    """)
    conn.commit()

    applied = {row[0] for row in conn.execute("SELECT version FROM _migrations").fetchall()}

    if not MIGRATIONS_DIR.exists():
        return

    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        try:
            version = int(sql_file.name.split("_")[0])
        except ValueError:
            continue
        if version in applied:
            continue

        logger.info("Applying migration %s", sql_file.name)
        conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO _migrations (version, filename, applied_at) VALUES (?, ?, ?)",
            (version, sql_file.name, time.time()),
        )
        conn.commit()
        logger.info("Migration %s applied", sql_file.name)


def get_active_roundtable() -> str | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM roundtables WHERE status='open' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None


def listen(agent_name: str, rt_id: str) -> list[dict]:
    """Read all messages since last read. Uses context manager for safe cleanup."""
    with get_db() as conn:
        cursor_row = conn.execute(
            "SELECT last_read_id FROM read_cursors WHERE agent_name=? AND roundtable_id=?",
            (agent_name, rt_id),
        ).fetchone()
        last_read = cursor_row["last_read_id"] if cursor_row else 0

        rows = conn.execute(
            "SELECT id, agent_name, message, timestamp FROM messages "
            "WHERE roundtable_id=? AND id>? ORDER BY id",
            (rt_id, last_read),
        ).fetchall()

        if rows:
            conn.execute(
                "INSERT OR REPLACE INTO read_cursors "
                "(agent_name, roundtable_id, last_read_id) VALUES (?, ?, ?)",
                (agent_name, rt_id, rows[-1]["id"]),
            )
            conn.commit()

    return [{"agent": r["agent_name"], "message": r["message"]} for r in rows]


def speak(agent_name: str, rt_id: str, message: str):
    """Post a message to the roundtable. Uses context manager for safe cleanup."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (roundtable_id, agent_name, message, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (rt_id, agent_name, message, time.time()),
        )
        conn.commit()


def is_roundtable_open(rt_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM roundtables WHERE id=?", (rt_id,)
        ).fetchone()
        return row["status"] == "open" if row else False


def init_read_cursor(agent_name: str, rt_id: str):
    """Initialize a read cursor for an agent joining a roundtable."""
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO read_cursors "
            "(agent_name, roundtable_id, last_read_id) VALUES (?, ?, 0)",
            (agent_name, rt_id),
        )
        conn.commit()


def recall(rt_id: str, agent_filter: str = "", keyword: str = "",
           round_num: int = 0, limit: int = 10) -> list[dict]:
    """Retrieve specific transcript segments from the current roundtable.

    Agents call this to pull full text of prior contributions they see
    referenced in the debate state index. Doesn't cost a floor turn.

    Filters (combinable):
      agent_filter: "<worker>" — only that agent's messages
      keyword: "caching" — messages containing this keyword (case-insensitive)
      round_num: 2 — only messages from that round (matched via ROUND markers)

    Returns: list of {agent, message, round} dicts, most recent first.
    """
    with get_db() as conn:
        # Get all messages for this RT
        rows = conn.execute(
            "SELECT id, agent_name, message, timestamp FROM messages "
            "WHERE roundtable_id=? ORDER BY id",
            (rt_id,),
        ).fetchall()

    if not rows:
        return []

    # Tag each message with its round number
    current_round = 0
    tagged: list[dict] = []
    for r in rows:
        msg_text = r["message"]
        agent = r["agent_name"]

        # Track round boundaries from runner messages
        if agent == "runner" and msg_text.startswith("ROUND ") and ": begin" in msg_text:
            try:
                current_round = int(msg_text.split("ROUND")[1].split(":")[0].strip())
            except (ValueError, IndexError):
                pass
            continue

        # Skip runner infrastructure messages
        if agent in ("runner", "assistant"):
            continue
        # Skip PASS messages
        if msg_text.strip().upper() == "PASS":
            continue

        tagged.append({
            "agent": agent,
            "message": msg_text,
            "round": current_round,
        })

    # Apply filters
    results = tagged

    if agent_filter:
        agent_lower = agent_filter.lower()
        results = [m for m in results if m["agent"].lower() == agent_lower]

    if keyword:
        kw_lower = keyword.lower()
        results = [m for m in results if kw_lower in m["message"].lower()]

    if round_num > 0:
        results = [m for m in results if m["round"] == round_num]

    # Most recent first, capped
    results.reverse()
    return results[:limit]


def build_transcript_index(rt_id: str) -> str:
    """Build a compact one-line-per-contribution index of the transcript.

    This is injected into agent context alongside the debate state so they
    know what's available to recall. Each line shows:
      [round] agent: first 80 chars of their message

    Compact enough to always fit in context (~50 bytes per contribution).
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT agent_name, message FROM messages "
            "WHERE roundtable_id=? ORDER BY id",
            (rt_id,),
        ).fetchall()

    if not rows:
        return ""

    current_round = 0
    lines = []
    for r in rows:
        agent = r["agent_name"]
        msg = r["message"]

        if agent == "runner" and msg.startswith("ROUND ") and ": begin" in msg:
            try:
                current_round = int(msg.split("ROUND")[1].split(":")[0].strip())
            except (ValueError, IndexError):
                pass
            continue

        if agent in ("runner", "assistant"):
            continue
        if msg.strip().upper() == "PASS":
            continue

        # One-line summary: first 80 chars, clean up newlines
        preview = msg.replace("\n", " ")[:80].rstrip()
        lines.append(f"  R{current_round} {agent}: {preview}")

    return "\n".join(lines)
