"""LLM backend abstraction for amatelier.

Three backends, one interface. The engine always calls ``complete()``
with a role hint (``"sonnet"``, ``"haiku"``, ``"opus"``) and the active
backend translates to a concrete model ID.

Modes:

1. ``claude-code`` — shells out to the ``claude`` CLI (legacy behavior)
2. ``anthropic-sdk`` — direct Anthropic API (``ANTHROPIC_API_KEY``)
3. ``openai-compat`` — any OpenAI-compatible endpoint (OpenAI, OpenRouter,
   Groq, Together, local Ollama/vLLM/LM Studio, etc.)

Selection order (unless ``AMATELIER_MODE`` is explicit):

    1. If ``claude`` binary is on ``PATH`` → claude-code
    2. Elif ``ANTHROPIC_API_KEY`` is set → anthropic-sdk
    3. Elif ``OPENAI_API_KEY`` is set → openai-compat (api.openai.com)
    4. Elif ``OPENROUTER_API_KEY`` is set → openai-compat (openrouter.ai)
    5. Else → raise ``BackendUnavailable`` with setup guidance

Explicit override:

    AMATELIER_MODE=claude-code | anthropic-sdk | openai-compat

Model resolution (all backends):

    Engine passes a short role name ("sonnet", "haiku", "opus"). Each
    backend resolves it through a ``model_map`` that can be overridden
    in ``config.json`` → ``llm.model_map`` or per-backend.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from amatelier import paths

logger = logging.getLogger(__name__)


class BackendUnavailable(RuntimeError):
    """Raised when no backend can satisfy the current environment."""


# ── Default role → model mapping ──────────────────────────────────────────────

CLAUDE_DEFAULT_MAP = {
    "sonnet": "claude-sonnet-4-20250514",
    "haiku": "claude-haiku-4-5-20251001",
    "opus": "claude-opus-4-20250514",
}

# For openai-compat users on OpenRouter, the default map routes to Anthropic
# models through OpenRouter's catalog. Users point at any provider by setting
# llm.openai_compat.base_url + model_map in config.json.
OPENROUTER_DEFAULT_MAP = {
    "sonnet": "anthropic/claude-sonnet-4",
    "haiku": "anthropic/claude-haiku-4-5",
    "opus": "anthropic/claude-opus-4",
}

OPENAI_DEFAULT_MAP = {
    "sonnet": "gpt-4o",
    "haiku": "gpt-4o-mini",
    "opus": "gpt-4o",
}


# ── Backend protocol + result type ────────────────────────────────────────────


@dataclass
class Completion:
    text: str
    model: str
    backend: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMBackend(Protocol):
    name: str

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int = 8000,
        timeout: float = 300.0,
        effort: str | None = None,
    ) -> Completion: ...


# Extended-thinking budget per effort level (tokens). None = no thinking block.
EFFORT_BUDGETS: dict[str, int] = {
    "low": 2048,
    "medium": 4096,
    "high": 8192,
    "max": 16000,
}


# ── Claude Code CLI backend ───────────────────────────────────────────────────


@dataclass
class ClaudeCLIBackend:
    name: str = "claude-code"
    model_map: dict[str, str] = field(default_factory=lambda: dict(CLAUDE_DEFAULT_MAP))
    binary: str = "claude"

    @classmethod
    def available(cls) -> bool:
        return shutil.which("claude") is not None

    def _resolve(self, model: str) -> str:
        # CLI expects short names (sonnet/haiku/opus); some call sites pass
        # full IDs, which we accept as-is.
        short = model if model in ("sonnet", "haiku", "opus") else None
        if short:
            return short
        # Map full IDs back to short tiers where possible.
        for tier, full in CLAUDE_DEFAULT_MAP.items():
            if full == model:
                return tier
        return model

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int = 8000,
        timeout: float = 300.0,
        effort: str | None = None,
    ) -> Completion:
        start = time.monotonic()
        resolved = self._resolve(model)
        cmd = [
            self.binary,
            "-p", prompt,
            "--model", resolved,
            "--append-system-prompt", system,
        ]
        if effort in ("low", "medium", "high", "max"):
            cmd.extend(["--effort", effort])
            logger.info("claude-code: --effort=%s", effort)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI failed (exit {result.returncode}): "
                f"{(result.stderr or '')[:500]}"
            )
        return Completion(
            text=result.stdout,
            model=resolved,
            backend=self.name,
            latency_ms=elapsed_ms,
        )


# ── Anthropic SDK backend ─────────────────────────────────────────────────────


@dataclass
class AnthropicSDKBackend:
    name: str = "anthropic-sdk"
    model_map: dict[str, str] = field(default_factory=lambda: dict(CLAUDE_DEFAULT_MAP))
    api_key: str | None = None
    _client: object = field(default=None, repr=False)

    @classmethod
    def available(cls) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise BackendUnavailable(
                "anthropic SDK not installed. Run: pip install anthropic"
            ) from e
        key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise BackendUnavailable(
                "ANTHROPIC_API_KEY not set. "
                "Get a key at https://console.anthropic.com"
            )
        self._client = Anthropic(api_key=key)
        return self._client

    def _resolve(self, model: str) -> str:
        # Accept short names or full IDs.
        if model in self.model_map:
            return self.model_map[model]
        return model

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int = 8000,
        timeout: float = 300.0,
        effort: str | None = None,
    ) -> Completion:
        client = self._get_client()
        resolved = self._resolve(model)
        start = time.monotonic()
        kwargs: dict = {
            "model": resolved,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "timeout": timeout,
        }
        budget = EFFORT_BUDGETS.get(effort or "") if effort else None
        if budget:
            # Anthropic requires max_tokens > budget_tokens; give headroom.
            kwargs["max_tokens"] = max(max_tokens, budget + 4096)
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            logger.info(
                "anthropic-sdk: extended thinking effort=%s budget=%d",
                effort, budget,
            )
        msg = client.messages.create(**kwargs)
        elapsed_ms = (time.monotonic() - start) * 1000
        text = "".join(
            (getattr(block, "text", "") or "")
            for block in getattr(msg, "content", [])
        )
        usage = getattr(msg, "usage", None)
        return Completion(
            text=text,
            model=resolved,
            backend=self.name,
            latency_ms=elapsed_ms,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )

    def complete_with_tools(
        self,
        *,
        system: str,
        user: str,
        tools: list[dict],
        tool_executor,
        model: str = "sonnet",
        max_tokens: int = 4000,
        timeout: float = 180.0,
        max_iterations: int = 10,
    ) -> Completion:
        """Run a tool-use loop: model calls tools, we execute them locally.

        `tool_executor` is a callable `(name: str, input: dict) -> str` that
        executes a tool and returns its text result. Looping continues until
        the model returns a message without tool_use blocks or until
        `max_iterations` is hit.

        Not part of the LLMBackend Protocol — only implemented on Anthropic
        since OpenAI-compat tool schemas differ. Callers must check for
        availability via `hasattr(backend, "complete_with_tools")`.
        """
        client = self._get_client()
        resolved = self._resolve(model)
        start = time.monotonic()
        messages: list[dict] = [{"role": "user", "content": user}]
        final_text = ""
        input_tokens_total = 0
        output_tokens_total = 0

        for _ in range(max_iterations):
            msg = client.messages.create(
                model=resolved,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=tools,
                timeout=timeout,
            )
            usage = getattr(msg, "usage", None)
            if usage:
                input_tokens_total += getattr(usage, "input_tokens", 0) or 0
                output_tokens_total += getattr(usage, "output_tokens", 0) or 0

            blocks = list(getattr(msg, "content", []))
            tool_uses = [b for b in blocks if getattr(b, "type", "") == "tool_use"]
            text_chunks = [
                (getattr(b, "text", "") or "")
                for b in blocks if getattr(b, "type", "") == "text"
            ]
            stop_reason = getattr(msg, "stop_reason", "")

            if not tool_uses:
                final_text = "".join(text_chunks)
                break

            # Record the assistant turn with all its tool_use blocks
            assistant_content = []
            for b in blocks:
                bt = getattr(b, "type", "")
                if bt == "text":
                    assistant_content.append({
                        "type": "text",
                        "text": getattr(b, "text", "") or "",
                    })
                elif bt == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": getattr(b, "id", ""),
                        "name": getattr(b, "name", ""),
                        "input": getattr(b, "input", {}) or {},
                    })
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool and build the tool_result user turn
            tool_results = []
            for tu in tool_uses:
                try:
                    result = tool_executor(
                        getattr(tu, "name", ""),
                        getattr(tu, "input", {}) or {},
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": getattr(tu, "id", ""),
                        "content": str(result),
                    })
                except Exception as e:  # noqa: BLE001
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": getattr(tu, "id", ""),
                        "content": f"Error: {e}",
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})

            if stop_reason != "tool_use":
                final_text = "".join(text_chunks)
                break
        else:
            logger.warning(
                "complete_with_tools: hit max_iterations=%d without final text",
                max_iterations,
            )

        elapsed_ms = (time.monotonic() - start) * 1000
        return Completion(
            text=final_text,
            model=resolved,
            backend=self.name,
            latency_ms=elapsed_ms,
            input_tokens=input_tokens_total or None,
            output_tokens=output_tokens_total or None,
        )


# ── OpenAI-compatible backend ─────────────────────────────────────────────────


@dataclass
class OpenAICompatBackend:
    name: str = "openai-compat"
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    model_map: dict[str, str] = field(default_factory=lambda: dict(OPENAI_DEFAULT_MAP))
    api_key: str | None = None
    _client: object = field(default=None, repr=False)

    @classmethod
    def available(cls) -> bool:
        return any(
            bool(os.environ.get(k, "").strip())
            for k in ("OPENAI_API_KEY", "OPENROUTER_API_KEY")
        )

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as e:
            raise BackendUnavailable(
                "openai SDK not installed. Run: pip install openai"
            ) from e
        key = self.api_key or os.environ.get(self.api_key_env)
        if not key:
            raise BackendUnavailable(
                f"{self.api_key_env} not set. "
                "Configure llm.openai_compat in config.json or set the env var."
            )
        self._client = OpenAI(base_url=self.base_url, api_key=key)
        return self._client

    def _resolve(self, model: str) -> str:
        if model in self.model_map:
            return self.model_map[model]
        return model

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int = 8000,
        timeout: float = 300.0,
        effort: str | None = None,
    ) -> Completion:
        client = self._get_client()
        resolved = self._resolve(model)
        if effort:
            logger.debug(
                "openai-compat backend: effort=%s has no equivalent on this "
                "provider; ignoring", effort,
            )
        start = time.monotonic()
        response = client.chat.completions.create(
            model=resolved,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            timeout=timeout,
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        return Completion(
            text=text,
            model=resolved,
            backend=self.name,
            latency_ms=elapsed_ms,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
        )


# ── Selection logic ───────────────────────────────────────────────────────────


def _load_config() -> dict:
    """Load config (user override if present, else bundled)."""
    user_cfg = paths.user_config_override()
    bundled_cfg = paths.bundled_config()
    src = user_cfg if user_cfg.exists() else bundled_cfg
    if not src.exists():
        return {}
    try:
        return json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _auto_detect() -> str:
    """Return the best available mode based on environment."""
    if ClaudeCLIBackend.available():
        return "claude-code"
    if AnthropicSDKBackend.available():
        return "anthropic-sdk"
    if OpenAICompatBackend.available():
        return "openai-compat"
    return "none"


def describe_environment() -> dict:
    """Diagnostic snapshot — used by ``amatelier config``."""
    return {
        "claude-code": {
            "available": ClaudeCLIBackend.available(),
            "detected_via": "claude binary on PATH",
        },
        "anthropic-sdk": {
            "available": AnthropicSDKBackend.available(),
            "detected_via": "ANTHROPIC_API_KEY env var",
        },
        "openai-compat": {
            "available": OpenAICompatBackend.available(),
            "detected_via": "OPENAI_API_KEY or OPENROUTER_API_KEY env var",
        },
        "active_mode": resolve_mode(),
        "explicit_override": os.environ.get("AMATELIER_MODE", "").strip() or None,
    }


def resolve_mode() -> str:
    """Resolve the mode to use.

    Order: explicit env var → config file → auto-detect.
    """
    explicit = os.environ.get("AMATELIER_MODE", "").strip()
    if explicit:
        return explicit
    cfg = _load_config().get("llm", {})
    configured = str(cfg.get("mode", "auto")).strip()
    if configured and configured != "auto":
        return configured
    return _auto_detect()


@lru_cache(maxsize=1)
def get_backend() -> LLMBackend:
    """Return a singleton backend instance configured for the current env."""
    cfg = _load_config().get("llm", {})
    mode = resolve_mode()

    if mode == "claude-code":
        model_map = cfg.get("model_map", {}) or CLAUDE_DEFAULT_MAP
        return ClaudeCLIBackend(model_map={**CLAUDE_DEFAULT_MAP, **model_map})

    if mode == "anthropic-sdk":
        model_map = cfg.get("model_map", {}) or CLAUDE_DEFAULT_MAP
        return AnthropicSDKBackend(model_map={**CLAUDE_DEFAULT_MAP, **model_map})

    if mode == "openai-compat":
        oc = cfg.get("openai_compat", {})
        # Sensible defaults: prefer OpenRouter if that key is set; else OpenAI.
        if os.environ.get("OPENROUTER_API_KEY", "").strip():
            base_url = oc.get("base_url") or "https://openrouter.ai/api/v1"
            api_key_env = oc.get("api_key_env") or "OPENROUTER_API_KEY"
            default_map = OPENROUTER_DEFAULT_MAP
        else:
            base_url = oc.get("base_url") or "https://api.openai.com/v1"
            api_key_env = oc.get("api_key_env") or "OPENAI_API_KEY"
            default_map = OPENAI_DEFAULT_MAP
        model_map = oc.get("model_map") or default_map
        return OpenAICompatBackend(
            base_url=base_url,
            api_key_env=api_key_env,
            model_map={**default_map, **model_map},
        )

    if mode == "none":
        raise BackendUnavailable(
            "No LLM backend available. Install Claude Code, or set one of:\n"
            "  ANTHROPIC_API_KEY (get one at https://console.anthropic.com)\n"
            "  OPENAI_API_KEY (https://platform.openai.com/api-keys)\n"
            "  OPENROUTER_API_KEY (https://openrouter.ai/keys)\n"
            "Run: amatelier config"
        )

    raise BackendUnavailable(
        f"Unknown mode: {mode}. "
        "Set AMATELIER_MODE to one of: claude-code, anthropic-sdk, openai-compat"
    )


def call_claude(system_prompt: str, prompt: str, agent_name: str, model: str) -> str:
    """Backward-compatible shim matching the original claude_agent.call_claude API.

    Engine code that previously called ``claude_agent.call_claude()`` can
    continue to do so — the function now delegates to ``get_backend()``.
    """
    backend = get_backend()
    result = backend.complete(system=system_prompt, prompt=prompt, model=model)
    logger.info(
        "llm call: agent=%s model=%s backend=%s latency_ms=%d",
        agent_name, result.model, result.backend, int(result.latency_ms),
    )
    return result.text


__all__ = [
    "Completion",
    "LLMBackend",
    "BackendUnavailable",
    "ClaudeCLIBackend",
    "AnthropicSDKBackend",
    "OpenAICompatBackend",
    "get_backend",
    "resolve_mode",
    "describe_environment",
    "call_claude",
]
