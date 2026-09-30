"""Every claude CLI call runs isolated from the user's own Claude Code setup.

Without isolation a call runs the user's hooks and loads every CLAUDE.md above
its working folder into the agent's context. The options are
``--setting-sources local`` plus ``--settings {"disableAllHooks": true}``.
"""

from __future__ import annotations

import re
import subprocess
import types
from pathlib import Path

import pytest

import amatelier.llm_backend as lb
from amatelier.llm_backend import (
    CLAUDE_CLI_ISOLATION_ARGS,
    ClaudeCLIBackend,
    claude_cli_isolation_args,
)

SRC = Path(lb.__file__).resolve().parent


def _has_isolation(cmd: list[str]) -> bool:
    n = len(CLAUDE_CLI_ISOLATION_ARGS)
    return any(cmd[i:i + n] == CLAUDE_CLI_ISOLATION_ARGS for i in range(len(cmd) - n + 1))


def test_isolation_on_by_default(monkeypatch):
    monkeypatch.setattr(lb, "_load_config", lambda: {"llm": {}})
    assert claude_cli_isolation_args() == CLAUDE_CLI_ISOLATION_ARGS
    assert CLAUDE_CLI_ISOLATION_ARGS == ["--setting-sources", "local", "--settings", '{"disableAllHooks": true}']


def test_isolation_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(lb, "_load_config", lambda: {"llm": {"claude_cli_isolation": False}})
    assert claude_cli_isolation_args() == []


def test_backend_call_is_isolated(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(lb, "_load_config", lambda: {})
    monkeypatch.setattr(subprocess, "run", fake_run)
    ClaudeCLIBackend().complete(system="s", prompt="p", model="sonnet")
    assert _has_isolation(seen["cmd"])


def test_worker_call_is_isolated(monkeypatch, tmp_path):
    from amatelier.engine import claude_agent

    seen = {}

    class FakeProc:
        pid = 1
        returncode = 0

        def __init__(self, cmd, **kwargs):
            seen["cmd"] = cmd

        def communicate(self, input=None, timeout=None):
            return "ok", ""

    monkeypatch.setattr(lb, "_load_config", lambda: {})
    monkeypatch.setattr(lb, "get_backend", lambda: types.SimpleNamespace(name="claude-code"))
    monkeypatch.setattr(claude_agent, "WRITE_ROOT", tmp_path)
    monkeypatch.setattr(claude_agent, "_load_config", lambda: {"roundtable": {}})
    monkeypatch.setattr(claude_agent.subprocess, "Popen", FakeProc)
    claude_agent.call_claude("system", "prompt", "elena", "sonnet")
    assert _has_isolation(seen["cmd"])


@pytest.mark.parametrize("module_name, call", [
    ("judge_scorer", lambda m: m._call_sonnet("prompt")),
    ("therapist", lambda m: m._call_llm("prompt", "sonnet")),
])
def test_scorer_and_therapist_calls_are_isolated(monkeypatch, module_name, call):
    import importlib

    mod = importlib.import_module(f"amatelier.engine.{module_name}")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout='{"result": "ok"}', stderr="")

    monkeypatch.setattr(lb, "_load_config", lambda: {})
    monkeypatch.setattr(lb, "get_backend", lambda: types.SimpleNamespace(name="claude-code"))
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    call(mod)
    assert _has_isolation(seen["cmd"])


def test_every_claude_command_list_in_the_package_is_isolated():
    """Guard: a new `["claude", "-p", ...]` call site must carry the isolation options."""
    missing = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'\[\s*"claude",\s*"-p"', text):
            window = text[m.start(): m.start() + 400]
            if "claude_cli_isolation_args()" not in window:
                missing.append(f"{path.name}:{text[:m.start()].count(chr(10)) + 1}")
        for m in re.finditer(r'cmd\s*=\s*\[\s*\n\s*"claude",', text):
            window = text[m.start(): m.start() + 600]
            if "claude_cli_isolation_args()" not in window:
                missing.append(f"{path.name}:{text[:m.start()].count(chr(10)) + 1}")
    assert not missing, f"claude CLI calls without isolation: {missing}"
