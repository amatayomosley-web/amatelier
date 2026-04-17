"""Integration test for the roundtable infrastructure.

Tests the actual SQLite DB, speak/listen/join mechanics, and
verifies that messages flow correctly between agents.

Run: python test_roundtable.py
"""

import json
import sqlite3
import time
import uuid
from pathlib import Path

DB_PATH = Path(__file__).parent / "roundtable.db"

PASS = 0
FAIL = 0


def result(name: str, passed: bool, detail: str = ""):
    global PASS, FAIL
    if passed:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} — {detail}")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def test_db_exists():
    print("\n--- Test: DB exists and schema is valid ---")
    conn = get_db()

    # Check tables exist
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [t["name"] for t in tables]

    result("roundtables table exists", "roundtables" in table_names)
    result("messages table exists", "messages" in table_names)
    result("read_cursors table exists", "read_cursors" in table_names)
    conn.close()


def test_open_roundtable():
    print("\n--- Test: Open a roundtable ---")
    conn = get_db()

    # Close any existing open roundtables
    conn.execute("UPDATE roundtables SET status='closed', closed_at=? WHERE status='open'", (time.time(),))

    rt_id = f"test-{uuid.uuid4().hex[:8]}"
    participants = ["elena", "marcus", "clare", "simon", "naomi", "judge"]

    conn.execute(
        "INSERT INTO roundtables (id, topic, participants, status, created_at) VALUES (?, ?, ?, 'open', ?)",
        (rt_id, "Test roundtable", json.dumps(participants), time.time()),
    )
    conn.commit()

    # Verify it's open
    row = conn.execute("SELECT * FROM roundtables WHERE id=?", (rt_id,)).fetchone()
    result("roundtable created", row is not None)
    result("status is open", row["status"] == "open")
    result("topic stored", row["topic"] == "Test roundtable")
    result("participants stored", json.loads(row["participants"]) == participants)

    conn.close()
    return rt_id


def test_join(rt_id: str):
    print("\n--- Test: Agents join via read cursor ---")
    conn = get_db()

    for agent in ["elena", "marcus", "clare", "simon", "naomi", "judge"]:
        conn.execute(
            "INSERT OR REPLACE INTO read_cursors (agent_name, roundtable_id, last_read_id) VALUES (?, ?, 0)",
            (agent, rt_id),
        )
    conn.commit()

    cursors = conn.execute(
        "SELECT agent_name FROM read_cursors WHERE roundtable_id=?", (rt_id,)
    ).fetchall()
    result("6 agents joined", len(cursors) == 6, f"got {len(cursors)}")
    conn.close()


def test_speak(rt_id: str):
    print("\n--- Test: Agents speak to the roundtable ---")
    conn = get_db()

    messages = [
        ("assistant", "Topic: Is the retrieval pipeline well-structured?"),
        ("elena", "The orchestrator imports everything — it's the hub. Centroids.dart is too large at 519 lines."),
        ("marcus", "The preprocessor has a hardcoded synonym map. That's data pretending to be code."),
        ("clare", "9 files for 1741 lines is a healthy ratio. The two biggest files are the problem."),
        ("simon", "Don't split everything. This is a solo dev project — more files means more navigation overhead."),
        ("naomi", "Nobody mentioned error handling. Every catch block swallows the error silently."),
    ]

    for agent, msg in messages:
        conn.execute(
            "INSERT INTO messages (roundtable_id, agent_name, message, timestamp) VALUES (?, ?, ?, ?)",
            (rt_id, agent, msg, time.time()),
        )
        time.sleep(0.01)  # Ensure distinct timestamps
    conn.commit()

    count = conn.execute(
        "SELECT COUNT(*) as c FROM messages WHERE roundtable_id=?", (rt_id,)
    ).fetchone()["c"]
    result("6 messages posted", count == 6, f"got {count}")

    # Verify ordering
    rows = conn.execute(
        "SELECT agent_name FROM messages WHERE roundtable_id=? ORDER BY id", (rt_id,)
    ).fetchall()
    agents = [r["agent_name"] for r in rows]
    result("message order preserved", agents == ["assistant", "elena", "marcus", "clare", "simon", "naomi"])

    conn.close()


def test_listen(rt_id: str):
    print("\n--- Test: Listen with cursor tracking ---")
    conn = get_db()

    # Elena listens — should get all 6 messages (cursor starts at 0)
    cursor_row = conn.execute(
        "SELECT last_read_id FROM read_cursors WHERE agent_name='elena' AND roundtable_id=?",
        (rt_id,),
    ).fetchone()
    last_read = cursor_row["last_read_id"]
    result("elena cursor starts at 0", last_read == 0)

    rows = conn.execute(
        "SELECT id, agent_name, message FROM messages WHERE roundtable_id=? AND id>? ORDER BY id",
        (rt_id, last_read),
    ).fetchall()
    result("elena sees all 6 messages", len(rows) == 6, f"got {len(rows)}")

    # Update elena's cursor
    new_cursor = rows[-1]["id"]
    conn.execute(
        "INSERT OR REPLACE INTO read_cursors (agent_name, roundtable_id, last_read_id) VALUES (?, ?, ?)",
        ("elena", rt_id, new_cursor),
    )
    conn.commit()

    # Elena listens again — should get 0 new messages
    rows2 = conn.execute(
        "SELECT id FROM messages WHERE roundtable_id=? AND id>? ORDER BY id",
        (rt_id, new_cursor),
    ).fetchall()
    result("elena sees 0 new messages after cursor update", len(rows2) == 0)

    # Judge posts feedback
    conn.execute(
        "INSERT INTO messages (roundtable_id, agent_name, message, timestamp) VALUES (?, ?, ?, ?)",
        (rt_id, "judge", "Elena: read centroids.dart and bring numbers. Marcus: engage with Simon's counter.", time.time()),
    )
    conn.commit()

    # Elena listens — should get only the judge's message
    rows3 = conn.execute(
        "SELECT id, agent_name FROM messages WHERE roundtable_id=? AND id>? ORDER BY id",
        (rt_id, new_cursor),
    ).fetchall()
    result("elena sees only judge's new message", len(rows3) == 1, f"got {len(rows3)}")
    result("new message is from judge", rows3[0]["agent_name"] == "judge" if rows3 else False)

    conn.close()


