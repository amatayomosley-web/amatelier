"""Pytest-compatible smoke test that exercises the new Amatayo Standard
infrastructure (paths, llm_backend, cli) without touching live APIs.

The legacy tests/test_integration.py is a standalone script, not a pytest
suite — pytest auto-discovers this file for CI coverage instead.
"""

from __future__ import annotations

import json

import pytest


def test_package_imports() -> None:
    import amatelier

    assert amatelier.__version__ == "0.2.0"
    assert amatelier.AMATELIER_ROOT.exists()
    assert amatelier.REPO_ROOT.exists()


def test_paths_module() -> None:
    from amatelier import paths

    bundled = paths.bundled_assets_dir()
    assert bundled.exists()
    assert (bundled / "config.json").exists()

    # user_data_dir may or may not exist pre-bootstrap; ensure_user_data must
    # make it exist.
    paths.ensure_user_data()
    udir = paths.user_data_dir()
    assert udir.exists()
    assert (udir / ".bootstrap-complete").exists()
    assert (udir / "roundtable-server" / "logs").exists()
    assert (udir / "agents").exists()


def test_bundled_docs_present() -> None:
    from amatelier import paths

    docs_dir = paths.bundled_docs_dir()
    assert docs_dir.exists(), f"bundled docs missing at {docs_dir}"
    assert (docs_dir / "index.md").exists()
    assert (docs_dir / "guides" / "install.md").exists()
    assert (docs_dir / "tutorials" / "first-run.md").exists()


def test_config_json_schema() -> None:
    from amatelier import paths

    data = json.loads(paths.bundled_config().read_text(encoding="utf-8"))
    assert data["version"] == "0.2.0"
    assert "llm" in data
    assert data["llm"]["mode"] in ("auto", "claude-code", "anthropic-sdk", "openai-compat")
    assert set(data["team"]["workers"].keys()) == {"elena", "marcus", "clare", "simon", "naomi"}


def test_llm_backend_describe() -> None:
    from amatelier import llm_backend

    env = llm_backend.describe_environment()
    assert set(env.keys()) >= {"claude-code", "anthropic-sdk", "openai-compat", "active_mode"}
    for mode in ("claude-code", "anthropic-sdk", "openai-compat"):
        assert "available" in env[mode]
        assert "detected_via" in env[mode]


def test_llm_backend_resolve_mode_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from amatelier import llm_backend

    monkeypatch.setenv("AMATELIER_MODE", "openai-compat")
    # get_backend is cached; clear before re-resolving.
    llm_backend.get_backend.cache_clear()
    assert llm_backend.resolve_mode() == "openai-compat"


def test_llm_backend_auto_detect_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """With all credentials removed and no claude CLI, mode should be 'none'."""
    from amatelier import llm_backend

    monkeypatch.delenv("AMATELIER_MODE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        "amatelier.llm_backend.ClaudeCLIBackend.available", classmethod(lambda cls: False)
    )
    llm_backend.get_backend.cache_clear()
    assert llm_backend.resolve_mode() == "none"


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    from amatelier.cli import main

    exit_code = main(["--version"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "0.2.0" in captured.out


def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    from amatelier.cli import main

    exit_code = main(["--help"])
    assert exit_code == 2  # argparse-style usage exit
    captured = capsys.readouterr()
    assert "roundtable" in captured.err
    assert "docs" in captured.err
    assert "config" in captured.err


def test_cli_unknown_command(capsys: pytest.CaptureFixture[str]) -> None:
    from amatelier.cli import main

    exit_code = main(["nonexistent-cmd"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "unknown command" in captured.err


def test_cli_docs_lists_topics(capsys: pytest.CaptureFixture[str]) -> None:
    from amatelier.cli import main

    exit_code = main(["docs"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "tutorials/" in captured.out
    assert "guides/" in captured.out
    assert "reference/" in captured.out


def test_cli_docs_specific_topic(capsys: pytest.CaptureFixture[str]) -> None:
    from amatelier.cli import main

    exit_code = main(["docs", "guides/install"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Install" in captured.out


def test_cli_config_json_shape() -> None:
    import io
    import json as _json
    from contextlib import redirect_stdout

    from amatelier.cli import main

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["config", "--json"])
    data = _json.loads(buf.getvalue())
    assert "version" in data
    assert "llm" in data
    assert "paths" in data
    assert "bundled_assets_dir" in data["paths"]
    assert "user_data_dir" in data["paths"]
