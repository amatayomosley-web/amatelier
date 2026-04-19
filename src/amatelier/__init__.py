"""Amatelier — a self-evolving multi-model AI team.

Runs in two modes:

1. ``claude-code`` — shells out to the ``claude`` CLI (the way Amatelier
   originally shipped). Auto-selected when the ``claude`` binary is on PATH.
2. ``open`` — bring your own LLM provider. Direct Anthropic, OpenAI,
   OpenRouter, Groq, Together, local Ollama, LM Studio — anything that
   speaks the OpenAI-compatible protocol.

Storage follows the Amatayo Standard dual-layer layout:

- **Bundled assets** (read-only, inside the installed package) —
  default config, agent persona seeds, skill catalog, bundled docs.
- **User data** (read-write, ``platformdirs`` user data dir) — runtime
  database, logs, digests, evolving agent memory, spark ledger.

Override the user-data location with the ``AMATELIER_WORKSPACE`` env var.

Two entry points:

1. Shell CLI (after ``pip install amatelier``):
       amatelier roundtable --topic "..." --briefing path/to/brief.md
       amatelier docs guides/install
       amatelier config

2. Python:
       from amatelier import paths, llm_backend
       backend = llm_backend.get_backend()
"""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.5.0"

# Filesystem anchor — the installed package directory.
AMATELIER_ROOT: Path = Path(__file__).resolve().parent
REPO_ROOT: Path = AMATELIER_ROOT.parent.parent

# Preserve existing flat-import semantics so engine code that does
# ``from db import ...`` or ``from store import ...`` continues to work
# without touching the engine modules.
for _subdir in ("engine", "store"):
    _path = str(AMATELIER_ROOT / _subdir)
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Back-compat alias for engine code that reads bundled assets.
SUITE_ROOT: Path = AMATELIER_ROOT

# Ensure the writable user-data tree exists on first use. Cheap after
# first call (gated by a sentinel file). If this fails — e.g. the user
# explicitly pointed AMATELIER_WORKSPACE at a directory they don't own —
# we swallow the error at import time and let the first real write raise
# the concrete PermissionError.
try:
    from amatelier import paths as _paths
    _paths.ensure_user_data()
except Exception:
    pass

__all__ = [
    "__version__",
    "AMATELIER_ROOT",
    "REPO_ROOT",
    "SUITE_ROOT",
]
