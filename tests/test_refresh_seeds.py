"""Tests for `amatelier refresh-seeds` — the opt-in mechanism that lets
users sync their local agent persona files to whatever shipped in the
currently-installed wheel."""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_temp_seed(tmp_path: Path, agent_name: str, content: str) -> Path:
    """Create a fake bundled agent seed under a temp directory."""
    seed_dir = tmp_path / "amatelier" / "agents" / agent_name
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "CLAUDE.md").write_text(content, encoding="utf-8")
    (seed_dir / "IDENTITY.md").write_text(f"{agent_name} identity", encoding="utf-8")
    return seed_dir


def test_refresh_seeds_skips_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When bundled content == user content, the file should be SKIPped, not refreshed."""
    from amatelier import cli

    monkeypatch.setenv("AMATELIER_WORKSPACE", str(tmp_path / "user"))
    # Point bundled_assets_dir at our test tmp
    bundled = tmp_path / "amatelier"
    monkeypatch.setattr(
        "amatelier.paths.bundled_assets_dir", lambda: bundled
    )

    _write_temp_seed(tmp_path, "judge", "judge rules v1")
    user_dir = tmp_path / "user" / "agents" / "judge"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "CLAUDE.md").write_text("judge rules v1", encoding="utf-8")

    cli._run_refresh_seeds(["--agent", "judge"])
    out = capsys.readouterr().out
    assert "already current" in out


def test_refresh_seeds_preserves_user_edits_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """User-modified files should NOT be overwritten unless --force."""
    from amatelier import cli

    monkeypatch.setenv("AMATELIER_WORKSPACE", str(tmp_path / "user"))
    bundled = tmp_path / "amatelier"
    monkeypatch.setattr("amatelier.paths.bundled_assets_dir", lambda: bundled)

    _write_temp_seed(tmp_path, "judge", "judge rules v2")
    user_dir = tmp_path / "user" / "agents" / "judge"
    user_dir.mkdir(parents=True, exist_ok=True)
    user_file = user_dir / "CLAUDE.md"
    user_file.write_text("my edited judge rules", encoding="utf-8")

    cli._run_refresh_seeds(["--agent", "judge"])
    assert user_file.read_text(encoding="utf-8") == "my edited judge rules"
    out = capsys.readouterr().out
    assert "user-modified" in out


def test_refresh_seeds_force_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--force overwrites user-edited files."""
    from amatelier import cli

    monkeypatch.setenv("AMATELIER_WORKSPACE", str(tmp_path / "user"))
    bundled = tmp_path / "amatelier"
    monkeypatch.setattr("amatelier.paths.bundled_assets_dir", lambda: bundled)

    _write_temp_seed(tmp_path, "judge", "judge rules v2 — new and improved")
    user_dir = tmp_path / "user" / "agents" / "judge"
    user_dir.mkdir(parents=True, exist_ok=True)
    user_file = user_dir / "CLAUDE.md"
    user_file.write_text("my old hack", encoding="utf-8")

    cli._run_refresh_seeds(["--agent", "judge", "--force"])
    assert user_file.read_text(encoding="utf-8") == "judge rules v2 — new and improved"


def test_refresh_seeds_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dry-run reports but doesn't mutate files."""
    from amatelier import cli

    monkeypatch.setenv("AMATELIER_WORKSPACE", str(tmp_path / "user"))
    bundled = tmp_path / "amatelier"
    monkeypatch.setattr("amatelier.paths.bundled_assets_dir", lambda: bundled)

    _write_temp_seed(tmp_path, "judge", "bundled content")
    user_dir = tmp_path / "user" / "agents" / "judge"
    user_dir.mkdir(parents=True, exist_ok=True)
    user_file = user_dir / "CLAUDE.md"
    user_file.write_text("my content", encoding="utf-8")

    cli._run_refresh_seeds(["--agent", "judge", "--force", "--dry-run"])
    assert user_file.read_text(encoding="utf-8") == "my content"


def test_refresh_seeds_never_touches_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command must NEVER touch evolving agent state (MEMORY/metrics/behaviors/sessions)."""
    from amatelier import cli

    monkeypatch.setenv("AMATELIER_WORKSPACE", str(tmp_path / "user"))
    bundled = tmp_path / "amatelier"
    monkeypatch.setattr("amatelier.paths.bundled_assets_dir", lambda: bundled)

    _write_temp_seed(tmp_path, "elena", "elena new rules")
    user_dir = tmp_path / "user" / "agents" / "elena"
    user_dir.mkdir(parents=True, exist_ok=True)
    memory = user_dir / "MEMORY.md"
    metrics = user_dir / "metrics.json"
    memory.write_text("100 roundtables of learnings", encoding="utf-8")
    metrics.write_text('{"sparks": 427}', encoding="utf-8")

    cli._run_refresh_seeds(["--agent", "elena", "--force"])

    assert memory.read_text(encoding="utf-8") == "100 roundtables of learnings"
    assert metrics.read_text(encoding="utf-8") == '{"sparks": 427}'
