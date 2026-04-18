"""Backfill distillation — run the skill distiller on all digests missing skills.

Usage:
    python engine/backfill_distill.py              # Process all missing
    python engine/backfill_distill.py --limit 10   # Process at most 10
    python engine/backfill_distill.py --dry-run     # Show what would be processed
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distiller import create_skill_entry, save_skill_to_agent, load_index, save_index

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

DIGEST_DIR = WRITE_ROOT / "roundtable-server"


def _valid_agents() -> set[str]:
    """Config-driven set of currently-configured worker names (v0.4.0)."""
    from amatelier import worker_registry
    return set(worker_registry.list_workers())


# Backcompat alias — prefer _valid_agents() for new code.
VALID_AGENTS = _valid_agents()


def _append_novel_concepts(skills: list[dict], rt_id: str, topic: str) -> int:
    """Append DERIVE-type skills to the novel concepts database."""
    derives = [s for s in skills if s.get("type") == "DERIVE"]
    if not derives:
        return 0

    db_path = WRITE_ROOT / "novel_concepts.json"
    if db_path.exists():
        db = json.loads(db_path.read_text(encoding="utf-8"))
    else:
        db = {"version": 1, "count": 0, "domains": {}, "concepts": []}

    existing_ids = {c["id"] for c in db["concepts"]}
    code_kw = {"function", "file", "code", "test", "bug", "fix", "import", "class",
               "method", "refactor", "api", "hook", "detector", "parser", "pipeline",
               "schema", "query", "threshold", "grep", "caller", "dependency", "migration"}
    lit_kw = {"character", "narrator", "scene", "reader", "prose", "chapter", "dialogue"}
    econ_kw = {"spark", "economy", "exploit", "governance", "incentive", "boost", "market"}

    def _classify(title, pattern):
        text = (title + " " + pattern).lower()
        words = set(text.split())
        if words & lit_kw: return "literary"
        if words & econ_kw: return "economic"
        if words & code_kw: return "engineering"
        return "cross-domain"

    added = 0
    for s in derives:
        title = s.get("title", "")
        pattern = s.get("pattern", "")
        content_hash = hashlib.sha256(f"{title}:{pattern[:100]}".encode()).hexdigest()[:12]
        concept_id = f"nc-{content_hash}"
        if concept_id in existing_ids:
            continue
        db["concepts"].append({
            "id": concept_id, "title": title, "domain": _classify(title, pattern),
            "pattern": pattern, "when_to_apply": s.get("when_to_apply", ""),
            "structural_category": s.get("structural_category", ""),
            "trigger_phase": s.get("trigger_phase", ""),
            "primary_actor": s.get("primary_actor", ""),
            "problem_nature": s.get("problem_nature", ""),
            "agent_dynamic": s.get("agent_dynamic", ""),
            "tags": s.get("tags", []),
            "one_liner": s.get("one_liner", ""),
            "source_agent": s.get("agent", ""), "source_rt": rt_id, "source_topic": topic,
        })
        existing_ids.add(concept_id)
        added += 1

    if added:
        db["count"] = len(db["concepts"])
        db["domains"] = {}
        for c in db["concepts"]:
            d = c.get("domain", "cross-domain")
            db["domains"][d] = db["domains"].get(d, 0) + 1
        db_path.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Novel concepts: +%d new (total %d)", added, db["count"])
    return added


def _parse_agent_field(agent_str: str) -> list[str]:
    """Parse agent field which may be 'Marcus', 'elena', or 'Naomi, Clare, Elena'."""
    agents = []
    for part in agent_str.split(","):
        name = part.strip().lower()
        if name in VALID_AGENTS:
            agents.append(name)
    return agents


def _needs_distillation(digest_data: dict) -> bool:
    """Check if a digest needs distillation."""
    skills = digest_data.get("distilled_skills", {})
    if skills and skills.get("skills"):
        return False  # already has skills
    # Check if there are enough messages to distill
    transcript = digest_data.get("transcript", [])
    substantive = [m for m in transcript if m.get("agent") not in ("runner", "system", None)]
    return len(substantive) >= 5


def distill_one(digest_path: Path) -> dict:
    """Run the Sonnet distiller on a single digest. Returns result dict."""
    data = json.loads(digest_path.read_text(encoding="utf-8"))
    rt_id = data.get("roundtable_id", "?")
    topic = data.get("topic", "?")
    transcript = data.get("transcript", [])
    workers = list(set(
        m.get("agent") for m in transcript
        if m.get("agent") not in ("runner", "system", "judge", None)
    ))

    substantive = [m for m in transcript if m.get("agent") in workers or m.get("agent") == "judge"]
    transcript_text = "\n\n".join(
        f"[{m['agent'].upper()}]: {m['message']}" for m in substantive
    )
    if len(transcript_text) > 50000:
        transcript_text = transcript_text[:50000] + "\n\n[TRANSCRIPT TRUNCATED]"

    from amatelier import worker_registry
    worker_names = worker_registry.list_workers()
    worker_list_str = ", ".join(worker_names) if worker_names else "(no workers configured)"
    prompt = f"""Extract concrete, reusable skills from this roundtable transcript.

For each skill, provide:
- **Title**: Short descriptive name
- **Type**: CAPTURE (observed technique), FIX (anti-pattern correction), or DERIVE (synthesized from multiple contributions)
- **Agent**: Who originated it — use the lowercase worker name ({worker_list_str}). For collaborative skills, pick the primary contributor.
- **Pattern**: The specific technique — what was done, with file/line references where available
- **When to Apply**: Concrete conditions where this skill is useful beyond this specific discussion

