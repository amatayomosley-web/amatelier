"""Default model IDs must be ones the API still serves.

claude-sonnet-4-20250514 is no longer served (the API answers "Please migrate
to a newer model"), which broke `sonnet` calls in anthropic-sdk mode and every
Steward escalation to Sonnet. claude-opus-4-20250514 is silently remapped by
the Claude CLI; neither may come back as a default, and a user config copied
from an older release must not keep sending them.
"""

from __future__ import annotations

import inspect
import json
import logging

import pytest

from amatelier import paths
from amatelier.engine import steward_dispatch
from amatelier.llm_backend import (
    CLAUDE_DEFAULT_MAP,
    AnthropicSDKBackend,
    ClaudeCLIBackend,
    get_backend,
)

OLD_IDS = {"claude-sonnet-4-20250514", "claude-opus-4-20250514"}


def test_default_map_uses_current_models():
    assert CLAUDE_DEFAULT_MAP["sonnet"] == "claude-sonnet-5-5"
    assert CLAUDE_DEFAULT_MAP["opus"] == "claude-opus-5-5"
    assert not OLD_IDS & set(CLAUDE_DEFAULT_MAP.values())


def test_bundled_config_uses_current_models():
    cfg = json.loads(paths.bundled_config().read_text(encoding="utf-8"))
    model_map = cfg["llm"]["model_map"]
    assert model_map["sonnet"] == "claude-sonnet-5-5" and model_map["opus"] == "claude-opus-5-5"
    assert cfg["steward"]["sonnet_model"] == "claude-sonnet-5-5"
    workers = {k: v for k, v in cfg["team"]["workers"].items() if isinstance(v, dict)}
    assert not OLD_IDS & {w.get("model") for w in workers.values()}


def test_steward_escalates_to_a_served_sonnet():
    src = inspect.getsource(steward_dispatch.spawn_steward_subagent)
    assert '"sonnet": "claude-sonnet-5-5"' in src
    assert not any(old in src for old in OLD_IDS)


@pytest.fixture
def stale_user_config(tmp_path, monkeypatch):
    """A user config.json copied from a release whose model_map named the retired IDs."""
    cfg = json.loads(paths.bundled_config().read_text(encoding="utf-8"))
    cfg["llm"]["model_map"] = {
        "sonnet": "claude-sonnet-4-20250514",
        "haiku": "claude-haiku-4-5-20251001",
        "opus": "claude-opus-4-20250514",
    }
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("AMATELIER_WORKSPACE", str(tmp_path))
    get_backend.cache_clear()
    yield paths.user_config_override()
    get_backend.cache_clear()


def test_stale_user_config_resolves_to_current_models(stale_user_config, monkeypatch, caplog):
    monkeypatch.setenv("AMATELIER_MODE", "anthropic-sdk")
    with caplog.at_level(logging.WARNING, logger="amatelier.llm_backend"):
        backend = get_backend()
    assert isinstance(backend, AnthropicSDKBackend)
    assert backend._resolve("sonnet") == "claude-sonnet-5-5"
    assert backend._resolve("opus") == "claude-opus-5-5"
    assert backend._resolve("haiku") == "claude-haiku-4-5-20251001"
    warnings = [r.getMessage() for r in caplog.records if "retired" in r.getMessage()]
    assert len(warnings) == 1
    assert str(stale_user_config) in warnings[0]


def test_retired_id_passed_directly_resolves_to_current_model():
    assert ClaudeCLIBackend()._resolve("claude-sonnet-4-20250514") == "sonnet"
    assert ClaudeCLIBackend()._resolve("claude-opus-4-20250514") == "opus"
    assert AnthropicSDKBackend()._resolve("claude-sonnet-4-20250514") == "claude-sonnet-5-5"
    stale = AnthropicSDKBackend(model_map={"sonnet": "claude-sonnet-4-20250514"})
    assert stale._resolve("sonnet") == "claude-sonnet-5-5"
