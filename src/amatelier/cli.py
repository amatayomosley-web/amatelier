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
        "  amatelier init                 Bootstrap + show status (first-run entry)\n"
        "  amatelier roundtable --topic TEXT --briefing PATH [--budget N] [--summary]\n"
        "  amatelier watch                Watch the live roundtable chat\n"
        "  amatelier team SUBCOMMAND      Manage the worker roster\n"
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


def _run_init(args: list[str]) -> int:
    """Bootstrap the writable user_data_dir and confirm setup status.

    v0.4.0: explicit entry point that runs `paths.ensure_user_data()` (which
    also fires automatically on first `import amatelier`). Useful for a
    clear "first-run" experience — shows where data lives, what agents are
    configured, which backend is active, and any warnings.
    """
    parser = argparse.ArgumentParser(prog="amatelier init")
    parser.add_argument("--force", action="store_true",
                        help="Re-run bootstrap even if .bootstrap-complete exists")
    parser.add_argument("--template", default=None,
                        choices=["curated-five", "minimal", "empty"],
                        help="Start with a specific roster template (default: curated-five)")
    ns = parser.parse_args(args)

    from amatelier import __version__, paths, worker_registry

    print(f"amatelier {__version__}")
    print()

    udir = paths.user_data_dir()
    was_bootstrapped = (udir / ".bootstrap-complete").exists()

    if ns.force or not was_bootstrapped:
        paths.ensure_user_data()
        print(f"Bootstrapped user data: {udir}")
    else:
        print(f"User data already bootstrapped: {udir}")

    if ns.template and ns.template != "curated-five":
        print()
        print(f"Importing template: {ns.template}")
        result = _team_import([ns.template, "--replace"])
        if result != 0:
            return result

    # Show roster
    print()
    workers = worker_registry.list_workers()
    if workers:
        print(f"Active roster: {len(workers)} workers — {', '.join(workers)}")
    else:
        print("Active roster: empty — add workers with `amatelier team new`")

    # Show backend
    print()
    try:
        from amatelier.llm_backend import resolve_mode
        mode = resolve_mode()
        print(f"LLM backend: {mode}")
    except Exception:
        print("LLM backend: (not yet configured — run `amatelier config`)")

    print()
    print("Next steps:")
    print("  amatelier config              Diagnose backend + credentials")
    print("  amatelier team list           See the active roster")
    print("  amatelier roundtable --help   See how to run a debate")
    return 0


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


# ─────────────────────────────────────────────────────────────────────────
# `amatelier team` subcommands (v0.4.0)
# ─────────────────────────────────────────────────────────────────────────