def test_close(rt_id: str):
    print("\n--- Test: Close roundtable and get transcript ---")
    conn = get_db()

    conn.execute(
        "UPDATE roundtables SET status='closed', closed_at=? WHERE id=?",
        (time.time(), rt_id),
    )
    conn.commit()

    row = conn.execute("SELECT status FROM roundtables WHERE id=?", (rt_id,)).fetchone()
    result("roundtable closed", row["status"] == "closed")

    # Full transcript
    rows = conn.execute(
        "SELECT agent_name, message FROM messages WHERE roundtable_id=? ORDER BY id",
        (rt_id,),
    ).fetchall()
    result("transcript has 7 messages (6 workers + judge)", len(rows) == 7, f"got {len(rows)}")

    # Verify all agents present
    agents = set(r["agent_name"] for r in rows)
    expected = {"assistant", "elena", "marcus", "clare", "simon", "naomi", "judge"}
    result("all agents in transcript", agents == expected, f"missing: {expected - agents}")

    conn.close()


def test_cut(rt_id: str):
    print("\n--- Test: Cut roundtable ---")
    conn = get_db()

    # Reopen for cut test
    new_rt = f"test-cut-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO roundtables (id, topic, participants, status, created_at) VALUES (?, ?, ?, 'open', ?)",
        (new_rt, "Cut test", json.dumps(["elena"]), time.time()),
    )
    conn.commit()

    # Cut it
    conn.execute(
        "UPDATE roundtables SET status='cut', closed_at=?, cut_reason=? WHERE id=?",
        (time.time(), "token_ceiling", new_rt),
    )
    conn.commit()

    row = conn.execute("SELECT status, cut_reason FROM roundtables WHERE id=?", (new_rt,)).fetchone()
    result("roundtable status is cut", row["status"] == "cut")
    result("cut reason stored", row["cut_reason"] == "token_ceiling")

    conn.close()


def test_concurrent_writers():
    print("\n--- Test: Concurrent write safety (WAL mode) ---")
    conn = get_db()

    rt_id = f"test-wal-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO roundtables (id, topic, participants, status, created_at) VALUES (?, ?, ?, 'open', ?)",
        (rt_id, "WAL test", json.dumps(["a", "b"]), time.time()),
    )
    conn.commit()
    conn.close()

    # Simulate two agents writing from separate connections
    conn1 = get_db()
    conn2 = get_db()

    conn1.execute(
        "INSERT INTO messages (roundtable_id, agent_name, message, timestamp) VALUES (?, 'agent_a', 'msg from a', ?)",
        (rt_id, time.time()),
    )
    conn1.commit()

    conn2.execute(
        "INSERT INTO messages (roundtable_id, agent_name, message, timestamp) VALUES (?, 'agent_b', 'msg from b', ?)",
        (rt_id, time.time()),
    )
    conn2.commit()

    # Verify both messages exist
    check = get_db()
    count = check.execute(
        "SELECT COUNT(*) as c FROM messages WHERE roundtable_id=?", (rt_id,)
    ).fetchone()["c"]
    result("both concurrent writes succeeded", count == 2, f"got {count}")

    conn1.close()
    conn2.close()
    check.close()


def test_gemini_agent_loadable():
    print("\n--- Test: gemini_agent.py imports and functions exist ---")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gemini_agent",
        Path(__file__).parent.parent / "engine" / "gemini_agent.py",
    )
    result("gemini_agent.py found", spec is not None)

    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            result("gemini_agent.py imports cleanly", True)
            result("listen() exists", hasattr(mod, "listen"))
            result("speak() exists", hasattr(mod, "speak"))
            result("call_gemini() exists", hasattr(mod, "call_gemini"))
            result("run_agent() exists", hasattr(mod, "run_agent"))
            result("load_agent_context() exists", hasattr(mod, "load_agent_context"))
        except Exception as e:
            result("gemini_agent.py imports cleanly", False, str(e))


def cleanup():
    """Remove test roundtables."""
    conn = get_db()
    conn.execute("DELETE FROM messages WHERE roundtable_id LIKE 'test-%'")
    conn.execute("DELETE FROM read_cursors WHERE roundtable_id LIKE 'test-%'")
    conn.execute("DELETE FROM roundtables WHERE id LIKE 'test-%'")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("ROUNDTABLE INFRASTRUCTURE TEST")
    print("=" * 60)

    test_db_exists()
    rt_id = test_open_roundtable()
    test_join(rt_id)
    test_speak(rt_id)
    test_listen(rt_id)
    test_close(rt_id)
    test_cut(rt_id)
    test_concurrent_writers()
    test_gemini_agent_loadable()
    cleanup()

    print("\n" + "=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 60)
