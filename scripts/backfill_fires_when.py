"""One-time backfill pass: author `fires_when` prose for every behavior
that doesn't already have it, then re-save so `save_behaviors` can compute
the embeddings.

Usage:
    python scripts/backfill_fires_when.py --agent naomi
    python scripts/backfill_fires_when.py --all

Auth: needs ANTHROPIC_API_KEY in the environment (uses Claude Sonnet to
author descriptions — quality matters, one-time cost is small).

Design:
- Idempotent: behaviors that already have non-empty `fires_when` are
  skipped. Re-runs are safe.
- Per-agent batched prompt: all that agent's unlabeled behaviors are
  sent in one call; structured JSON response is parsed.
- save_behaviors() auto-populates embeddings after we write the
  fires_when field, so the backfill is one step from the caller's view.
"""
from __future__ import annotations

import argparse
import json
import sys
import re
from pathlib import Path

# Locate the engine package regardless of where this script is run from.
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
    from amatelier.engine.evolver import load_behaviors, save_behaviors
except ImportError:
    from engine.evolver import load_behaviors, save_behaviors  # type: ignore


AUTHOR_PROMPT = """You are labeling learned behaviors for an AI roundtable agent with brief \
`fires_when` descriptions. Each description tells a runner when to semantically \
select this behavior for a given briefing.

For each numbered behavior below, write ONE fires_when description (1-2 sentences, \
plain prose) naming the briefing contexts where this rule should fire. Be specific \
about trigger conditions: the topic, the phase, the shape of the debate. Avoid \
"always" and "when appropriate" — those are useless for selection.

Good examples:
- "When the briefing asks for a structural-premise challenge, a multi-decision architectural RT, or a load-bearing-assumption audit."
- "When engaging rebuttal phases against strongly-argued positions in architectural debates — any RT where the agent needs to escalate beyond framing."
- "When the current RT involves explicit scoring debate, novelty deployment, or multi-stage RT phase planning."

Bad examples:
- "Always."
- "When useful."
- "Related to retrieval."

Agent: {agent}

Behaviors:
{behaviors_block}

Respond with STRICT JSON only — no prose, no markdown fence:

{{
  "fires_when": {{
    "1": "description for behavior 1",
    "2": "description for behavior 2",
    ...
  }}
}}

Every index must appear. No commentary outside the JSON.
"""


def _render_behaviors_block(behaviors: list[dict]) -> str:
    lines = []
    for idx, b in enumerate(behaviors, 1):
        text = (b.get("text") or "").strip()
        lines.append(f"[{idx}] {text}")
    return "\n".join(lines)


def _call_sonnet(prompt: str) -> str:
    """Invoke Claude Sonnet via the Claude CLI (matches the suite's pattern).

    Uses the user's Claude Code auth — no ANTHROPIC_API_KEY required.
    """
    import subprocess
    result = subprocess.run(
        [
            "claude", "-p", "--model", "sonnet",
            "--no-session-persistence", "--output-format", "text",
            "--disable-slash-commands", "--dangerously-skip-permissions",
            "--max-budget-usd", "5.00",
        ],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=240,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (exit {result.returncode}): {result.stderr[:400]}"
        )
    return result.stdout.strip()


def _parse_json_loosely(text: str) -> dict:
    """Pull the first JSON object from `text`, tolerant of surrounding prose."""
    text = text.strip()
    # Strip markdown fences if the model ignored the instruction.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find first { and matching }
    start = text.find("{")
    if start < 0:
        raise ValueError("No JSON object in response")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("Unbalanced JSON object in response")


def backfill_agent(agent_name: str, *, dry_run: bool = False) -> dict:
    """Author fires_when for any missing behaviors of `agent_name`.

    Returns {"labeled": N, "skipped": N, "failed": N}.
    """
    behaviors = load_behaviors(agent_name)
    if not behaviors:
        print(f"[{agent_name}] no behaviors — skipping")
        return {"labeled": 0, "skipped": 0, "failed": 0}

    missing_idx: list[int] = []
    for i, b in enumerate(behaviors):
        fw = (b.get("fires_when") or "").strip()
        if not fw:
            missing_idx.append(i)

    if not missing_idx:
        print(f"[{agent_name}] all {len(behaviors)} behaviors already have fires_when")
        return {"labeled": 0, "skipped": len(behaviors), "failed": 0}

    missing_behaviors = [behaviors[i] for i in missing_idx]
    behaviors_block = _render_behaviors_block(missing_behaviors)
    prompt = AUTHOR_PROMPT.format(agent=agent_name, behaviors_block=behaviors_block)

    print(f"[{agent_name}] authoring fires_when for {len(missing_idx)} behavior(s)…")
    if dry_run:
        print(prompt[:2000])
        return {"labeled": 0, "skipped": len(behaviors) - len(missing_idx),
                "failed": 0, "dry_run": True}

    raw = _call_sonnet(prompt)
    try:
        parsed = _parse_json_loosely(raw)
    except ValueError as e:
        print(f"[{agent_name}] parse failed: {e}")
        print("Raw response head:", raw[:500])
        return {"labeled": 0, "skipped": len(behaviors) - len(missing_idx),
                "failed": len(missing_idx)}

    mapping = parsed.get("fires_when", {})
    labeled = 0
    failed = 0
    for list_idx, behavior_idx in enumerate(missing_idx, 1):
        fw = (mapping.get(str(list_idx)) or "").strip()
        if not fw:
            failed += 1
            continue
        behaviors[behavior_idx]["fires_when"] = fw
        labeled += 1

    # save_behaviors() auto-populates fires_when_embedding for newly-labeled rows.
    save_behaviors(agent_name, behaviors)
    print(f"[{agent_name}] labeled={labeled} failed={failed} "
          f"already_had={len(behaviors) - len(missing_idx)}")
    return {"labeled": labeled,
            "skipped": len(behaviors) - len(missing_idx),
            "failed": failed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill fires_when on behaviors.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--agent", help="Single agent name (e.g., naomi)")
    group.add_argument("--all", action="store_true",
                       help="Run for all agents in the standard roster")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the prompt without calling the LLM")
    args = parser.parse_args()

    if args.all:
        try:
            from amatelier.worker_registry import list_workers
        except ImportError:
            list_workers = lambda: ["elena", "marcus", "clare", "simon", "naomi"]  # noqa
        agents = list_workers()
    else:
        agents = [args.agent]

    total = {"labeled": 0, "skipped": 0, "failed": 0}
    for a in agents:
        result = backfill_agent(a, dry_run=args.dry_run)
        for k in ("labeled", "skipped", "failed"):
            total[k] += result.get(k, 0)
    print(f"\nTOTAL: labeled={total['labeled']} skipped={total['skipped']} "
          f"failed={total['failed']}")
    return 0 if total["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
