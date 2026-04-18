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
import amatelier  # noqa: E402, F401  (side-effect after UTF-8 reconfigure)

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
        "  amatelier refresh-seeds [--agent NAME] [--force]\n"
        "                                 Re-copy persona seeds from the wheel\n"
        "                                 (overwrites user_data_dir copies)\n"
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


def _run_refresh_seeds(args: list[str]) -> int:
    """Re-copy agent persona seeds (CLAUDE.md / IDENTITY.md) from the bundled
    wheel layer into user_data_dir, overwriting any local edits.

    Amatelier is fire-and-forget: pip upgrades NEVER clobber your local rule
    edits. When you DO want the latest shipped rules (e.g. after a package
    upgrade that improved the therapist interview framework), run this.
    """
    from amatelier import paths

    parser = argparse.ArgumentParser(prog="amatelier refresh-seeds")
    parser.add_argument("--agent", help="Refresh only this agent (else all)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite local CLAUDE.md / IDENTITY.md even if modified",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change; write nothing",
    )
    ns = parser.parse_args(args)

    bundled_agents = paths.bundled_assets_dir() / "agents"
    if not bundled_agents.exists():
        print("error: bundled agents not found in this install", file=sys.stderr)
        return 1

    agent_names = [ns.agent] if ns.agent else [
        d.name for d in sorted(bundled_agents.iterdir()) if d.is_dir()
    ]

    refreshed, skipped, written = [], [], []
    for name in agent_names:
        seed_dir = bundled_agents / name
        if not seed_dir.exists():
            print(f"warning: no bundled seed for agent '{name}'", file=sys.stderr)
            continue
        dst_dir = paths.user_agent_dir(name)
        dst_dir.mkdir(parents=True, exist_ok=True)
        for fname in ("CLAUDE.md", "IDENTITY.md"):
            src = seed_dir / fname
            dst = dst_dir / fname
            if not src.exists():
                continue
            bundled_content = src.read_text(encoding="utf-8")
            if dst.exists():
                current = dst.read_text(encoding="utf-8")
                if current == bundled_content:
                    skipped.append(f"{name}/{fname} (already current)")
                    continue
                if not ns.force:
                    skipped.append(f"{name}/{fname} (user-modified; use --force to overwrite)")
                    continue
            if ns.dry_run:
                written.append(f"{name}/{fname} (would refresh)")
            else:
                dst.write_text(bundled_content, encoding="utf-8")
                written.append(f"{name}/{fname}")
                refreshed.append(name)

    if ns.dry_run:
        print("dry run — no files written\n")
    print(f"Refreshed: {len(written)}")
    for line in written:
        print(f"  [WRITE] {line}")
    if skipped:
        print(f"\nSkipped: {len(skipped)}")
        for line in skipped:
            print(f"  [SKIP] {line}")
    if ns.force and refreshed:
        print(
            f"\nNote: {len(set(refreshed))} agent(s) refreshed. Their accumulated "
            "MEMORY.md / behaviors.json / metrics.json are untouched — only the "
            "persona rules and identity seeds were overwritten."
        )
    return 0


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
    if cmd == "refresh-seeds":
        return _run_refresh_seeds(rest)
    if cmd in DISPATCH_ENGINE:
        return _run_engine_module(cmd, rest)

    print(f"amatelier: unknown command: {cmd}", file=sys.stderr)
    return _usage()


if __name__ == "__main__":
    sys.exit(main())
