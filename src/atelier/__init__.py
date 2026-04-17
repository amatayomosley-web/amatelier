"""Atelier — a self-evolving multi-model AI team skill for Claude Code.

This package preserves the original flat-import structure of atelier for
backward compatibility while conforming to the Amatayo Standard `src/<pkg>/`
layout.

On import, `atelier/engine/` and `atelier/store/` are added to sys.path so
existing bare imports (``from db import ...``, ``from store import ...``,
``from distiller import ...``) continue to resolve without refactoring.

Consumers of the package have two entry points:

1. Shell CLI (after ``pip install atelier``):
       atelier roundtable --topic "..." --briefing roundtable-server/briefing-001.md

2. Python:
       from atelier import ATELIER_ROOT, REPO_ROOT
"""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.1.0"

# Filesystem anchors. ATELIER_ROOT is the package dir (src/atelier/).
# REPO_ROOT is the repository root (parent of src/).
ATELIER_ROOT: Path = Path(__file__).resolve().parent
REPO_ROOT: Path = ATELIER_ROOT.parent.parent

# Preserve existing flat-import semantics. Before the Amatayo Standard
# restructure, engine/, store/, etc. lived at the repo root and agents
# wrote `from db import get_active_roundtable`. We keep that working by
# adding those directories to sys.path at package import time.
for _subdir in ("engine", "store"):
    _path = str(ATELIER_ROOT / _subdir)
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Back-compat alias. Engine code references SUITE_ROOT as
# Path(__file__).resolve().parent.parent from inside engine/ — which now
# yields ATELIER_ROOT (src/atelier/). That is correct: roundtable-server/,
# store/, tools/ all live inside ATELIER_ROOT.
SUITE_ROOT: Path = ATELIER_ROOT

__all__ = ["__version__", "ATELIER_ROOT", "REPO_ROOT", "SUITE_ROOT"]
