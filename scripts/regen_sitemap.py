"""Regenerate llms.txt from the current set of llm/*.md files.

Usage:
    python scripts/regen_sitemap.py [--repo <path>]

Reads repo metadata from pyproject.toml (or package.json) + llm/SPEC.md
to populate the header.
"""

import argparse
import pathlib
import sys
import tomllib
import json


def read_meta(repo: pathlib.Path) -> dict:
    pyproject = repo / "pyproject.toml"
    package_json = repo / "package.json"
    if pyproject.exists():
        with pyproject.open("rb") as f:
            data = tomllib.load(f)
        proj = data.get("project", {})
        url = proj.get("urls", {}).get("Homepage", "")
        return {
            "name": proj.get("name", repo.name),
            "description": proj.get("description", ""),
            "repo_url": url,
        }
    if package_json.exists():
        data = json.loads(package_json.read_text(encoding="utf-8"))
        return {
            "name": data.get("name", repo.name),
            "description": data.get("description", ""),
            "repo_url": data.get("homepage", ""),
        }
    return {"name": repo.name, "description": "", "repo_url": ""}


def find_author_and_pkg(repo_url: str, fallback: str) -> tuple[str, str]:
    # Expect github.com/<author>/<pkg>
    if "github.com" in repo_url:
        parts = repo_url.rstrip("/").split("/")
        if len(parts) >= 2:
            return parts[-2], parts[-1]
    return "UNKNOWN", fallback


def render(meta: dict, llm_files: list[pathlib.Path]) -> str:
    author, pkg = find_author_and_pkg(meta["repo_url"], meta["name"])
    lines = [
        f"# {meta['name']}",
        "",
        f"> {meta['description']}",
        "",
        "## Canonical sources",
        "",
    ]
    for f in sorted(llm_files):
        stem = f.stem
        raw_url = f"https://raw.githubusercontent.com/{author}/{pkg}/main/llm/{f.name}"
        lines.append(f"- [{stem}]({raw_url})")
    lines.extend([
        "",
        "## Full context (one-shot load)",
        "",
        f"- [llms-full.txt](https://raw.githubusercontent.com/{author}/{pkg}/main/llms-full.txt)",
        "",
        "## Tool-specific instructions",
        "",
        f"- [CLAUDE.md](https://raw.githubusercontent.com/{author}/{pkg}/main/CLAUDE.md)",
        f"- [AGENTS.md](https://raw.githubusercontent.com/{author}/{pkg}/main/AGENTS.md)",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="Repo root (default: cwd)")
    args = parser.parse_args()

    repo = pathlib.Path(args.repo).resolve()
    llm_dir = repo / "llm"
    if not llm_dir.exists():
        print(f"regen_sitemap: {llm_dir} not found", file=sys.stderr)
        return 1

    meta = read_meta(repo)
    llm_files = [p for p in llm_dir.glob("*.md")]
    output = render(meta, llm_files)
    (repo / "llms.txt").write_text(output, encoding="utf-8")
    print(f"regen_sitemap: wrote {len(llm_files)} entries to llms.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
