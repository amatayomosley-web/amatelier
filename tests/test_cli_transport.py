"""Claude CLI transport: nothing large rides on the command line.

Windows caps a command line at 32,767 characters. The agent definition goes to
the CLI as a file path, the backend's prompt goes on stdin and its system
prompt in a file, and an agent's context is no longer cut at 8,000 characters.
"""

from __future__ import annotations

import json
import logging
import subprocess
import types

import pytest

from amatelier.engine import claude_agent
from amatelier.llm_backend import ClaudeCLIBackend


class _FakeProc:
    """Stands in for subprocess.Popen: records the command and the stdin input."""

    calls: list[dict] = []

    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = 4242
        self.returncode = 0

    def communicate(self, input=None, timeout=None):
        _FakeProc.calls.append({"cmd": self.cmd, "input": input, "timeout": timeout})
        return "ok", ""


@pytest.fixture
def cli_path(monkeypatch, tmp_path):
    """Route call_claude to its CLI path with a fake Popen and a temporary user-data root."""
    _FakeProc.calls = []
    monkeypatch.setattr(claude_agent, "WRITE_ROOT", tmp_path)
    monkeypatch.setattr(claude_agent.subprocess, "Popen", _FakeProc)
    import amatelier.llm_backend as lb
    monkeypatch.setattr(lb, "get_backend", lambda: types.SimpleNamespace(name="claude-code"))
    return tmp_path


def _config(monkeypatch, **roundtable):
    monkeypatch.setattr(claude_agent, "_load_config", lambda: {"roundtable": roundtable})


def test_agent_definition_travels_as_a_file(cli_path, monkeypatch):
    _config(monkeypatch)  # code defaults: context_limit 60000, cli_timeout_seconds 600
    system = "S" * 44_990 + " END-MARKER"
    assert claude_agent.call_claude(system, "hello", "elena", "sonnet") == "ok"
    call = _FakeProc.calls[-1]
    cmd = call["cmd"]
    defs_arg = cmd[cmd.index("--agents") + 1]
    assert defs_arg == str(cli_path / "agent-defs" / "elena.json")
    body = json.loads((cli_path / "agent-defs" / "elena.json").read_text(encoding="utf-8"))
    assert body["elena"]["prompt"] == system  # whole, not cut at 8,000
    assert len(" ".join(cmd)) < 2000
    assert call["input"] == "hello"
    assert call["timeout"] == 600


def test_context_over_the_limit_is_cut_and_logged(cli_path, monkeypatch, caplog):
    _config(monkeypatch, context_limit=100, cli_timeout_seconds=42)
    with caplog.at_level(logging.WARNING):
        claude_agent.call_claude("x" * 250, "hi", "marcus", "sonnet")
    body = json.loads((cli_path / "agent-defs" / "marcus.json").read_text(encoding="utf-8"))
    assert len(body["marcus"]["prompt"]) == 100
    assert "cut from 250 to 100" in caplog.text
    assert _FakeProc.calls[-1]["timeout"] == 42


def test_backend_prompt_on_stdin_and_system_in_a_file(monkeypatch):
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["input"] = kwargs.get("input")
        i = cmd.index("--append-system-prompt-file")
        with open(cmd[i + 1], encoding="utf-8") as fh:
            seen["system"] = fh.read()
        return subprocess.CompletedProcess(cmd, 0, stdout="answer", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    prompt = "P" * 40_000
    system = "SYSTEM " * 5_000
    out = ClaudeCLIBackend().complete(system=system, prompt=prompt, model="sonnet")
    assert out.text == "answer"
    assert seen["input"] == prompt
    assert prompt not in seen["cmd"] and "--append-system-prompt" not in seen["cmd"]
    assert seen["system"] == system
    assert len(" ".join(seen["cmd"])) < 2000


def test_backend_without_system_prompt_passes_no_file(monkeypatch):
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="x", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ClaudeCLIBackend().complete(system="", prompt="hi", model="haiku")
    assert "--append-system-prompt-file" not in seen["cmd"]
