"""Amatelier command-line entry point.

After ``pip install amatelier`` this is invoked as::

    amatelier <command> [args...]

Commands dispatch to the corresponding engine module by running it as if
invoked via ``python -m <module>``. The engine modules preserve their
original script-style argparse surfaces — they expect to be executed,
not imported as a library.
"""

from __future__ import annotations

import runpy
import sys

# Importing `amatelier` runs __init__.py which sets up sys.path for
# engine/ and store/ so bare imports inside engine modules resolve.
import amatelier  # noqa: F401  (side-effect import — sys.path shim)

# Map CLI subcommands to the module name that implements them. Each
# module runs as `__main__` via runpy so its `if __name__ == "__main__"`
# block fires. These module names resolve against the sys.path entries
# installed by `amatelier.__init__` (amatelier/engine/, amatelier/store/),
# so the bare names work without fully-qualified paths.
DISPATCH = {
    "roundtable": "roundtable_runner",
    "therapist": "therapist",
    "analytics": "analytics",
    "watch": "watch_roundtable",
}


def _usage() -> int:
    print(
        "amatelier — self-evolving multi-model AI team for Claude Code\n"
        "\n"
        "Usage:\n"
        "  amatelier roundtable [--topic TEXT --briefing PATH --budget N ...]\n"
        "  amatelier watch                Watch the live roundtable chat\n"
        "  amatelier therapist [...]      Run a therapist debrief cycle\n"
        "  amatelier analytics [...]      Print analytics across roundtables\n"
        "  amatelier --version\n"
        "  amatelier --help\n",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        return _usage()

    if argv[0] == "--version":
        from amatelier import __version__
        print(__version__)
        return 0

    cmd = argv[0]
    rest = argv[1:]

    module_name = DISPATCH.get(cmd)
    if module_name is None:
        print(f"amatelier: unknown command: {cmd}", file=sys.stderr)
        return _usage()

    # `watch_roundtable` lives in amatelier/tools/, not on the bare sys.path.
    # Resolve it through the package import path.
    if cmd == "watch":
        module_name = "amatelier.tools.watch_roundtable"

    # Re-mount argv so the target module's argparse sees the subcommand args.
    sys.argv = [module_name, *rest]

    try:
        runpy.run_module(module_name, run_name="__main__", alter_sys=True)
        return 0
    except SystemExit as e:
        # argparse / sys.exit in the target module bubbles up as SystemExit;
        # propagate the exit code.
        return int(e.code or 0) if isinstance(e.code, (int, type(None))) else 1


if __name__ == "__main__":
    sys.exit(main())
