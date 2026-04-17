"""Roundtable MCP Server — the room where agents discuss."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "roundtable.db"

mcp = FastMCP("Roundtable")


def get_db() -> sqlite3.Connection:
    """Get a WAL-mode SQLite connection."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS roundtables (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            participants TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            created_at REAL,
            closed_at REAL,
            cut_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roundtable_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp REAL NOT NULL,
            FOREIGN KEY (roundtable_id) REFERENCES roundtables(id)
        );
        CREATE TABLE IF NOT EXISTS read_cursors (
            agent_name TEXT,
            roundtable_id TEXT,
            last_read_id INTEGER DEFAULT 0,
            PRIMARY KEY (agent_name, roundtable_id)
        );
        CREATE INDEX IF NOT EXISTS idx_messages_roundtable ON messages(roundtable_id, id);
    """)
    conn.commit()
    conn.close()


def _active_roundtable_id(conn: sqlite3.Connection) -> str | None:
    """Get the current open roundtable ID."""
    row = conn.execute(
        "SELECT id FROM roundtables WHERE status='open' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


# --- Facilitator tools (Assistant) ---

@mcp.tool()
async def roundtable_open(topic: str, participants: list[str]) -> dict:
    """Open a new roundtable discussion.

    Args:
        topic: The topic/question for the team to discuss
        participants: List of agent names invited to participate
    """
    import uuid
    rt_id = uuid.uuid4().hex[:12]
    conn = get_db()

    # Close any existing open roundtable
    conn.execute("UPDATE roundtables SET status='closed', closed_at=? WHERE status='open'", (time.time(),))

    conn.execute(
        "INSERT INTO roundtables (id, topic, participants, status, created_at) VALUES (?, ?, ?, 'open', ?)",
        (rt_id, topic, json.dumps(participants), time.time()),
    )
    conn.commit()
    conn.close()
    logger.info("Roundtable %s opened: %s", rt_id, topic)
    return {"roundtable_id": rt_id, "topic": topic, "participants": participants, "status": "open"}


@mcp.tool()
async def roundtable_close() -> dict:
    """Close the active roundtable and return the full transcript."""
    conn = get_db()
    rt_id = _active_roundtable_id(conn)
    if not rt_id:
        conn.close()
        return {"error": "No active roundtable"}

    conn.execute("UPDATE roundtables SET status='closed', closed_at=? WHERE id=?", (time.time(), rt_id))

    rows = conn.execute(
        "SELECT agent_name, message, timestamp FROM messages WHERE roundtable_id=? ORDER BY id",
        (rt_id,),
    ).fetchall()
    conn.commit()
    conn.close()

    transcript = [{"agent": r["agent_name"], "message": r["message"], "timestamp": r["timestamp"]} for r in rows]
    logger.info("Roundtable %s closed with %d messages", rt_id, len(transcript))
    return {"roundtable_id": rt_id, "status": "closed", "message_count": len(transcript), "transcript": transcript}


@mcp.tool()
async def roundtable_cut(reason: str) -> dict:
    """Force-end the active roundtable (consensus, repetition, token ceiling, etc).

    Args:
        reason: Why the discussion is being cut (consensus, repetition, diminishing_returns, token_ceiling)
    """
    conn = get_db()
    rt_id = _active_roundtable_id(conn)
    if not rt_id:
        conn.close()
        return {"error": "No active roundtable"}

    conn.execute(
        "UPDATE roundtables SET status='cut', closed_at=?, cut_reason=? WHERE id=?",
        (time.time(), reason, rt_id),
    )
    conn.commit()
    conn.close()
    logger.info("Roundtable %s cut: %s", rt_id, reason)
    return {"roundtable_id": rt_id, "status": "cut", "reason": reason}


# --- Worker tools (all agents) ---

@mcp.tool()
async def roundtable_join(agent_name: str) -> dict:
    """Join the active roundtable discussion.

    Args:
        agent_name: Your agent name (e.g. elena, marcus, naomi)
    """
    conn = get_db()
    rt_id = _active_roundtable_id(conn)
    if not rt_id:
        conn.close()
        return {"error": "No active roundtable to join"}

    row = conn.execute("SELECT topic, participants FROM roundtables WHERE id=?", (rt_id,)).fetchone()

    # Initialize read cursor
    conn.execute(
        "INSERT OR REPLACE INTO read_cursors (agent_name, roundtable_id, last_read_id) VALUES (?, ?, 0)",
        (agent_name, rt_id),
    )
    conn.commit()
    conn.close()

    return {
        "roundtable_id": rt_id,
        "topic": row["topic"],
        "participants": json.loads(row["participants"]),
        "joined": agent_name,
    }


@mcp.tool()
async def roundtable_speak(agent_name: str, message: str) -> dict:
    """Post a message to the active roundtable discussion.

    Args:
        agent_name: Your agent name
        message: Your contribution to the discussion
    """
    conn = get_db()
    rt_id = _active_roundtable_id(conn)
    if not rt_id:
        conn.close()
        return {"error": "No active roundtable"}

    ts = time.time()
    conn.execute(
        "INSERT INTO messages (roundtable_id, agent_name, message, timestamp) VALUES (?, ?, ?, ?)",
        (rt_id, agent_name, message, ts),
    )
    conn.commit()

    count = conn.execute("SELECT COUNT(*) as c FROM messages WHERE roundtable_id=?", (rt_id,)).fetchone()["c"]
    conn.close()

    return {"roundtable_id": rt_id, "agent": agent_name, "posted": True, "total_messages": count}


@mcp.tool()
async def roundtable_listen(agent_name: str) -> dict:
    """Read all messages since your last read. First call returns full history.

    Args:
        agent_name: Your agent name
    """
    conn = get_db()
    rt_id = _active_roundtable_id(conn)
    if not rt_id:
        # Check for most recently closed roundtable
        row = conn.execute(
            "SELECT id FROM roundtables WHERE status IN ('closed','cut') ORDER BY closed_at DESC LIMIT 1"
        ).fetchone()
        if row:
            rt_id = row["id"]
        else:
            conn.close()
            return {"error": "No roundtable found"}

    # Get cursor
    cursor_row = conn.execute(
        "SELECT last_read_id FROM read_cursors WHERE agent_name=? AND roundtable_id=?",
        (agent_name, rt_id),
    ).fetchone()
    last_read = cursor_row["last_read_id"] if cursor_row else 0

    # Get new messages
    rows = conn.execute(
        "SELECT id, agent_name, message, timestamp FROM messages WHERE roundtable_id=? AND id>? ORDER BY id",
        (rt_id, last_read),
    ).fetchall()

    # Update cursor
    if rows:
        new_cursor = rows[-1]["id"]
        conn.execute(
            "INSERT OR REPLACE INTO read_cursors (agent_name, roundtable_id, last_read_id) VALUES (?, ?, ?)",
            (agent_name, rt_id, new_cursor),
        )
        conn.commit()

    conn.close()

    messages = [{"agent": r["agent_name"], "message": r["message"], "timestamp": r["timestamp"]} for r in rows]

    # Get roundtable status
    status_conn = get_db()
    status_row = status_conn.execute("SELECT status FROM roundtables WHERE id=?", (rt_id,)).fetchone()
    status_conn.close()

    return {
        "roundtable_id": rt_id,
        "new_messages": len(messages),
        "messages": messages,
        "roundtable_status": status_row["status"] if status_row else "unknown",
    }


@mcp.tool()
async def roundtable_leave(agent_name: str) -> dict:
    """Leave the active roundtable.

    Args:
        agent_name: Your agent name
    """
    return {"agent": agent_name, "left": True}


# --- Admin tools (Opus) ---

@mcp.tool()
async def roundtable_review(roundtable_id: str) -> dict:
    """Read the full transcript of a completed roundtable.

    Args:
        roundtable_id: ID of the roundtable to review
    """
    conn = get_db()
    rt = conn.execute("SELECT * FROM roundtables WHERE id=?", (roundtable_id,)).fetchone()
    if not rt:
        conn.close()
        return {"error": f"Roundtable {roundtable_id} not found"}

    rows = conn.execute(
        "SELECT agent_name, message, timestamp FROM messages WHERE roundtable_id=? ORDER BY id",
        (roundtable_id,),
    ).fetchall()
    conn.close()

    transcript = [{"agent": r["agent_name"], "message": r["message"], "timestamp": r["timestamp"]} for r in rows]
    return {
        "roundtable_id": roundtable_id,
        "topic": rt["topic"],
        "participants": json.loads(rt["participants"]),
        "status": rt["status"],
        "cut_reason": rt["cut_reason"],
        "message_count": len(transcript),
        "transcript": transcript,
    }


@mcp.tool()
async def roundtable_history(limit: int = 20) -> dict:
    """List past roundtables.

    Args:
        limit: Maximum number to return (default 20)
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT id, topic, status, cut_reason, created_at, closed_at FROM roundtables ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()

    return {
        "roundtables": [
            {
                "id": r["id"],
                "topic": r["topic"],
                "status": r["status"],
                "cut_reason": r["cut_reason"],
                "created_at": r["created_at"],
                "closed_at": r["closed_at"],
            }
            for r in rows
        ]
    }


@mcp.tool()
async def roundtable_status() -> dict:
    """Get the current roundtable status — who's in, message count, is it open."""
    conn = get_db()
    rt_id = _active_roundtable_id(conn)
    if not rt_id:
        conn.close()
        return {"active": False, "message": "No active roundtable"}

    rt = conn.execute("SELECT * FROM roundtables WHERE id=?", (rt_id,)).fetchone()
    count = conn.execute("SELECT COUNT(*) as c FROM messages WHERE roundtable_id=?", (rt_id,)).fetchone()["c"]

    # Get unique speakers
    speakers = conn.execute(
        "SELECT DISTINCT agent_name FROM messages WHERE roundtable_id=?", (rt_id,)
    ).fetchall()
    conn.close()

    return {
        "active": True,
        "roundtable_id": rt_id,
        "topic": rt["topic"],
        "participants": json.loads(rt["participants"]),
        "active_speakers": [s["agent_name"] for s in speakers],
        "message_count": count,
        "status": rt["status"],
    }


# --- Init and run ---

init_db()


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
