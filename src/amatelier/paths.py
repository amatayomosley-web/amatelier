"""Filesystem path resolution for the Amatayo Standard dual-layer layout.

Amatelier splits state into two layers:

1. **Bundled assets** — read-only, shipped in the wheel. Default config,
   agent persona seeds, skill template catalog, bundled docs. Lives inside
   the installed package (``site-packages/amatelier/``).

2. **User data** — read-write, owned by the user. Database, logs, digests,
   evolving agent MEMORY, spark ledger, sessions. Lives in the
   OS-appropriate user data directory via ``platformdirs``:

   - Linux: ``$XDG_DATA_HOME/amatelier`` (default ``~/.local/share/amatelier/``)
   - macOS: ``~/Library/Application Support/amatelier/``
   - Windows: ``%LOCALAPPDATA%\\amatelier\\``

Override the user-data location with the ``AMATELIER_WORKSPACE`` env var.
This is mainly useful for:

- Clone-based installs that want everything in the working tree
- CI / Docker: point at a scratch directory
- Multiple parallel atelier instances

First-run bootstrap (``ensure_user_data``) is invoked lazily — no writes
happen at import time. It copies agent persona seeds and store catalog
from the bundled layer to user data the first time they are needed.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from platformdirs import user_data_dir as _platform_user_data_dir

APP_NAME = "amatelier"

# Bundled assets live next to this module (the installed package root).
# Resolves to site-packages/amatelier/ after pip install, or
# <repo>/src/amatelier/ for editable installs.
_BUNDLED = Path(__file__).resolve().parent


def bundled_assets_dir() -> Path:
    """The read-only bundled-assets root. Inside the installed package."""
    return _BUNDLED


def bundled_docs_dir() -> Path:
    """The bundled human docs (Diátaxis tree) shipped inside the wheel."""
    return _BUNDLED / "docs"


def bundled_agent_dir(agent_name: str) -> Path:
    """Seed persona directory for an agent (ships in wheel, read-only)."""
    return _BUNDLED / "agents" / agent_name


def bundled_store_catalog() -> Path:
    """Default skill template catalog."""
    return _BUNDLED / "store" / "catalog.json"


def bundled_config() -> Path:
    """Default config.json."""
    return _BUNDLED / "config.json"


def user_data_dir() -> Path:
    """The user-writable root for runtime state.

    Respects ``AMATELIER_WORKSPACE`` if set; otherwise uses platformdirs.
    """
    override = os.environ.get("AMATELIER_WORKSPACE", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(_platform_user_data_dir(APP_NAME, appauthor=False))


def user_agent_dir(agent_name: str) -> Path:
    """Per-agent mutable state (MEMORY, metrics, behaviors, sessions, skills)."""
    return user_data_dir() / "agents" / agent_name


def user_db_path() -> Path:
    """SQLite database for the roundtable chat."""
    return user_data_dir() / "roundtable-server" / "roundtable.db"


def user_logs_dir() -> Path:
    """Runtime logs (gemini_errors, runner logs, etc.)."""
    return user_data_dir() / "roundtable-server" / "logs"


def user_digest_dir() -> Path:
    """Where ``digest-<rt_id>.json`` and related transcripts land."""
    return user_data_dir() / "roundtable-server"


def user_briefing_dir() -> Path:
    """Where user-authored briefing-*.md files are expected."""
    return user_data_dir() / "roundtable-server"


def user_store_ledger() -> Path:
    """Spark economy ledger (evolves as agents earn and spend)."""
    return user_data_dir() / "store" / "ledger.json"


def user_novel_concepts() -> Path:
    """DERIVE skill concepts accumulated across roundtables."""
    return user_data_dir() / "novel_concepts.json"


def user_shared_skills_index() -> Path:
    """Curated shared skills from Admin distillation."""
    return user_data_dir() / "shared-skills" / "index.json"


def user_config_override() -> Path:
    """Optional user-level override for config.json.

    If present, used in place of the bundled defaults.
    """
    return user_data_dir() / "config.json"


# ── Bootstrap ────────────────────────────────────────────────────────────────

_BOOTSTRAP_SENTINEL = ".bootstrap-complete"


def _copy_agent_seed(agent_name: str) -> None:
    """Copy persona seeds (CLAUDE.md, IDENTITY.md) from bundled to user_data
    and create empty state files (MEMORY.md/json, metrics.json, behaviors.json).
    """
    seed = bundled_agent_dir(agent_name)
    if not seed.exists():
        return
    dst = user_agent_dir(agent_name)
    dst.mkdir(parents=True, exist_ok=True)
    for filename in ("CLAUDE.md", "IDENTITY.md"):
        src = seed / filename
        target = dst / filename
        if src.exists() and not target.exists():
            shutil.copy2(src, target)
    (dst / "sessions").mkdir(exist_ok=True)
    (dst / "skills").mkdir(exist_ok=True)
    # Initialize empty state files so engine doesn't need existence checks.
    for fname, default in (
        ("MEMORY.md", ""),
        ("MEMORY.json", "{}"),
        ("metrics.json", "{}"),
        ("behaviors.json", "{}"),
    ):
        p = dst / fname
        if not p.exists():
            p.write_text(default, encoding="utf-8")


def _load_config_for_bootstrap() -> dict:
    user_cfg = user_config_override()
    src = user_cfg if user_cfg.exists() else bundled_config()
    if not src.exists():
        return {}
    try:
        return json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def ensure_user_data(force: bool = False) -> Path:
    """Create the user-data tree on first use.

    Idempotent: running this twice is safe. Uses a ``.bootstrap-complete``
    sentinel file to skip the expensive path on subsequent runs.

    Returns the resolved ``user_data_dir()``.
    """
    root = user_data_dir()
    sentinel = root / _BOOTSTRAP_SENTINEL
    if sentinel.exists() and not force:
        return root

    # Directory scaffolding
    root.mkdir(parents=True, exist_ok=True)
    (root / "roundtable-server").mkdir(exist_ok=True)
    (root / "roundtable-server" / "logs").mkdir(exist_ok=True)
    (root / "agents").mkdir(exist_ok=True)
    (root / "store").mkdir(exist_ok=True)
    (root / "shared-skills").mkdir(exist_ok=True)

    # Seed agents from the bundled layer
    config = _load_config_for_bootstrap()
    agents = set()
    team = config.get("team", {})
    agents.update(team.get("workers", {}).keys())
    for key in ("admin", "judge", "therapist"):
        entry = team.get(key)
        if isinstance(entry, dict):
            name = entry.get("name")
            if name:
                agents.add(_slugify(name))
    # Also pull from filesystem in case config is stale.
    bundled_agents = (_BUNDLED / "agents")
    if bundled_agents.exists():
        for child in bundled_agents.iterdir():
            if child.is_dir():
                agents.add(child.name)
    for a in sorted(agents):
        _copy_agent_seed(a)

    # Initialize empty top-level state files
    _init_json(user_store_ledger(), {})
    _init_json(user_novel_concepts(), [])
    _init_json(user_shared_skills_index(), {"entries": []})

    sentinel.write_text("1", encoding="utf-8")
    return root


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "-")


def _init_json(path: Path, default_value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(default_value), encoding="utf-8")


__all__ = [
    "APP_NAME",
    "bundled_assets_dir",
    "bundled_docs_dir",
    "bundled_agent_dir",
    "bundled_store_catalog",
    "bundled_config",
    "user_data_dir",
    "user_agent_dir",
    "user_db_path",
    "user_logs_dir",
    "user_digest_dir",
    "user_briefing_dir",
    "user_store_ledger",
    "user_novel_concepts",
    "user_shared_skills_index",
    "user_config_override",
    "ensure_user_data",
]
