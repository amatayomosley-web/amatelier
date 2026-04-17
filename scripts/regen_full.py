"""Concatenate llm/*.md into llms-full.txt with section dividers.

Usage:
    python scripts/regen_full.py [--repo <path>]

Order: SPEC → API → SCHEMA → WORKFLOWS → EXAMPLES → <alphabetical domain files>
"""

import argparse
import pathlib
import sys

PRIORITY = ["SPEC.md", "API.md", "SCHEMA.md", "WORKFLOWS.md", "EXAMPLES.md"]


def ordered(files: list[pathlib.Path]) -> list[pathlib.Path]:
    by_name = {f.name: f for f in files}
    result = []
    for name in PRIORITY:
        if name in by_name:
            result.append(by_name.pop(name))
    result.extend(sorted(by_name.values(), key=lambda p: p.name))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="Repo root (default: cwd)")
    args = parser.parse_args()

    repo = pathlib.Path(args.repo).resolve()
    llm_dir = repo / "llm"
    if not llm_dir.exists():
        print(f"regen_full: {llm_dir} not found", file=sys.stderr)
        return 1

    files = ordered(list(llm_dir.glob("*.md")))
    buffers = []
    for f in files:
        buffers.append(f"{'=' * 80}")
        buffers.append(f"FILE: llm/{f.name}")
        buffers.append(f"{'=' * 80}")
        buffers.append("")
        buffers.append(f.read_text(encoding="utf-8").rstrip())
        buffers.append("")

    (repo / "llms-full.txt").write_text("\n".join(buffers) + "\n", encoding="utf-8")
    print(f"regen_full: wrote {len(files)} files to llms-full.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
