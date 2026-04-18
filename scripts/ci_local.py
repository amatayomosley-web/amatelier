"""Run the same checks the GitHub workflows run, locally.

Cross-platform — works on Windows (no `make` required), macOS, Linux.
Burns zero GitHub Actions minutes. Run this before pushing.

Usage:
    python scripts/ci_local.py
    python scripts/ci_local.py --skip-build   # skip wheel build (faster)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run(label: str, cmd: list[str], *, cwd: Path = REPO) -> bool:
    print(f"\n=== {label} ===")
    print(f"$ {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=cwd, check=False)
    except FileNotFoundError as e:
        print(f"  [--] command not found: {e}")
        return False
    if result.returncode != 0:
        print(f"  [--] exit {result.returncode}")
        return False
    print("  [OK]")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-build", action="store_true",
                    help="Skip wheel build step (faster, for iterative checks)")
    args = ap.parse_args()

    py = sys.executable
    checks: list[tuple[str, list[str]]] = [
        ("ruff (ci.yml)", [py, "-m", "ruff", "check", "src", "tests"]),
        ("pytest smoke (ci.yml)",
         [py, "-m", "pytest", "tests/test_smoke.py", "-q"]),
        ("mkdocs build (docs.yml)", [py, "-m", "mkdocs", "build", "--quiet"]),
    ]

    if not args.skip_build:
        dist = REPO / "dist"
        if dist.exists():
            shutil.rmtree(dist)
        checks.append(
            ("wheel build (wheel-smoke.yml)", [py, "-m", "build"]),
        )
    checks.append(
        ("pytest integration (wheel-smoke.yml)",
         [py, "-m", "pytest", "tests/test_db_integration.py", "-q"]),
    )

    failures = [label for label, cmd in checks if not run(label, cmd)]

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All local CI checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
