"""Atelier command-line entry point.

After ``pip install atelier`` this is invoked as::

    atelier <command> [args...]

Commands dispatch to the corresponding engine module. The engine preserves
its original argparse surfaces; this wrapper just routes to the right one
and ensures the package sys.path shim is applied first.
"""

from __future__ import annotations

import sys

# Importing `atelier` runs __init__.py which sets up sys.path for
# engine/ and store/ so bare imports inside engine modules resolve.
import atelier  # noqa: F401  (side-effect import — sys.path shim)


def _usage() -> int:
    print(
        "atelier — self-evolving multi-model AI team for Claude Code\n"
        "\n"
        "Usage:\n"
        "  atelier roundtable [--topic TEXT --briefing PATH --budget N ...]\n"
        "  atelier watch                Watch the live roundtable chat\n"
        "  atelier therapist [...]      Run a therapist debrief cycle\n"
        "  atelier analytics [...]      Print analytics across roundtables\n"
        "  atelier --version\n"
        "  atelier --help\n",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        return _usage()

    if argv[0] == "--version":
        from atelier import __version__
        print(__version__)
        return 0

    cmd = argv[0]
    rest = argv[1:]

    # Re-mount argv for the invoked module so its argparse sees the right args.
    sys.argv = [cmd, *rest]

    if cmd == "roundtable":
        from roundtable_runner import main as run  # type: ignore[import-not-found]
        return int(run() or 0)

    if cmd == "watch":
        from atelier.tools import watch_roundtable
        return int(getattr(watch_roundtable, "main", lambda: 0)() or 0)

    if cmd == "therapist":
        from therapist import main as run  # type: ignore[import-not-found]
        return int(run() or 0)

    if cmd == "analytics":
        from analytics import main as run  # type: ignore[import-not-found]
        return int(run() or 0)

    print(f"atelier: unknown command: {cmd}", file=sys.stderr)
    return _usage()


if __name__ == "__main__":
    sys.exit(main())
