"""Reconcile CLAUDE.md's "## Learned Behaviors" section with behaviors.json.

behaviors.json is the source of truth. CLAUDE.md is rebuilt to mirror it
exactly — orphan bullets that accumulated before behaviors.json existed
(or were added outside the evolver code path) get dropped.

Usage:
    python scripts/sync_claude_md_behaviors.py --agent naomi
    python scripts/sync_claude_md_behaviors.py --all
    python scripts/sync_claude_md_behaviors.py --all --dry-run

Safe:
- Only the "## Learned Behaviors" section is rewritten. Everything else
  in CLAUDE.md is preserved byte-for-byte.
- `evolver.write_claude_md()` already creates a timestamped backup in
  `agents/{name}/sessions/` before writing, so each run is reversible.
- `--dry-run` shows the delta per agent without touching any file.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for candidate in [HERE / ".." / "src", HERE / ".."]:
    candidate = candidate.resolve()
    if (candidate / "amatelier" / "engine" / "evolver.py").exists():
        sys.path.insert(0, str(candidate))
        break
    if (candidate / "engine" / "evolver.py").exists():
        sys.path.insert(0, str(candidate))
        break

try:
    from amatelier.engine.evolver import (
        load_behaviors, read_claude_md, write_claude_md,
    )
except ImportError:
    from engine.evolver import (  # type: ignore
        load_behaviors, read_claude_md, write_claude_md,
    )


SECTION_HEADER = "## Learned Behaviors"


def _extract_current_bullets(content: str) -> list[str]:
    """Return the list of bullet texts currently under Learned Behaviors."""
    if SECTION_HEADER not in content:
        return []
    idx = content.index(SECTION_HEADER)
    end_idx = content.find("\n## ", idx + 1)
    if end_idx == -1:
        end_idx = len(content)
    section = content[idx:end_idx]
    bullets = []
    for line in section.splitlines():
        line = line.rstrip()
        if line.startswith("- "):
            bullets.append(line[2:])
    return bullets


def _replace_section(content: str, new_bullets: list[str]) -> str:
    """Rewrite the Learned Behaviors section with the given bullet list.

    Preserves everything else in the file. If the section doesn't exist,
    appends it at the end.
    """
    if new_bullets:
        new_body = SECTION_HEADER + "\n" + "\n".join(f"- {b}" for b in new_bullets) + "\n"
    else:
        new_body = SECTION_HEADER + "\nNone yet.\n"

    if SECTION_HEADER not in content:
        return content.rstrip() + "\n\n" + new_body

    idx = content.index(SECTION_HEADER)
    end_idx = content.find("\n## ", idx + 1)
    if end_idx == -1:
        # Section runs to EOF
        return content[:idx] + new_body
    # Section is followed by another section — preserve the separator
    return content[:idx] + new_body + content[end_idx:]


def sync_agent(agent_name: str, *, dry_run: bool = False) -> dict:
    """Reconcile one agent's CLAUDE.md against its behaviors.json.

    Returns {"before": N, "after": M, "removed": [orphan bullets],
             "added": [bullets added back]}.
    """
    behaviors = load_behaviors(agent_name)
    truth_bullets = [b.get("text", "").strip() for b in behaviors if b.get("text")]

    content = read_claude_md(agent_name)
    current_bullets = _extract_current_bullets(content)

    # Diff for reporting. Exact-text comparison — fuzzy reconciliation is
    # out of scope; behaviors.json wins by construction.
    current_set = set(current_bullets)
    truth_set = set(truth_bullets)
    orphans = [b for b in current_bullets if b not in truth_set]
    added = [b for b in truth_bullets if b not in current_set]

    summary = {
        "agent": agent_name,
        "before": len(current_bullets),
        "after": len(truth_bullets),
        "removed_orphans": len(orphans),
        "added_from_json": len(added),
        "orphan_sample": [o[:100] for o in orphans[:3]],
    }

    if dry_run:
        return summary

    new_content = _replace_section(content, truth_bullets)
    if new_content != content:
        write_claude_md(agent_name, new_content)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync CLAUDE.md Learned Behaviors with behaviors.json.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--agent", help="Single agent name")
    group.add_argument("--all", action="store_true", help="Run for all workers")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report changes without modifying files")
    args = parser.parse_args()

    if args.all:
        try:
            from amatelier.worker_registry import list_workers
            agents = list_workers()
        except ImportError:
            agents = ["elena", "marcus", "clare", "simon", "naomi"]
    else:
        agents = [args.agent]

    label = "dry-run" if args.dry_run else "writing"
    print(f"=== {label} ===")
    for a in agents:
        r = sync_agent(a, dry_run=args.dry_run)
        print(f"\n[{r['agent']}]")
        print(f"  before (CLAUDE.md bullets): {r['before']}")
        print(f"  after  (behaviors.json):    {r['after']}")
        print(f"  orphans to drop:            {r['removed_orphans']}")
        print(f"  missing from CLAUDE.md:     {r['added_from_json']}")
        if r["orphan_sample"]:
            print("  orphan samples:")
            for s in r["orphan_sample"]:
                print(f"    · {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
