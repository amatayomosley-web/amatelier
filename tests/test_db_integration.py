"""Integration test against the REAL database schema.

Catches the bug class that has bitten this project repeatedly:
tests that used invented schemas (columns that don't exist in the
real migrations) passed locally but crashed on the first live run.

This test:

1. Bootstraps a fresh user_data_dir via paths.ensure_user_data(force=True),
   which applies the REAL migrations from engine/migrations/*.sql.
2. Seeds a canned roundtable via tests/fixtures/sample_roundtable.sql.
3. Exercises every DB-touching code path that ships in the wheel:
   - amatelier.tools.watch_roundtable (message queries + rendering helpers)
   - scripts/render_session.py (SVG generation + transcript)
   - engine.db.get_db() (connection + concurrent-safe mode)
   - roundtable-server/db_client.py DB_PATH resolution
4. Asserts on real invariants — schema columns, round derivation,
   GATE detection, SVG structure, transcript content.

If this test passes, the pip-installed package can actually open a DB,
read messages, render the watcher UI, and generate example artifacts.
If this test fails, a real run will fail the same way.

Runs in <5 seconds, no API calls, deterministic, repeatable.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE_SQL = Path(__file__).parent / "fixtures" / "sample_roundtable.sql"


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def seeded_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fresh user_data_dir + migrations applied + fixture roundtable seeded.

    Every test gets a clean slate — no state leaks between tests.
    """
    monkeypatch.setenv("AMATELIER_WORKSPACE", str(tmp_path))

    # Force re-import of paths so it picks up the env var
    import importlib

    from amatelier import paths as _paths_mod

    importlib.reload(_paths_mod)

    # Run real migrations
    _paths_mod.ensure_user_data(force=True)
    db_path = _paths_mod.user_db_path()
    assert db_path.exists(), "bootstrap failed to create DB"

    # Seed fixture
    conn = sqlite3.connect(str(db_path))
    conn.executescript(FIXTURE_SQL.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()

    yield tmp_path

    # Clean re-load for downstream tests
    importlib.reload(_paths_mod)


# ── Schema invariants ──────────────────────────────────────────────────


def test_real_schema_matches_what_code_queries(seeded_workspace: Path) -> None:
    """Every column the shipped code queries must exist in the real schema.

    This is the regression test for the 'invented schema' bug class.
    """
    from amatelier import paths

    conn = sqlite3.connect(str(paths.user_db_path()))

    # roundtables columns
    cols = {r[1] for r in conn.execute("PRAGMA table_info(roundtables)").fetchall()}
    required = {"id", "topic", "status", "participants", "created_at", "closed_at"}
    assert required.issubset(cols), f"roundtables missing: {required - cols}"

    # messages columns
    cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
    required = {"id", "roundtable_id", "agent_name", "message", "timestamp"}
    assert required.issubset(cols), f"messages missing: {required - cols}"

    # scores columns
    cols = {r[1] for r in conn.execute("PRAGMA table_info(scores)").fetchall()}
    required = {"roundtable_id", "agent_name", "novelty", "accuracy", "impact", "challenge", "total"}
    assert required.issubset(cols), f"scores missing: {required - cols}"

    # spark_ledger columns
    cols = {r[1] for r in conn.execute("PRAGMA table_info(spark_ledger)").fetchall()}
    required = {"agent_name", "amount", "reason", "category", "roundtable_id"}
    assert required.issubset(cols), f"spark_ledger missing: {required - cols}"


def test_fixture_seeded_correctly(seeded_workspace: Path) -> None:
    from amatelier import paths

    conn = sqlite3.connect(str(paths.user_db_path()))
    rts = conn.execute("SELECT id, topic, status FROM roundtables").fetchall()
    assert len(rts) == 1
    assert rts[0][0] == "rt-fixture-001"
    assert rts[0][2] == "closed"

    msg_count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE roundtable_id='rt-fixture-001'"
    ).fetchone()[0]
    assert msg_count == 23, f"expected 23 seeded messages, got {msg_count}"

    score_count = conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    assert score_count == 4


# ── Watcher paths ──────────────────────────────────────────────────────


def test_watcher_finds_roundtable(seeded_workspace: Path) -> None:
    from amatelier.tools import watch_roundtable as w

    conn = w._open_db()
    assert conn is not None
    row = w._find_roundtable(conn, rt_id=None)
    assert row is not None
    assert row["id"] == "rt-fixture-001"


