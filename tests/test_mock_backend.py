"""Integration tests for the MockBackend class (v0.4.0).

These tests exercise the mock backend wired via ``AMATELIER_MODE=mock`` so
engine paths can run without API keys or network traffic. Requested by
Marcus (Open-mode RT d29eab18f423) and Gemini's code review (2026-04-18).
"""

from __future__ import annotations

import json
import os

import pytest

from amatelier import worker_registry
from amatelier.llm_backend import (
    Completion,
    MockBackend,
    get_backend,
    resolve_mode,
)


@pytest.fixture(autouse=True)
def clean_backend_cache():
    """Clear the ``get_backend`` lru_cache around each test.

    Tests manipulate ``AMATELIER_MODE`` — the cache must be reset so a
    previous mode doesn't leak into the next test.
    """
    get_backend.cache_clear()
    yield
    get_backend.cache_clear()


# ── 1. Mode resolution ──────────────────────────────────────────────────────


def test_mock_backend_activates_via_env(monkeypatch):
    monkeypatch.setenv("AMATELIER_MODE", "mock")
    get_backend.cache_clear()
    assert resolve_mode() == "mock"
    backend = get_backend()
    assert isinstance(backend, MockBackend)
    assert backend.name == "mock"


# ── 2. Basic completion ─────────────────────────────────────────────────────


def test_mock_backend_completes():
    backend = MockBackend()
    result = backend.complete(system="", prompt="hi", model="sonnet")
    assert isinstance(result, Completion)
    assert result.text  # non-empty
    assert result.backend == "mock"
    assert "sonnet" in result.model


# ── 3. JSON mode ────────────────────────────────────────────────────────────


def test_mock_backend_json_mode_returns_valid_json():
    backend = MockBackend()
    result = backend.complete(
        system="", prompt="give me json", model="sonnet", json_mode=True,
    )
    parsed = json.loads(result.text)  # does not raise
    assert parsed["status"] == "mock"


# ── 4. Tool-use dispatches through executor ─────────────────────────────────


def test_mock_backend_with_tools_dispatches():
    backend = MockBackend()
    calls: list[tuple[str, dict]] = []

    def executor(name, input_dict):
        calls.append((name, input_dict))
        return f"mock-{name}"

    tools = [{"name": "read_file", "input_schema": {}}]
    result = backend.complete_with_tools(
        system="",
        user="read the file",
        tools=tools,
        tool_executor=executor,
    )
    assert calls, "executor should have been called"
    assert calls[0][0] == "read_file"
    assert "read_file" in result.text


# ── 5. Tool loop caps at 3 tools ────────────────────────────────────────────


def test_mock_backend_tool_loop_caps_tools():
    backend = MockBackend()
    calls: list[str] = []

    def executor(name, input_dict):
        calls.append(name)
        return "ok"

    tools = [
        {"name": "t1", "input_schema": {}},
        {"name": "t2", "input_schema": {}},
        {"name": "t3", "input_schema": {}},
        {"name": "t4", "input_schema": {}},
        {"name": "t5", "input_schema": {}},
    ]
    backend.complete_with_tools(
        system="", user="u", tools=tools, tool_executor=executor,
    )
    assert len(calls) == 3, f"Expected 3 tool calls, got {len(calls)}: {calls}"
    assert calls == ["t1", "t2", "t3"]


# ── 6. Worker registry reads config ─────────────────────────────────────────


def test_worker_registry_reads_config():
    workers = worker_registry.list_workers()
    assert set(workers) == {"clare", "elena", "marcus", "naomi", "simon"}
    assert worker_registry.get_worker_backend("naomi") == "gemini"
    assert worker_registry.get_worker_backend("elena") == "claude"


# ── 7. Backend default falls back to claude ─────────────────────────────────


def test_worker_registry_backend_defaults_to_claude():
    assert worker_registry.get_worker_backend("nonexistent-worker") == "claude"


# ── 8. Missing workers returns empty list ───────────────────────────────────


def test_worker_registry_handles_missing_workers(monkeypatch):
    monkeypatch.setattr(
        worker_registry, "_load_config", lambda: {"team": {"workers": {}}},
    )
    assert worker_registry.list_workers() == []


# ── 9. judge_scorer._call_sonnet delegates to mock backend ─────────────────


def test_engine_judge_scorer_uses_backend_when_mock_active(monkeypatch):
    monkeypatch.setenv("AMATELIER_MODE", "mock")
    get_backend.cache_clear()

    # Block any real subprocess so a CLI fallback cannot run.
    def _no_subprocess(*args, **kwargs):
        raise AssertionError(
            "subprocess.run should not be called when mock backend is active",
        )

    monkeypatch.setattr(
        "amatelier.engine.judge_scorer.subprocess.run", _no_subprocess,
    )

    from amatelier.engine import judge_scorer

    result = judge_scorer._call_sonnet("dummy prompt")
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0


# ── 10. Steward tool-use dispatch via mock ──────────────────────────────────


def test_steward_tool_use_dispatches_in_anthropic_mode_via_mock(monkeypatch):
    """MockBackend exposes complete_with_tools, so get_backend() in mock
    mode is a drop-in for the Steward's tool-use path.

    Scope narrowed from the full steward_dispatch integration (which gates
    on ``backend.name == "anthropic-sdk"``) to verifying the backend shape:
    under mock mode, ``get_backend()`` returns an object with a working
    ``complete_with_tools`` method that dispatches to the provided executor.
    """
    monkeypatch.setenv("AMATELIER_MODE", "mock")
    get_backend.cache_clear()

    backend = get_backend()
    assert backend.name == "mock"
    assert hasattr(backend, "complete_with_tools")

    calls: list[str] = []

    def executor(name, input_dict):
        calls.append(name)
        return f"executed-{name}"

    tools = [
        {"name": "read_file", "input_schema": {}},
        {"name": "list_files", "input_schema": {}},
    ]
    result = backend.complete_with_tools(
        system="steward",
        user="find the file",
        tools=tools,
        tool_executor=executor,
        model="haiku",
    )
    assert calls == ["read_file", "list_files"]
    assert result.backend == "mock"
    assert result.text