def _load_user_config() -> dict:
    """Load user's config.json (from user_data_dir), falling back to bundled."""
    from amatelier import paths
    user_cfg = paths.user_config_override()
    if not user_cfg.exists():
        bundled = paths.bundled_config()
        if bundled.exists():
            user_cfg.parent.mkdir(parents=True, exist_ok=True)
            user_cfg.write_text(bundled.read_text(encoding="utf-8"), encoding="utf-8")
    if not user_cfg.exists():
        return {}
    try:
        return json.loads(user_cfg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_user_config(data: dict) -> None:
    from amatelier import paths
    user_cfg = paths.user_config_override()
    user_cfg.parent.mkdir(parents=True, exist_ok=True)
    user_cfg.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _templates_dir():
    from amatelier import paths
    return paths.bundled_assets_dir() / "agents" / "templates"


def _agents_user_dir():
    from amatelier import paths
    return paths.user_data_dir() / "agents"


def _team_list(_args: list[str]) -> int:
    from amatelier import worker_registry
    roster = worker_registry.describe_roster()
    if not roster["workers"]:
        print("No workers configured.")
        print()
        print("Add one:       amatelier team new <name> --model sonnet --role \"...\"")
        print("Or import:     amatelier team import minimal")
        print("Or see all:    amatelier team templates")
        return 0
    print(f"Active roster ({roster['count']} workers):")
    max_name = max((len(w["name"]) for w in roster["workers"]), default=8)
    max_model = max((len(w["model"]) for w in roster["workers"]), default=8)
    for w in roster["workers"]:
        role = w["role"] or "(no role set)"
        if len(role) > 60:
            role = role[:57] + "..."
        print(
            f"  {w['name']:<{max_name}}  "
            f"{w['backend']:<13}  "
            f"{w['model']:<{max_model}}  "
            f"{role}"
        )
    print()
    by_backend = roster["backends"]
    for backend in ("claude", "gemini", "openai-compat"):
        names = by_backend.get(backend, [])
        if names:
            print(f"  {backend}: {len(names)} worker(s) — {', '.join(names)}")
    return 0


def _team_new(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="amatelier team new")
    parser.add_argument("name", help="Worker agent name (lowercase, alphanumeric + dashes)")
    parser.add_argument("--model", default="sonnet",
                        help="Model alias or provider ID (default: sonnet)")
    parser.add_argument("--backend", default="claude",
                        choices=["claude", "gemini", "openai-compat"],
                        help="Backend routing (default: claude)")
    parser.add_argument("--role", default="",
                        help="Free-form role description")
    parser.add_argument("--from-template", default="",
                        help="Optional: copy CLAUDE.md/IDENTITY.md from this template/agent dir")
    ns = parser.parse_args(args)

    name = ns.name.lower().strip()
    if not name or not all(c.isalnum() or c == "-" for c in name):
        print(f"Invalid name: {name!r}. Use lowercase alphanumeric + dashes.", file=sys.stderr)
        return 1

    from amatelier import worker_registry
    if worker_registry.worker_exists(name):
        print(f"Worker {name!r} already exists. Remove first: amatelier team remove {name}")
        return 1

    # Create agent folder with minimal scaffolding
    agent_dir = _agents_user_dir() / name
    agent_dir.mkdir(parents=True, exist_ok=True)

    claude_md = agent_dir / "CLAUDE.md"
    identity_md = agent_dir / "IDENTITY.md"

    if ns.from_template:
        src = _templates_dir() / ns.from_template
        if not src.exists():
            # Fall back to direct agent folder under bundled
            from amatelier import paths
            src = paths.bundled_assets_dir() / "agents" / ns.from_template
        if src.exists() and src.is_dir():
            for fname in ("CLAUDE.md", "IDENTITY.md"):
                src_file = src / fname
                if src_file.exists():
                    (agent_dir / fname).write_text(
                        src_file.read_text(encoding="utf-8"),
                        encoding="utf-8",
                    )

    if not claude_md.exists():
        claude_md.write_text(
            f"# {name.capitalize()} — CLAUDE.md\n\n"
            "<!-- Persona system prompt. Written in first person, to the model. -->\n\n"
            f"You are {name}.\n\n"
            f"## Role\n\n{ns.role or 'Describe your role here.'}\n\n"
            "## Voice\n\n"
            "<!-- Distinctive voice and approach. Avoid the eager-assistant trap. -->\n\n"
            "## Focus\n\n"
            "<!-- What you specialize in. What failure modes you catch. -->\n",
            encoding="utf-8",
        )
    if not identity_md.exists():
        identity_md.write_text(
            f"# {name.capitalize()}\n\n"
            f"- **Role:** {ns.role or '(describe)'}\n"
            f"- **Model:** {ns.model}\n"
            f"- **Backend:** {ns.backend}\n",
            encoding="utf-8",
        )

    # Update config
    cfg = _load_user_config()
    cfg.setdefault("team", {}).setdefault("workers", {})
    cfg["team"]["workers"][name] = {
        "model": ns.model,
        "backend": ns.backend,
        "role": ns.role,
        "assignments": 0,
    }
    _save_user_config(cfg)

    print(f"Created {agent_dir}")
    print(f"Updated config.team.workers with {name!r}")
    print()
    print(f"Edit {claude_md.name} to refine the persona.")
    print("Run:  amatelier team list")
    return 0


def _team_remove(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="amatelier team remove")
    parser.add_argument("name", help="Worker to remove from config")
    parser.add_argument("--delete-folder", action="store_true",
                        help="Also delete the agent's data folder (destructive)")
    ns = parser.parse_args(args)

    name = ns.name
    cfg = _load_user_config()
    workers = cfg.get("team", {}).get("workers", {})
    if name not in workers:
        print(f"Worker {name!r} not in config.")
        return 1

    del workers[name]
    _save_user_config(cfg)
    print(f"Removed {name!r} from config.team.workers.")

    agent_dir = _agents_user_dir() / name
    if agent_dir.exists():
        if ns.delete_folder:
            import shutil
            shutil.rmtree(agent_dir)
            print(f"Deleted folder: {agent_dir}")
        else:
            print(f"Agent folder preserved at {agent_dir}")
            print("Use --delete-folder to remove it entirely.")
    return 0


def _team_templates(_args: list[str]) -> int:
    tdir = _templates_dir()
    if not tdir.exists():
        print(f"No templates directory at {tdir}")
        return 1
    print(f"Starter rosters (in {tdir}):")
    for entry in sorted(tdir.iterdir()):
        if not entry.is_dir():
            continue
        readme = entry / "README.md"
        desc = ""
        if readme.exists():
            first_lines = readme.read_text(encoding="utf-8").splitlines()[:3]
            for ln in first_lines:
                s = ln.strip()
                if s and not s.startswith("#"):
                    desc = s[:80]
                    break
        workers_in = [
            d.name for d in entry.iterdir()
            if d.is_dir() and d.name not in ("admin", "judge", "therapist")
        ]
        worker_count = len(workers_in)
        print(f"  {entry.name:<16}  {worker_count} worker(s)  {desc}")
    print()
    print("Import with:   amatelier team import <name>")
    return 0


def _team_import(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="amatelier team import")
    parser.add_argument("template", help="Template name (see: amatelier team templates)")
    parser.add_argument("--replace", action="store_true",
                        help="Replace current roster entirely (default: merge)")
    ns = parser.parse_args(args)

    src = _templates_dir() / ns.template
    if not src.exists() or not src.is_dir():
        print(f"Template not found: {ns.template}", file=sys.stderr)
        print("See available: amatelier team templates", file=sys.stderr)
        return 1

    import shutil
    user_agents = _agents_user_dir()
    user_agents.mkdir(parents=True, exist_ok=True)

    cfg = _load_user_config()
    cfg.setdefault("team", {}).setdefault("workers", {})
    if ns.replace:
        cfg["team"]["workers"] = {}

    imported: list[str] = []
    for entry in sorted(src.iterdir()):
        if not entry.is_dir():
            continue
        dest = user_agents / entry.name
        if dest.exists():
            print(f"  (already present, skipping) {entry.name}")
            continue
        shutil.copytree(entry, dest)
        # If it's a worker (not admin/judge/therapist), register in config
        if entry.name not in ("admin", "judge", "therapist"):
            # Try to read IDENTITY.md for model hint
            imported.append(entry.name)
            cfg["team"]["workers"].setdefault(entry.name, {
                "model": "sonnet",
                "backend": "claude",
                "role": "",
                "assignments": 0,
            })

    _save_user_config(cfg)
    print(f"Imported {len(imported)} worker(s) from {ns.template!r}: {', '.join(imported)}")
    print(f"Config updated at {_load_user_config and 'user_data_dir/config.json'}")
    print()
    print("Review with:  amatelier team list")
    return 0


def _team_validate(_args: list[str]) -> int:
    from amatelier import worker_registry
    user_agents = _agents_user_dir()
    errors: list[str] = []
    warnings: list[str] = []

    workers = worker_registry.list_workers()
    if not workers:
        warnings.append("No workers configured — RT will refuse to start.")

    for name in workers:
        agent_dir = user_agents / name
        if not agent_dir.exists():
            errors.append(f"{name}: config entry exists but no folder at {agent_dir}")
            continue
        for required in ("CLAUDE.md", "IDENTITY.md"):
            if not (agent_dir / required).exists():
                errors.append(f"{name}: missing {required}")
        backend = worker_registry.get_worker_backend(name)
        if backend not in ("claude", "gemini", "openai-compat"):
            warnings.append(f"{name}: unknown backend {backend!r}; defaulting to claude")

    # Check admin-side roles
    for role in ("admin", "judge", "therapist"):
        if not (user_agents / role).exists():
            warnings.append(f"Admin-side role {role!r} missing at {user_agents / role}")

    if not errors and not warnings:
        print(f"Roster OK. {len(workers)} workers, all folders present.")
        return 0

    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  - {e}")
    if warnings:
        print("WARNINGS:" if not errors else "\nWARNINGS:")
        for w in warnings:
            print(f"  - {w}")
    return 1 if errors else 0


def _run_team(args: list[str]) -> int:
    if not args or args[0] in ("-h", "--help"):
        print(
            "amatelier team — manage the worker roster\n"
            "\n"
            "Subcommands:\n"
            "  list                                    Show current roster\n"
            "  new <name> [--model M] [--backend B] [--role R] [--from-template T]\n"
            "                                          Add a new worker\n"
            "  remove <name> [--delete-folder]         Remove a worker from config\n"
            "  import <template> [--replace]           Load a starter roster\n"
            "  templates                               List available starter rosters\n"
            "  validate                                Check roster integrity\n"
            "\n"
            "Examples:\n"
            "  amatelier team list\n"
            "  amatelier team new nova --model sonnet --role \"distributed systems\"\n"
            "  amatelier team import minimal\n"
            "  amatelier team validate\n",
            file=sys.stderr,
        )
        return 0 if (args and args[0] in ("-h", "--help")) else 2

    sub, rest = args[0], args[1:]
    handlers = {
        "list": _team_list,
        "new": _team_new,
        "remove": _team_remove,
        "import": _team_import,
        "templates": _team_templates,
        "validate": _team_validate,
    }
    if sub not in handlers:
        print(f"Unknown subcommand: team {sub}", file=sys.stderr)
        return _run_team([])
    return handlers[sub](rest)


# ─────────────────────────────────────────────────────────────────────────

_CONSENT_ENV = "AMATELIER_STEWARD_CONSENT"
_CONSENT_TRUTHY = frozenset({"1", "yes", "true", "y"})

_CONSENT_DISCLOSURE = """\

amatelier roundtable will spawn worker agents that may emit
[[request: ...]] tags. When that happens, the Steward subagent reads
files from your project workspace and sends excerpts to:

  - the Anthropic API (claude-code mode and anthropic-sdk mode), or
  - the OpenAI-compatible endpoint you've configured

These excerpts become part of the durable RT digest and message log.
A credential denylist (~/.env, .ssh keys, .aws/credentials, etc.) is
applied at read time, but renamed or non-standard secret files are
not detected. Truncation caps each excerpt at 4 KB.

By proceeding, you confirm that:
  1. The current workspace does not contain unmanaged secrets, AND
  2. You consent to file excerpts being transmitted to the configured
     LLM provider for the duration of this RT.

Set AMATELIER_STEWARD_CONSENT=1 in your environment to skip this
prompt in CI / automation.
"""


def _check_steward_consent() -> int:
    """Return 0 if consent is granted, non-zero exit code if not.

    Honored env var: AMATELIER_STEWARD_CONSENT (1/yes/true/y → granted).
    Otherwise prints disclosure and prompts y/n. Sets the env var on accept
    so that this process's subprocess children (the runner, agents,
    Steward) all inherit the granted state without re-prompting.
    """
    existing = (os.environ.get(_CONSENT_ENV, "") or "").strip().lower()
    if existing in _CONSENT_TRUTHY:
        return 0

    # Non-interactive (no TTY) and no env var → refuse rather than block on input
    if not sys.stdin.isatty():
        sys.stderr.write(_CONSENT_DISCLOSURE)
        sys.stderr.write(
            "\n[refusing] Non-interactive session and "
            f"{_CONSENT_ENV} not set. Set it to '1' in your CI env to proceed.\n"
        )
        return 2

    sys.stdout.write(_CONSENT_DISCLOSURE)
    sys.stdout.write("\nProceed? [y/N]: ")
    sys.stdout.flush()
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        sys.stdout.write("\n[cancelled]\n")
        return 130
    if answer not in _CONSENT_TRUTHY:
        sys.stdout.write("[declined] Steward dispatch will not run.\n")
        return 1
    os.environ[_CONSENT_ENV] = "1"
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

    if cmd == "init":
        return _run_init(rest)
    if cmd == "docs":
        return _run_docs(rest)
    if cmd == "config":
        return _run_config(rest)
    if cmd == "refresh-seeds":
        return _run_refresh_seeds(rest)
    if cmd == "team":
        return _run_team(rest)
    if cmd in DISPATCH_ENGINE:
        # Steward consent gate fires before the runner spawns workers.
        # GDPR Article 13 requires disclosure before processing event.
        if cmd == "roundtable":
            consent_exit = _check_steward_consent()
            if consent_exit != 0:
                return consent_exit
        return _run_engine_module(cmd, rest)

    print(f"amatelier: unknown command: {cmd}", file=sys.stderr)
    return _usage()


if __name__ == "__main__":
    sys.exit(main())