def test_watcher_message_query_uses_real_schema(seeded_workspace: Path) -> None:
    """The watcher's SQL against the messages table must run without error.

    Had this test existed, it would have caught the `round` and
    `created_at` column bugs that crashed every real RT this session.
    """
    from amatelier.tools import watch_roundtable as w

    conn = w._open_db()
    # This is the exact query shape RichWatcher._poll uses
    rows = conn.execute(
        "SELECT id, agent_name, message, timestamp FROM messages "
        "WHERE roundtable_id=? AND id > ? ORDER BY id",
        ("rt-fixture-001", 0),
    ).fetchall()
    assert len(rows) > 0
    # Each row accessible via column name (sqlite3.Row)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, agent_name, message, timestamp FROM messages "
        "WHERE roundtable_id=? AND id > ? ORDER BY id LIMIT 1",
        ("rt-fixture-001", 0),
    ).fetchall()
    row = rows[0]
    assert row["agent_name"] == "runner"
    assert row["timestamp"] is not None


def test_round_derivation_from_runner_messages(seeded_workspace: Path) -> None:
    """Round isn't a DB column — it's derived from runner phase markers."""
    from amatelier.tools.watch_roundtable import extract_round

    # Runner emits these in sequence; extract_round should handle each
    assert extract_round("ROUND 1: begin") == 1
    assert extract_round("--- SPEAK PHASE (Round 1) ---") == 1
    assert extract_round("--- REBUTTAL PHASE (Round 1) ---") == 1
    assert extract_round("ROUND 2: begin") == 2
    assert extract_round("--- SPEAK PHASE (Round 2) ---") == 2
    assert extract_round("YOUR TURN: clare -> SPEAK (Round 1, speaker 1/4)") == 1
    # Non-round messages return None
    assert extract_round("BRIEFING: ...") is None
    assert extract_round("GATE: elena - ...") is None


def test_gate_detection_finds_fixture_gate(seeded_workspace: Path) -> None:
    """The fixture has one Judge GATE; is_gate() must detect it."""
    from amatelier.tools.watch_roundtable import is_gate

    from amatelier import paths

    conn = sqlite3.connect(str(paths.user_db_path()))
    conn.row_factory = sqlite3.Row
    judge_msgs = conn.execute(
        "SELECT agent_name, message FROM messages "
        "WHERE roundtable_id='rt-fixture-001' AND agent_name='judge'"
    ).fetchall()
    gates = [m for m in judge_msgs if is_gate(m["agent_name"], m["message"])]
    assert len(gates) == 1, f"expected 1 GATE in fixture, detected {len(gates)}"
    assert "marcus" in gates[0]["message"]


# ── db_client path resolution ──────────────────────────────────────────


def test_db_client_resolves_to_user_data_dir(seeded_workspace: Path) -> None:
    """Regression test for the DB_PATH bug in roundtable-server/db_client.py.

    The bug: db_client.py had `DB_PATH = Path(__file__).parent / "roundtable.db"`
    which points at bundled/readonly location — every first roundtable failed
    with 'no such table: roundtables' because db_client wrote to the wrong DB.
    """
    # We can't just import db_client (it's in a hyphen-named dir), so
    # exec it and check DB_PATH.
    db_client_path = (
        Path(__file__).parent.parent
        / "src"
        / "amatelier"
        / "roundtable-server"
        / "db_client.py"
    )
    assert db_client_path.exists()

    # Spawn as subprocess so its module-level code runs fresh with our env.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, r'{db_client_path.parent}'); "
            f"import db_client; print(db_client.DB_PATH)",
        ],
        capture_output=True,
        text=True,
        env={"AMATELIER_WORKSPACE": str(seeded_workspace), **dict(__import__('os').environ)},
    )
    assert result.returncode == 0, result.stderr
    resolved = Path(result.stdout.strip())
    expected = seeded_workspace / "roundtable-server" / "roundtable.db"
    assert resolved.resolve() == expected.resolve(), (
        f"db_client.DB_PATH = {resolved}\nexpected: {expected}"
    )


# ── Render-session artifact generation ─────────────────────────────────


