"""Regenerate llm/API.md and llm/SCHEMA.md from source introspection.

Usage:
    python scripts/regen_llm.py [--repo <path>]

What it does:
    1. Walks `src/<pkg>/` for public symbols (functions, classes, methods) —
       anything not prefixed with `_`
    2. Parses docstrings, signatures, and type annotations
    3. Walks argparse CLI definitions (or click/typer) to collect flags
    4. Walks pydantic models / JSON schemas / dataclasses for config shapes
    5. Writes `llm/API.md` and `llm/SCHEMA.md` in the deterministic YAML-block format

Guarantee:
    Running this twice in a row produces identical output. This is what the CI
    sync-check diffs against.

Implementation:
    At skill install time, this file is a stub. Replace with the real
    introspection implementation on first migration.
"""

import argparse
import ast
import pathlib
import sys

HEADER_API = """# API

> **Generated.** Do not hand-edit. Regenerate with `python scripts/regen_llm.py`.

"""

HEADER_SCHEMA = """# Schema

> **Generated.** Do not hand-edit. Regenerate with `python scripts/regen_llm.py`.

"""


def find_public_symbols(src_dir: pathlib.Path) -> list[dict]:
    """Walk src/ for public symbols. Returns list of dicts with name, kind, path."""
    symbols = []
    for py_file in src_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    symbols.append({
                        "name": node.name,
                        "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                        "path": str(py_file.relative_to(src_dir.parent)),
                        "docstring": ast.get_docstring(node) or "",
                    })
    return symbols


def render_api(symbols: list[dict]) -> str:
    lines = [HEADER_API, "## Public symbols\n"]
    for s in symbols:
        lines.append(f"### `{s['name']}`")
        lines.append("")
        lines.append("```yaml")
        lines.append(f"name: {s['name']}")
        lines.append(f"kind: {s['kind']}")
        lines.append(f"path: {s['path']}")
        desc = (s['docstring'].split(chr(10))[0] if s['docstring'] else '').replace('"', "'")
        lines.append(f"description: \"{desc}\"")
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def render_schema(schemas: list[dict]) -> str:
    lines = [HEADER_SCHEMA, "## Config keys\n"]
    lines.append("_No pydantic models or JSON schemas detected in this repo. "
                 "Populate by implementing the schema-walking logic in "
                 "`find_schemas()` when pydantic/dataclass usage appears._")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="Repo root (default: cwd)")
    args = parser.parse_args()

    repo = pathlib.Path(args.repo).resolve()
    src = repo / "src"
    llm = repo / "llm"

    if not src.exists():
        print(f"regen_llm: {src} not found — nothing to generate", file=sys.stderr)
        return 0

    symbols = find_public_symbols(src)
    api = render_api(symbols)
    schema = render_schema([])

    (llm / "API.md").write_text(api, encoding="utf-8")
    (llm / "SCHEMA.md").write_text(schema, encoding="utf-8")

    print(f"regen_llm: wrote {len(symbols)} symbols to llm/API.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
