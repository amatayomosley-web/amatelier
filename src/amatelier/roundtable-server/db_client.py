"""Roundtable DB client — used by Claude agents to speak/listen through the real DB.

Usage from bash (inside a Claude agent):
    python db_client.py open "Topic here" "elena,marcus,clare,simon,naomi,judge"
    python db_client.py join elena
    python db_client.py speak elena "My contribution text"
    python db_client.py listen elena
    python db_client.py status
    python db_client.py close
    python db_client.py cut "consensus"
    python db_client.py transcript
"""

import io
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

# Fix Windows cp1252 encoding for Unicode output
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Amatayo Standard dual-layer paths: DB is user-writable runtime state,
# so it must resolve to user_data_dir — not next to this source file.
# Fall back to the source-relative path only if amatelier isn't importable.
try:
    from amatelier import paths as _amatelier_paths
    _amatelier_paths.ensure_user_data()
    DB_PATH = _amatelier_paths.user_db_path()
except Exception:
    DB_PATH = Path(__file__).parent / "roundtable.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")  # 15s — 7 concurrent processes on Windows
    conn.row_factory = sqlite3.Row
    return conn


def get_active_rt(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT id FROM roundtables WHERE status='open' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def cmd_open(topic: str, participants_csv: str):
    conn = get_db()
    # Close any existing open roundtables
    conn.execute("UPDATE roundtables SET status='closed', closed_at=? WHERE status='open'", (time.time(),))
    rt_id = uuid.uuid4().hex[:12]
    participants = [p.strip() for p in participants_csv.split(",")]
    conn.execute(
        "INSERT INTO roundtables (id, topic, participants, status, created_at) VALUES (?, ?, ?, 'open', ?)",
        (rt_id, topic, json.dumps(participants), time.time()),
    )
    conn.commit()
    conn.close()
    print(json.dumps({"roundtable_id": rt_id, "topic": topic, "participants": participants, "status": "open"}))


def cmd_join(agent_name: str):
    conn = get_db()
    rt_id = get_active_rt(conn)
    if not rt_id:
        print(json.dumps({"error": "No active roundtable"}))
        conn.close()
        return
    conn.execute(
        "INSERT OR REPLACE INTO read_cursors (agent_name, roundtable_id, last_read_id) VALUES (?, ?, 0)",
        (agent_name, rt_id),
    )
    conn.commit()
    row = conn.execute("SELECT topic, participants FROM roundtables WHERE id=?", (rt_id,)).fetchone()
    conn.close()
    print(json.dumps({"roundtable_id": rt_id, "joined": agent_name, "topic": row["topic"]}))


def cmd_speak(agent_name: str, message: str):
    conn = get_db()
    rt_id = get_active_rt(conn)
    if not rt_id:
        print(json.dumps({"error": "No active roundtable"}))
        conn.close()
        return
    conn.execute(
        "INSERT INTO messages (roundtable_id, agent_name, message, timestamp) VALUES (?, ?, ?, ?)",
        (rt_id, agent_name, message, time.time()),
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) as c FROM messages WHERE roundtable_id=?", (rt_id,)).fetchone()["c"]
    conn.close()
    print(json.dumps({"roundtable_id": rt_id, "agent": agent_name, "posted": True, "total_messages": count}))


def cmd_listen(agent_name: str):
    conn = get_db()
    rt_id = get_active_rt(conn)
    if not rt_id:
        # Try most recently closed
        row = conn.execute(
            "SELECT id FROM roundtables WHERE status IN ('closed','cut') ORDER BY closed_at DESC LIMIT 1"
        ).fetchone()
        if row:
            rt_id = row["id"]
        else:
            print(json.dumps({"error": "No roundtable found"}))
            conn.close()
            return

    cursor_row = conn.execute(
        "SELECT last_read_id FROM read_cursors WHERE agent_name=? AND roundtable_id=?",
        (agent_name, rt_id),
    ).fetchone()
    last_read = cursor_row["last_read_id"] if cursor_row else 0

    rows = conn.execute(
        "SELECT id, agent_name, message, timestamp FROM messages WHERE roundtable_id=? AND id>? ORDER BY id",
        (rt_id, last_read),
    ).fetchall()

    if rows:
        conn.execute(
            "INSERT OR REPLACE INTO read_cursors (agent_name, roundtable_id, last_read_id) VALUES (?, ?, ?)",
            (agent_name, rt_id, rows[-1]["id"]),
        )
        conn.commit()

    conn.close()

    messages = [{"agent": r["agent_name"], "message": r["message"]} for r in rows]
    status_conn = get_db()
    status_row = status_conn.execute("SELECT status FROM roundtables WHERE id=?", (rt_id,)).fetchone()
    status_conn.close()

    print(json.dumps({
        "roundtable_id": rt_id,
        "new_messages": len(messages),
        "messages": messages,
        "roundtable_status": status_row["status"] if status_row else "unknown",
    }))


def cmd_status():
    conn = get_db()
    rt_id = get_active_rt(conn)
    if not rt_id:
        print(json.dumps({"active": False}))
        conn.close()
        return

    rt = conn.execute("SELECT * FROM roundtables WHERE id=?", (rt_id,)).fetchone()
    count = conn.execute("SELECT COUNT(*) as c FROM messages WHERE roundtable_id=?", (rt_id,)).fetchone()["c"]
    speakers = conn.execute(
        "SELECT DISTINCT agent_name FROM messages WHERE roundtable_id=?", (rt_id,)
    ).fetchall()
    conn.close()

    print(json.dumps({
        "active": True,
        "roundtable_id": rt_id,
        "topic": rt["topic"],
        "participants": json.loads(rt["participants"]),
        "active_speakers": [s["agent_name"] for s in speakers],
        "message_count": count,
    }))


def cmd_close():
    conn = get_db()
    rt_id = get_active_rt(conn)
    if not rt_id:
        print(json.dumps({"error": "No active roundtable"}))
        conn.close()
        return

    conn.execute("UPDATE roundtables SET status='closed', closed_at=? WHERE id=?", (time.time(), rt_id))
    rows = conn.execute(
        "SELECT agent_name, message, timestamp FROM messages WHERE roundtable_id=? ORDER BY id",
        (rt_id,),
    ).fetchall()
    conn.commit()
    conn.close()

    transcript = [{"agent": r["agent_name"], "message": r["message"]} for r in rows]
    print(json.dumps({
        "roundtable_id": rt_id,
        "status": "closed",
        "message_count": len(transcript),
        "transcript": transcript,
    }))


def cmd_cut(reason: str):
    conn = get_db()
    rt_id = get_active_rt(conn)
    if not rt_id:
        print(json.dumps({"error": "No active roundtable"}))
        conn.close()
        return

    conn.execute(
        "UPDATE roundtables SET status='cut', closed_at=?, cut_reason=? WHERE id=?",
        (time.time(), reason, rt_id),
    )
    conn.commit()
    conn.close()
    print(json.dumps({"roundtable_id": rt_id, "status": "cut", "reason": reason}))


def cmd_recall(agent_filter: str = "", keyword: str = "", round_num: int = 0):
    """Retrieve specific transcript segments from the active roundtable.

    Agents use this to pull full text of prior contributions. No floor turn cost.

    Usage:
        python db_client.py recall --agent elena           # Elena's messages
        python db_client.py recall --keyword caching       # Messages about caching
        python db_client.py recall --round 1               # Round 1 messages
        python db_client.py recall --agent marcus --round 2 # Marcus in round 2
    """
    conn = get_db()
    rt_id = get_active_rt(conn)
    if not rt_id:
        row = conn.execute(
            "SELECT id FROM roundtables ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        rt_id = row["id"] if row else None
    conn.close()

    if not rt_id:
        print(json.dumps({"error": "No roundtable found"}))
        return

    # Import from engine db module for the actual recall logic
    sys.path.insert(0, str(Path(__file__).parent.parent / "engine"))
    from db import recall as db_recall
    results = db_recall(rt_id, agent_filter=agent_filter, keyword=keyword,
                        round_num=round_num)

    print(json.dumps({
        "roundtable_id": rt_id,
        "query": {"agent": agent_filter, "keyword": keyword, "round": round_num},
        "results": len(results),
        "messages": results,
    }, indent=2))


def cmd_index():
    """Show the transcript index — compact one-line-per-contribution view."""
    conn = get_db()
    rt_id = get_active_rt(conn)
    if not rt_id:
        row = conn.execute(
            "SELECT id FROM roundtables ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        rt_id = row["id"] if row else None
    conn.close()

    if not rt_id:
        print(json.dumps({"error": "No roundtable found"}))
        return

    sys.path.insert(0, str(Path(__file__).parent.parent / "engine"))
    from db import build_transcript_index
    index = build_transcript_index(rt_id)
    print(index if index else "(no contributions yet)")


def cmd_transcript():
    conn = get_db()
    # Get most recent roundtable (open or closed)
    row = conn.execute(
        "SELECT id, topic, status FROM roundtables ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        print(json.dumps({"error": "No roundtables found"}))
        conn.close()
        return

    rt_id = row["id"]
    rows = conn.execute(
        "SELECT agent_name, message, timestamp FROM messages WHERE roundtable_id=? ORDER BY id",
        (rt_id,),
    ).fetchall()
    conn.close()

    transcript = [{"agent": r["agent_name"], "message": r["message"]} for r in rows]
    print(json.dumps({
        "roundtable_id": rt_id,
        "topic": row["topic"],
        "status": row["status"],
        "message_count": len(transcript),
        "transcript": transcript,
    }, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python db_client.py <command> [args...]")
        print("Commands: open, join, speak, listen, status, close, cut, transcript, recall, index")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "open" and len(sys.argv) >= 4:
        cmd_open(sys.argv[2], sys.argv[3])
    elif cmd == "join" and len(sys.argv) >= 3:
        cmd_join(sys.argv[2])
    elif cmd == "speak" and len(sys.argv) >= 4:
        cmd_speak(sys.argv[2], sys.argv[3])
    elif cmd == "listen" and len(sys.argv) >= 3:
        cmd_listen(sys.argv[2])
    elif cmd == "status":
        cmd_status()
    elif cmd == "close":
        cmd_close()
    elif cmd == "cut" and len(sys.argv) >= 3:
        cmd_cut(sys.argv[2])
    elif cmd == "transcript":
        cmd_transcript()
    elif cmd == "index":
        cmd_index()
    elif cmd == "recall":
        # Parse --agent, --keyword, --round flags
        agent_f = ""
        kw_f = ""
        round_f = 0
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--agent" and i + 1 < len(args):
                agent_f = args[i + 1]
                i += 2
            elif args[i] == "--keyword" and i + 1 < len(args):
                kw_f = args[i + 1]
                i += 2
            elif args[i] == "--round" and i + 1 < len(args):
                round_f = int(args[i + 1])
                i += 2
            else:
                i += 1
        cmd_recall(agent_filter=agent_f, keyword=kw_f, round_num=round_f)
    else:
        print(f"Unknown command or missing args: {cmd}")
        sys.exit(1)