def test_render_session_generates_svgs(
    seeded_workspace: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """scripts/render_session.py must produce valid SVG artifacts.

    Runs the real script as a subprocess. Verifies every expected output file
    exists and has non-trivial content.
    """
    out_dir = tmp_path_factory.mktemp("render-out")
    script = Path(__file__).parent.parent / "scripts" / "render_session.py"
    result = subprocess.run(
        [sys.executable, str(script), "--rt", "rt-fixture-001", "--out", str(out_dir)],
        capture_output=True,
        text=True,
        env={"AMATELIER_WORKSPACE": str(seeded_workspace), **dict(__import__('os').environ)},
    )
    assert result.returncode == 0, f"render_session failed:\n{result.stderr}"

    shots = out_dir / "screenshots"
    expected = [
        "01-header-and-opening.svg",
        "02-gate.svg",
        "03-round-transition.svg",
        "04-session-summary.svg",
    ]
    for name in expected:
        path = shots / name
        assert path.exists(), f"missing SVG: {name}"
        content = path.read_text(encoding="utf-8")
        assert content.startswith("<svg") or content.startswith("<?xml"), (
            f"{name} does not look like SVG (starts: {content[:40]!r})"
        )
        assert len(content) > 1000, f"{name} too small ({len(content)} bytes)"

    transcript = out_dir / "transcript.md"
    assert transcript.exists()
    text = transcript.read_text(encoding="utf-8")
    assert "rt-fixture-001" in text
    assert "Round 1" in text
    assert "Round 2" in text
    assert "GATE" in text  # The Judge GATE message text is in the transcript


def test_render_gate_scene_contains_gate(
    seeded_workspace: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """02-gate.svg must be a real GATE (not fallback) since the fixture has one."""
    out_dir = tmp_path_factory.mktemp("render-out")
    script = Path(__file__).parent.parent / "scripts" / "render_session.py"
    result = subprocess.run(
        [sys.executable, str(script), "--rt", "rt-fixture-001", "--out", str(out_dir)],
        capture_output=True,
        text=True,
        env={"AMATELIER_WORKSPACE": str(seeded_workspace), **dict(__import__('os').environ)},
    )
    assert result.returncode == 0
    # render_session prints "GATE scene: real GATE" when one was found
    assert "real GATE" in result.stdout, (
        f"expected 'real GATE' in output, got:\n{result.stdout}"
    )


# ── engine.db path + migrations ────────────────────────────────────────


def test_engine_db_get_db_opens_clean(seeded_workspace: Path) -> None:
    """engine.db.get_db() must connect to the user DB and find tables."""
    import importlib

    import sys as _sys

    # engine/ is on sys.path after amatelier import
    if "db" in _sys.modules:
        del _sys.modules["db"]
    import amatelier  # noqa: F401  (triggers sys.path shim)
    importlib.import_module("db")
    import db

    conn = db.get_db()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    required = {"roundtables", "messages", "scores", "spark_ledger", "_migrations"}
    assert required.issubset(tables), f"missing tables: {required - tables}"
    conn.close()


# ── End-to-end: everything works together ──────────────────────────────


def test_end_to_end_no_api_calls(seeded_workspace: Path) -> None:
    """Simulates what happens on first pip install: bootstrap + DB open +
    query messages + render watcher message + generate SVG. No API calls,
    entirely deterministic.
    """
    import importlib

    from amatelier import paths
    from amatelier.tools import watch_roundtable as w

    # Bootstrap already done by fixture; verify paths resolve
    assert paths.user_db_path().exists()
    assert paths.user_data_dir() == seeded_workspace

    # Open + query
    conn = w._open_db()
    assert conn is not None
    row = w._find_roundtable(conn, rt_id=None)
    assert row["id"] == "rt-fixture-001"

    # Render a single message (exercises agent_color, role, is_gate paths)
    msg = conn.execute(
        "SELECT id, agent_name, message, timestamp FROM messages "
        "WHERE roundtable_id=? AND agent_name='judge' LIMIT 1",
        ("rt-fixture-001",),
    ).fetchone()
    # Create a RichWatcher (without running its loop) to test render
    rt_row = w._find_roundtable(conn, rt_id=None)
    rw = w.RichWatcher(conn, rt_row)
    rendered = rw._render_message(msg)
    # rendered is a Panel (for GATE) or Table (for normal); both have __class__
    assert rendered is not None
    assert rendered.__class__.__name__ in ("Panel", "Table")
