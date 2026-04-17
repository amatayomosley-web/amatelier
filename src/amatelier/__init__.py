"""Amatelier — a self-evolving multi-model AI team skill for Claude Code.

This package preserves the original flat-import structure of amatelier for
backward compatibility while conforming to the Amatayo Standard `src/<pkg>/`
layout.

On import, `amatelier/engine/` and `amatelier/store/` are added to sys.path so
existing bare imports (``from db import ...``, ``from store import ...``,
``from distiller import ...``) continue to resolve without refactoring.

Consumers of the package have two entry points:

1. Shell CLI (after ``pip install amatelier``):
       amatelier roundtable --topic "..." --briefing roundtable-server/briefing-001.md

2. Python:
       from amatelier import AMATELIER_ROOT, REPO_ROOT
"""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.1.0"

# Filesystem anchors. AMATELIER_ROOT is the package dir (src/amatelier/).
# REPO_ROOT is the repository root (parent of src/).
AMATELIER_ROOT: Path = Path(__file__).resolve().parent
REPO_ROOT: Path = AMATELIER_ROOT.parent.parent

# Preserve existing flat-import semantics. Before the Amatayo Standard
# restructure, engine/, store/, etc. lived at the repo root and agents
# wrote `from db import get_active_roundtable`. We keep that working by
# adding those directories to sys.path at package import time.
for _subdir in ("engine", "store"):
    _path = str(AMATELIER_ROOT / _subdir)
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Back-compat alias. Engine code references SUITE_ROOT as
# Path(__file__).resolve().parent.parent from inside engine/ — which now
# yields AMATELIER_ROOT (src/amatelier/). That is correct: roundtable-server/,
# store/, tools/ all live inside AMATELIER_ROOT.
SUITE_ROOT: Path = AMATELIER_ROOT

__all__ = ["__version__", "AMATELIER_ROOT", "REPO_ROOT", "SUITE_ROOT"]
