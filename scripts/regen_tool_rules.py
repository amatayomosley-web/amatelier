"""Regenerate .cursor/rules/<pkg>.mdc and .github/copilot-instructions.md from CLAUDE.md.

Usage:
    python scripts/regen_tool_rules.py [--repo <path>]

CLAUDE.md is the canonical source of tool-facing project rules. Cursor and
Copilot rule files are derived — they share 90% of content but need different
frontmatter and preambles.
"""

import argparse
import pathlib
import sys
import tomllib
import json


def read_pkg_name(repo: pathlib.Path) -> str:
    pyproject = repo / "pyproject.toml"
    package_json = repo / "package.json"
    if pyproject.exists():
        with pyproject.open("rb") as f:
            return tomllib.load(f).get("project", {}).get("name", repo.name)
    if package_json.exists():
        return json.loads(package_json.read_text(encoding="utf-8")).get("name", repo.name)
    return repo.name


def make_cursor_mdc(claude_body: str, pkg: str) -> str:
    frontmatter = (
        "---\n"
        f"description: {pkg} repository rules (Amatayo Standard)\n"
        'globs: ["**/*"]\n'
        "alwaysApply: true\n"
        "---\n\n"
    )
    return frontmatter + claude_body


def make_copilot_md(claude_body: str, pkg: str) -> str:
    preamble = (
        f"# GitHub Copilot Instructions — {pkg}\n\n"
        "_This file is generated from CLAUDE.md. Do not hand-edit._\n\n"
    )
    # Skip the first heading of CLAUDE.md since we replaced it
    stripped = "\n".join(
        line for line in claude_body.splitlines()
        if not line.startswith("# ")
    ).lstrip()
    return preamble + stripped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="Repo root (default: cwd)")
    args = parser.parse_args()

    repo = pathlib.Path(args.repo).resolve()
    claude = repo / "CLAUDE.md"
    if not claude.exists():
        print(f"regen_tool_rules: {claude} not found", file=sys.stderr)
        return 1

    body = claude.read_text(encoding="utf-8")
    pkg = read_pkg_name(repo)

    cursor_dir = repo / ".cursor" / "rules"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    (cursor_dir / f"{pkg}.mdc").write_text(make_cursor_mdc(body, pkg), encoding="utf-8")

    copilot = repo / ".github" / "copilot-instructions.md"
    copilot.parent.mkdir(parents=True, exist_ok=True)
    copilot.write_text(make_copilot_md(body, pkg), encoding="utf-8")

    print("regen_tool_rules: wrote .cursor/rules/{pkg}.mdc and .github/copilot-instructions.md".format(pkg=pkg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
