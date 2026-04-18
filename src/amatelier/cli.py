"""Amatelier command-line entry point.

After ``pip install amatelier`` this is invoked as::

    amatelier <command> [args...]

Most commands dispatch to an engine module run via runpy. The ``docs``
and ``config`` commands are implemented here directly.
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
from pathlib import Path

# Force UTF-8 stdout/stderr so bundled docs and any Unicode in engine
# output render cleanly on Windows consoles (cp1252 default chokes on
# arrows, em-dashes, etc.).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

# Importing `amatelier` runs __init__.py which sets up sys.path for
# engine/ and store/ so bare imports inside engine modules resolve,
# and calls ensure_user_data() to bootstrap the writable tree.
import amatelier  # noqa: F401  (side-effect import)

DISPATCH_ENGINE = {
    "roundtable": "roundtable_runner",
    "therapist": "therapist",
    "analytics": "analytics",
    "watch": "amatelier.tools.watch_roundtable",
}


def _usage() -> int:
    print(
        "amatelier — self-evolving multi-model AI team\n"
        "\n"
        "Usage:\n"
        "  amatelier roundtable --topic TEXT --briefing PATH [--budget N] [--summary]\n"
        "  amatelier watch                Watch the live roundtable chat\n"
        "  amatelier therapist --digest PATH [--agents LIST] [--turns N]\n"
        "  amatelier analytics SUBCOMMAND\n"
        "  amatelier docs [TOPIC]         Show bundled documentation\n"
        "  amatelier config [--json]      Show detected LLM mode + paths\n"
        "  amatelier --version\n"
        "  amatelier --help\n"
        "\n"
        "LLM modes (auto-detected):\n"
        "  claude-code    — claude CLI on PATH\n"
        "  anthropic-sdk  — ANTHROPIC_API_KEY set\n"
        "  openai-compat  — OPENAI_API_KEY or OPENROUTER_API_KEY set\n"
        "\n"
        "Run `amatelier config` to see the detected mode and configure.\n",
        file=sys.stderr,
    )
    return 2


def _run_docs(args: list[str]) -> int:
    """Print bundled documentation to stdout, or list available topics."""
    from amatelier import paths

    docs_dir = paths.bundled_docs_dir()
    if not docs_dir.exists():
        print("docs not bundled in this install.", file=sys.stderr)
        print(
            "Browse online: https://amatayomosley-web.github.io/amatelier/",
            file=sys.stderr,
        )
        return 1

    if not args:
        # List available docs
        print("Amatelier documentation (bundled)\n")
        print(f"Location: {docs_dir}\n")
        for tier in ("tutorials", "guides", "reference", "explanation"):
            tier_dir = docs_dir / tier
            if not tier_dir.exists():
                continue
            print(f"  {tier}/")
            for md in sorted(tier_dir.rglob("*.md")):
                rel = md.relative_to(docs_dir)
                topic = str(rel).replace("\\", "/").removesuffix(".md")
                print(f"    amatelier docs {topic}")
            print()
        print("Full site: https://amatayomosley-web.github.io/amatelier/")
        return 0

    topic = args[0].replace("\\", "/")
    # Accept "guides/install", "install", or "guides install" forms.
    candidates = [
        docs_dir / f"{topic}.md",
        docs_dir / topic / "index.md",
        docs_dir / "guides" / f"{topic}.md",
        docs_dir / "tutorials" / f"{topic}.md",
        docs_dir / "reference" / f"{topic}.md",
        docs_dir / "explanation" / f"{topic}.md",
    ]
    for c in candidates:
        if c.exists():
            print(c.read_text(encoding="utf-8"))
            return 0

    print(f"doc topic not found: {topic}", file=sys.stderr)
    print("Run `amatelier docs` (no args) to list available topics.", file=sys.stderr)
    return 1


def _run_config(args: list[str]) -> int:
    """Diagnose the current LLM backend and paths configuration."""
    from amatelier import llm_backend, paths

    env = llm_backend.describe_environment()
    snapshot = {
        "version": amatelier.__version__,
        "llm": env,
        "paths": {
            "bundled_assets_dir": str(paths.bundled_assets_dir()),
            "bundled_docs_dir": str(paths.bundled_docs_dir()),
            "user_data_dir": str(paths.user_data_dir()),
            "user_db_path": str(paths.user_db_path()),
            "AMATELIER_WORKSPACE": os.environ.get("AMATELIER_WORKSPACE", "") or "(unset)",
        },
        "env": {
            "CLAUDE_ON_PATH": env["claude-code"]["available"],
            "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
            "OPENROUTER_API_KEY": bool(os.environ.get("OPENROUTER_API_KEY")),
            "GEMINI_API_KEY": bool(os.environ.get("GEMINI_API_KEY")),
        },
    }

    if "--json" in args:
        print(json.dumps(snapshot, indent=2))
        return 0

    print(f"amatelier {snapshot['version']}")
    print()
    print("LLM backend")
    print(f"  active mode: {env['active_mode']}")
    override = env["explicit_override"]
    if override:
        print(f"  explicit override: AMATELIER_MODE={override}")
    print()
    print("Available backends:")
    for mode in ("claude-code", "anthropic-sdk", "openai-compat"):
        marker = "[OK]" if env[mode]["available"] else "[  ]"
        print(f"  {marker} {mode:14} ({env[mode]['detected_via']})")
    print()
    print("Credentials seen in environment:")
    for key, present in snapshot["env"].items():
        marker = "[OK]" if present else "[  ]"
        print(f"  {marker} {key}")
    print()
    print("Paths:")
    for k, v in snapshot["paths"].items():
        print(f"  {k:22} {v}")
    print()
    if env["active_mode"] == "none":
        print("!! No backend available. Set up one of:")
        print("     - Install Claude Code (https://claude.com/claude-code)")
        print("     - export ANTHROPIC_API_KEY=... (https://console.anthropic.com)")
        print("     - export OPENAI_API_KEY=... (https://platform.openai.com)")
        print("     - export OPENROUTER_API_KEY=... (https://openrouter.ai)")
        return 1
    return 0


def _run_engine_module(cmd: str, rest: list[str]) -> int:
    """Run an engine-side module via runpy, preserving its argparse surface."""
    module_name = DISPATCH_ENGINE[cmd]
    sys.argv = [module_name, *rest]
    try:
        runpy.run_module(module_name, run_name="__main__", alter_sys=True)
        return 0
    except SystemExit as e:
        return int(e.code or 0) if isinstance(e.code, (int, type(None))) else 1


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        return _usage()

    if argv[0] == "--version":
        from amatelier import __version__
        print(__version__)
        return 0

    cmd, rest = argv[0], argv[1:]

    if cmd == "docs":
        return _run_docs(rest)
    if cmd == "config":
        return _run_config(rest)
    if cmd in DISPATCH_ENGINE:
        return _run_engine_module(cmd, rest)

    print(f"amatelier: unknown command: {cmd}", file=sys.stderr)
    return _usage()


if __name__ == "__main__":
    sys.exit(main())
