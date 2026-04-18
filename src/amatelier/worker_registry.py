"""Worker registry — config-driven access to the current agent roster.

Single source of truth for which workers exist, what models they use, and
which backend spawns them. All engine code that previously hardcoded worker
names (elena/marcus/clare/simon/naomi) should call these helpers instead.

Design:
- No in-memory cache — config.json is tiny; re-read per call keeps things
  simple and lets CLI changes (e.g. `amatelier team new`) take effect
  without a process restart
- Graceful on missing config: returns [] or empty dict rather than crashing
- Sensible defaults: missing `backend` field resolves to "claude"; missing
  `model` resolves to "sonnet"
- Respects user override: `paths.user_config_override()` (at
  user_data_dir/config.json) takes precedence over bundled config

Config schema expected under `team.workers`:

    {
      "<worker-name>": {
        "model": "sonnet" | "haiku" | "opus" | any provider model ID,
        "backend": "claude" | "gemini" | "openai-compat"  (default "claude"),
        "role": "free-form description"                    (optional),
        "assignments": 0                                    (runtime counter)
      }
    }

Added in v0.4.0 to support arbitrary rosters. Backwards-compatible: configs
missing `backend` or `role` still load (defaults applied).
"""

from __future__ import annotations

import json

from amatelier import paths

# ── Config loading ─────────────────────────────────────────────────────────


def _load_config() -> dict:
    """Read config.json (user override if present, else bundled)."""
    user_cfg = paths.user_config_override()
    bundled_cfg = paths.bundled_config()
    src = user_cfg if user_cfg.exists() else bundled_cfg
    if not src.exists():
        return {}
    try:
        return json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _workers_dict() -> dict:
    """Return the raw `team.workers` dict (empty if missing or malformed)."""
    cfg = _load_config()
    workers = cfg.get("team", {}).get("workers", {})
    if not isinstance(workers, dict):
        return {}
    return workers


# ── Public helpers ─────────────────────────────────────────────────────────


def list_workers() -> list[str]:
    """Sorted list of configured worker names.

    Excludes admin-side roles (admin/judge/therapist). Comment keys starting
    with `_` and non-dict values are filtered. Empty list if no workers —
    callers must handle the empty-roster case (framework use).
    """
    return sorted(
        name
        for name, conf in _workers_dict().items()
        if not name.startswith("_") and isinstance(conf, dict)
    )


def get_worker_config(name: str) -> dict:
    """Full config dict for a worker. Empty dict if not found."""
    worker = _workers_dict().get(name, {})
    if not isinstance(worker, dict):
        return {}
    return worker


def get_worker_model(name: str, default: str = "sonnet") -> str:
    """Model alias or full ID for a worker.

    Returns the `model` field from config.team.workers.<name>. Common
    values: `"sonnet"`, `"haiku"`, `"opus"`, or a full provider model
    identifier. Default: `"sonnet"`.
    """
    return str(get_worker_config(name).get("model", default))


def get_worker_backend(name: str, default: str = "claude") -> str:
    """Backend for a worker: `"claude"`, `"gemini"`, or `"openai-compat"`.

    Default: `"claude"`. The roundtable runner uses this to decide which
    spawn helper to call (`_launch_claude` vs `_launch_gemini` vs other).
    Added in v0.4.0; configs missing this field default to `"claude"` so
    v0.3.x configs continue to work.
    """
    return str(get_worker_config(name).get("backend", default))


def get_worker_role(name: str, default: str = "") -> str:
    """Free-form role description. Empty string if not set."""
    return str(get_worker_config(name).get("role", default))


def list_workers_by_backend(backend: str) -> list[str]:
    """All workers whose backend matches the given string."""
    return [n for n in list_workers() if get_worker_backend(n) == backend]


def worker_exists(name: str) -> bool:
    """True if this name is in the configured roster."""
    return name in _workers_dict() and isinstance(
        _workers_dict().get(name), dict
    ) and not name.startswith("_")


# ── Inverse helpers (model/backend → worker list) ──────────────────────────


def workers_using_model(model: str) -> list[str]:
    """All workers whose model alias matches."""
    return [n for n in list_workers() if get_worker_model(n) == model]


# ── Diagnostic ─────────────────────────────────────────────────────────────


def describe_roster() -> dict:
    """Machine-readable snapshot of the current roster. Used by CLI list."""
    return {
        "workers": [
            {
                "name": name,
                "model": get_worker_model(name),
                "backend": get_worker_backend(name),
                "role": get_worker_role(name),
            }
            for name in list_workers()
        ],
        "count": len(list_workers()),
        "backends": {
            b: list_workers_by_backend(b)
            for b in ("claude", "gemini", "openai-compat")
        },
    }


__all__ = [
    "list_workers",
    "get_worker_config",
    "get_worker_model",
    "get_worker_backend",
    "get_worker_role",
    "list_workers_by_backend",
    "workers_using_model",
    "worker_exists",
    "describe_roster",
]
