"""Batch-classify existing novel concepts with the full taxonomy.

Sends ~15 concepts per Sonnet call to minimize cost.
Skips concepts that already have classification fields.

Usage:
    python engine/classify_concepts.py              # Classify all unclassified
    python engine/classify_concepts.py --dry-run    # Show what would be classified
    python engine/classify_concepts.py --limit 15   # Classify one batch only
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SUITE_ROOT = Path(__file__).resolve().parent.parent

# Amatayo Standard dual-layer paths: bundled assets stay in SUITE_ROOT
# (read-only post-install); mutable runtime state goes to WRITE_ROOT.
try:
    from amatelier import paths as _amatelier_paths
    _amatelier_paths.ensure_user_data()
    WRITE_ROOT = _amatelier_paths.user_data_dir()
except Exception:
    WRITE_ROOT = SUITE_ROOT

DB_PATH = WRITE_ROOT / "novel_concepts.json"
BATCH_SIZE = 15


def _needs_classification(concept: dict) -> bool:
    """Check if a concept is missing taxonomy fields."""
    return not concept.get("structural_category")


def _classify_batch(batch: list[dict]) -> list[dict]:
    """Send a batch of concepts to Sonnet for classification."""
    items = []
    for c in batch:
        items.append({
            "id": c["id"],
            "title": c["title"],
            "pattern": c["pattern"][:400],
            "when_to_apply": c.get("when_to_apply", "")[:200],
        })

    prompt = f"""Classify each concept below using these taxonomy axes.

For each concept ID, return:
- **structural_category**: state-boundary | signal-integrity | compound-failure | mechanism-policy | affordance-capacity | process-workflow | data-pipeline | testing-verification
- **trigger_phase**: system-design | code-review | debugging | policy-governance | implementation
- **primary_actor**: individual-contributor | reviewer | architect | system-prompter
- **problem_nature**: state-lifecycle | calibration-metric | dependency-sequencing | cognitive-framing | interface-contract | data-integrity
- **agent_dynamic**: convergence | synthesis | reframing
- **tags**: 3-5 searchable keywords as array
- **one_liner**: One plain-English sentence summarizing the concept

Definitions:
- structural_category: What structural problem does this solve?
  - state-boundary: Rules about how systems remember, forget, and isolate data across time/tasks
  - signal-integrity: Separating causation from correlation, ensuring detectors measure reality
  - compound-failure: How distinct systems collide to create unpredicted failure modes
  - mechanism-policy: Rules governing thresholds, severity, economic incentives, automated consequences
  - affordance-capacity: Whether the user/agent has the tools and context to execute a required action
  - process-workflow: How work is sequenced, triaged, or organized
  - data-pipeline: How data flows, transforms, and is validated through a system
  - testing-verification: How correctness is established and maintained

- trigger_phase: When in the SDLC does this apply?
- primary_actor: Who needs this insight most?
- problem_nature: What root cause does this address?
  - state-lifecycle: State not properly managed across boundaries
  - calibration-metric: Measurement or threshold is wrong
  - dependency-sequencing: Order of operations matters
  - cognitive-framing: The debate/analysis is happening at the wrong level
  - interface-contract: Mismatch between what's promised and what's delivered
  - data-integrity: Data is lost, corrupted, or misattributed

- agent_dynamic: How was this concept synthesized in the roundtable?
  - convergence: Multiple agents independently arrived at same conclusion
  - synthesis: Opposing views resolved into new idea
  - reframing: Agent shifted the debate to the right level/dimension

Output as JSON array matching input order:
[{{"id": "nc-xxx", "structural_category": "...", "trigger_phase": "...", "primary_actor": "...", "problem_nature": "...", "agent_dynamic": "...", "tags": ["...", "..."], "one_liner": "..."}}]

CONCEPTS:
{json.dumps(items, indent=2)}"""

    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            ["claude", "-p", "--model", "sonnet",
             "--no-session-persistence", "--output-format", "text",
             "--disable-slash-commands", "--dangerously-skip-permissions",
             "--max-budget-usd", "2.00"],
            input=prompt, capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace", env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            raw = result.stdout.strip()
            json_start = raw.find("[")
            json_end = raw.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(raw[json_start:json_end])
        logger.warning("Classification call failed (exit %d)", result.returncode)
        return []
    except subprocess.TimeoutExpired:
        logger.error("Classification call timed out")
        return []
    except Exception as e:
        logger.error("Classification error: %s", e)
        return []


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Batch-classify novel concepts")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max concepts to classify (0=all)")
    args = parser.parse_args()

    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    unclassified = [c for c in db["concepts"] if _needs_classification(c)]

    if args.limit:
        unclassified = unclassified[:args.limit]

    print(f"Unclassified: {len(unclassified)} / {len(db['concepts'])}")

    if args.dry_run:
        for c in unclassified[:20]:
            print(f"  {c['id']}: {c['title']}")
        if len(unclassified) > 20:
            print(f"  ... and {len(unclassified) - 20} more")
        return

    # Build lookup for fast merge
    concept_map = {c["id"]: c for c in db["concepts"]}

    total_classified = 0
    batches = [unclassified[i:i + BATCH_SIZE] for i in range(0, len(unclassified), BATCH_SIZE)]

    for batch_num, batch in enumerate(batches, 1):
        titles = [c["title"][:50] for c in batch]
        print(f"Batch {batch_num}/{len(batches)} ({len(batch)} concepts)...", flush=True)

        results = _classify_batch(batch)
        if not results:
            print("  FAILED — skipping batch")
            continue

        matched = 0
        for r in results:
            cid = r.get("id", "")
            if cid in concept_map:
                c = concept_map[cid]
                for field in ("structural_category", "trigger_phase", "primary_actor",
                              "problem_nature", "agent_dynamic", "tags", "one_liner"):
                    if r.get(field):
                        c[field] = r[field]
                matched += 1

        total_classified += matched
        print(f"  {matched}/{len(batch)} classified")

    # Save
    db["concepts"] = list(concept_map.values())
    DB_PATH.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone. {total_classified} concepts classified. Saved to {DB_PATH.name}")


if __name__ == "__main__":
    main()
