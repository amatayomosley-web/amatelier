"""Default model IDs must be ones the API still serves.

claude-sonnet-4-20250514 is no longer served (the API answers "Please migrate
to a newer model"), which broke `sonnet` calls in anthropic-sdk mode and every
Steward escalation to Sonnet. claude-opus-4-20250514 is silently remapped by
the Claude CLI; neither may come back as a default.
"""

from __future__ import annotations

import inspect
import json

from amatelier import paths
from amatelier.engine import steward_dispatch
from amatelier.llm_backend import CLAUDE_DEFAULT_MAP

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