Rules:
- Only extract skills that are REUSABLE in future discussions/work — skip topic-specific observations
- Each skill must have a filled Pattern and When to Apply — no empty fields
- Cite specific files, functions, or line numbers from the transcript where possible
- Agent field MUST be a single lowercase name from: {worker_list_str}
- Target 10-15 skills. Quality over quantity.

Output as JSON array:
[{{"title": "...", "type": "CAPTURE|FIX|DERIVE", "agent": "<one of the configured workers>", "pattern": "...", "when_to_apply": "..."}}]

TRANSCRIPT:
{transcript_text}"""

    # Obtain raw response via backend (open-mode) or CLI subprocess (claude-code).
    # In claude-code mode, preserve the original subprocess flags (--max-budget-usd,
    # --no-session-persistence, etc). In open mode, delegate through llm_backend.
    raw: str | None = None
    try:
        from amatelier.llm_backend import get_backend
        backend = get_backend()
        if backend.name != "claude-code":
            res = backend.complete(
                system="", prompt=prompt, model="sonnet",
                max_tokens=8000, timeout=180,
                json_mode=True,
            )
            raw = (res.text or "").strip() or None
    except Exception as e:
        logger.debug("Backend unavailable for distill, falling back to CLI: %s", e)

    if raw is None:
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                ["claude", "-p", "--model", "sonnet",
                 "--no-session-persistence", "--output-format", "text",
                 "--disable-slash-commands", "--dangerously-skip-permissions",
                 "--max-budget-usd", "5.00"],
                input=prompt, capture_output=True, text=True, timeout=180,
                encoding="utf-8", errors="replace", env=env,
            )
            if result.returncode == 0 and result.stdout.strip():
                raw = result.stdout.strip()
            else:
                data["distilled_skills"] = {"skills": [], "error": f"exit {result.returncode}"}
                digest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                return {"rt_id": rt_id, "extracted": 0, "saved": 0, "status": f"exit-{result.returncode}"}
        except subprocess.TimeoutExpired:
            data["distilled_skills"] = {"skills": [], "error": "timeout"}
            digest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"rt_id": rt_id, "extracted": 0, "saved": 0, "status": "timeout"}
        except Exception as e:
            logger.error("Distillation error for %s: %s", rt_id, e)
            return {"rt_id": rt_id, "extracted": 0, "saved": 0, "status": f"error: {e}"}

    # raw is guaranteed non-None beyond this point
    try:
        json_start = raw.find("[")
        json_end = raw.rfind("]") + 1
        if json_start < 0 or json_end <= json_start:
            data["distilled_skills"] = {"skills": [], "error": "non-json"}
            digest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"rt_id": rt_id, "extracted": 0, "saved": 0, "status": "non-json"}

        skills = json.loads(raw[json_start:json_end])
        data["distilled_skills"] = {"skills": skills, "count": len(skills), "model": "sonnet"}
        digest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        _append_novel_concepts(skills, rt_id, topic)

        saved = 0
        for skill in skills:
            entry = create_skill_entry(
                skill_type=skill.get("type", "DERIVE"),
                title=skill.get("title", ""),
                context=topic,
                pattern=skill.get("pattern", ""),
                when_to_apply=skill.get("when_to_apply", ""),
                source_roundtable=rt_id,
                source_agent=skill.get("agent", ""),
            )
            if not entry:
                continue
            index = load_index()
            index.append({
                "id": entry["id"],
                "type": entry["type"],
                "title": entry["title"],
                "context": entry.get("context", ""),
                "source_agent": skill.get("agent", ""),
                "recurrence_count": 0,
            })
            save_index(index)
            saved += 1
        return {"rt_id": rt_id, "extracted": len(skills), "saved": saved, "status": "ok"}
    except Exception as e:
        logger.error("Distillation parse error for %s: %s", rt_id, e)
        return {"rt_id": rt_id, "extracted": 0, "saved": 0, "status": f"error: {e}"}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Backfill skill distillation on all digests")
    parser.add_argument("--limit", type=int, default=0, help="Max digests to process (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed")
    parser.add_argument("--oldest-first", action="store_true", help="Process oldest digests first")
    args = parser.parse_args()

    digests = sorted(DIGEST_DIR.glob("digest-*.json"), key=lambda f: f.stat().st_mtime,
                     reverse=not args.oldest_first)

    candidates = []
    for d in digests:
        data = json.loads(d.read_text(encoding="utf-8"))
        if _needs_distillation(data):
            candidates.append(d)

    if args.limit:
        candidates = candidates[:args.limit]

    print(f"Digests to process: {len(candidates)}")

    if args.dry_run:
        for d in candidates:
            data = json.loads(d.read_text(encoding="utf-8"))
            topic = data.get("topic", "?")[:60]
            print(f"  {d.name}: {topic}")
        return

    total_extracted = 0
    total_saved = 0
    for i, d in enumerate(candidates):
        data = json.loads(d.read_text(encoding="utf-8"))
        topic = data.get("topic", "?")[:60]
        print(f"{i+1:3d}/{len(candidates)}: {topic}...", end=" ", flush=True)

        result = distill_one(d)
        total_extracted += result["extracted"]
        total_saved += result["saved"]
        print(f"{result['extracted']} skills, {result['saved']} saved [{result['status']}]")

    print(f"\nDone. {total_extracted} skills extracted, {total_saved} saved to agents across {len(candidates)} digests.")


if __name__ == "__main__":
    main()
