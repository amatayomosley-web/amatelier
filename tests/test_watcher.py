"""Tests for the watcher — DB-path resolution and rich/plain fallback logic.

These tests exercise the watcher against an in-memory-like SQLite fixture;
they do NOT spawn live processes or render to a real terminal.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def _seed_db(db_path: Path) -> None:
    """Create a minimal schema matching what roundtable_runner writes."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE roundtables (
            id TEXT PRIMARY KEY,
            topic TEXT,
            status TEXT,
            created_at TEXT
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roundtable_id TEXT,
            agent_name TEXT,
            message TEXT,
            round INTEGER,
            created_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO roundtables VALUES (?, ?, ?, ?)",
        ("rt-test", "hello world", "open", "2026-04-18T00:00:00"),
    )
    conn.executemany(
        "INSERT INTO messages (roundtable_id, agent_name, message, round, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("rt-test", "elena", "my take on the problem", 1, "2026-04-18T00:00:10"),
            ("rt-test", "marcus", "challenging that assumption", 1, "2026-04-18T00:00:20"),
            ("rt-test", "judge", "GATE: marcus - explicit challenge", 1, "2026-04-18T00:00:25"),
        ],
    )
    conn.commit()
    conn.close()


def test_agent_color_stable() -> None:
    from amatelier.tools import watch_roundtable as w

    assert w.agent_color("elena") == "cyan"
    assert w.agent_color("judge").startswith("bold")
    # Unknown agent gets a deterministic hash-based color
    c1 = w.agent_color("made-up-agent-xyz")
    c2 = w.agent_color("made-up-agent-xyz")
    assert c1 == c2


def test_agent_role_categorization() -> None:
    from amatelier.tools import watch_roundtable as w

    assert w.agent_role("elena") == "worker"
    assert w.agent_role("judge") == "judge"
    assert w.agent_role("therapist") == "therapist"
    assert w.agent_role("opus-therapist") == "therapist"
    assert w.agent_role("runner") == "runner"
    assert w.agent_role("steward") == "steward"
    assert w.agent_role("unknown") == "agent"


def test_open_db_returns_none_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from amatelier.tools import watch_roundtable as w

    monkeypatch.setenv("AMATELIER_WORKSPACE", str(tmp_path))
    # Force re-resolve of user_db_path by reloading the paths cache
    assert w._open_db() is None


def test_find_roundtable_returns_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from amatelier import paths
    from amatelier.tools import watch_roundtable as w

    monkeypatch.setenv("AMATELIER_WORKSPACE", str(tmp_path))
    db_path = paths.user_db_path()
    _seed_db(db_path)

    conn = w._open_db()
    assert conn is not None
    row = w._find_roundtable(conn, rt_id=None)
    assert row is not None
    assert row["id"] == "rt-test"
    assert row["status"] == "open"


def test_gate_detection() -> None:
    from amatelier.tools import watch_roundtable as w

    assert w.is_gate("judge", "GATE: marcus - test") is True
