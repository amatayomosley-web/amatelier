"""Skill Distillation — CAPTURE/FIX/DERIVE extraction from roundtable transcripts."""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

SUITE_ROOT = Path(__file__).resolve().parent.parent
SHARED_SKILLS_DIR = SUITE_ROOT / "shared-skills" / "entries"
INDEX_PATH = SUITE_ROOT / "shared-skills" / "index.json"


def load_index() -> list[dict]:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return []


def save_index(index: list[dict]):
    INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")


def _judge_gate(title: str, pattern: str) -> str | None:
    """Rule-based quality gate — returns rejection reason or None if pass.

    S3 Stage 2: min 15 words, imperative verb, concrete code reference. No LLM call.
    """
    import re
    words = (title + " " + pattern).split()
    if len(words) < 15:
        return f"too short ({len(words)} words, need 15+)"
    imperative_verbs = {"use", "apply", "check", "add", "avoid", "ensure", "validate",
                        "prefer", "replace", "scan", "flag", "track", "detect", "call",
                        "run", "test", "skip", "merge", "split", "wrap", "inject"}
    first_words = {w.lower().rstrip(".,;:") for w in words[:5]}
    if not first_words & imperative_verbs:
        return "no imperative verb in first 5 words"
    code_refs = re.findall(r'`[^`]+`|[a-z_]+\.[a-z_]+\(|[A-Z][a-z]+[A-Z]', title + " " + pattern)
    if not code_refs:
        return "no concrete code reference"
    return None


def create_skill_entry(
    skill_type: str,
    title: str,
    context: str,
    pattern: str,
    when_to_apply: str,
    source_roundtable: str = "",
    source_agent: str = "",
) -> dict | None:
    """Create a structured skill entry. Returns None if duplicate or fails JUDGE gate.

    S3 Stage 1: RETRIEVE guard — check for duplicates before creating.
    S3 Stage 2: JUDGE gate — quality check (min words, imperative verb, code ref).
    """
    # S3 JUDGE gate
    rejection = _judge_gate(title, pattern)
    if rejection:
        logger.info("JUDGE gate rejected skill '%s': %s", title[:50], rejection)
        return None

    # S3 RETRIEVE guard — check for duplicates
    existing = search_shared_skills(title, limit=3)
    for match in existing:
        match_text = f"{match['title']} {match.get('context', '')}".lower()
        title_words = set(title.lower().split())
        match_words = set(match_text.split())
        if title_words and match_words:
            overlap = len(title_words & match_words) / len(title_words | match_words)
            if overlap > 0.6:
                # Duplicate found — increment recurrence_count instead
                match["recurrence_count"] = match.get("recurrence_count", match.get("uses", 0)) + 1
                _update_index_entry(match["id"], {"recurrence_count": match["recurrence_count"]})
                logger.info("Duplicate skill '%s' matched '%s' (overlap=%.2f) — recurrence_count=%d",
                            title[:40], match["title"][:40], overlap, match["recurrence_count"])
                return None

    skill_id = f"{skill_type.lower()}-{uuid.uuid4().hex[:8]}"
    entry = {
        "id": skill_id,
        "type": skill_type,  # CAPTURE, FIX, DERIVE
        "title": title,
        "context": context,
        "pattern": pattern,
        "when_to_apply": when_to_apply,
        "source_roundtable": source_roundtable,
        "source_agent": source_agent,
        "created_at": time.time(),
        "created_at_rt": source_roundtable,
        "recurrence_count": 0,
    }
    return entry


def _update_index_entry(skill_id: str, updates: dict):
    """Update fields on an existing index entry."""
    index = load_index()
    for entry in index:
        if entry["id"] == skill_id:
            entry.update(updates)
            break
    save_index(index)


def save_skill_to_agent(agent_name: str, entry: dict):
    """Save a skill to an agent's local skills directory."""
    skills_dir = SUITE_ROOT / "agents" / agent_name / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    path = skills_dir / f"{entry['id']}.md"

    md = f"""# {entry['title']}
- **Type**: {entry['type']}
- **Context**: {entry['context']}
- **Source**: {entry['source_roundtable']} ({entry['source_agent']})

## Pattern
{entry['pattern']}

## When to Apply
{entry['when_to_apply']}
"""
    path.write_text(md, encoding="utf-8")
    logger.info("Saved skill %s to %s", entry["id"], agent_name)


def promote_to_shared(entry: dict):
    """Promote a skill to the shared skill store."""
    SHARED_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    path = SHARED_SKILLS_DIR / f"{entry['id']}.md"

    md = f"""# {entry['title']}
- **Type**: {entry['type']}
- **Context**: {entry['context']}
- **Source**: {entry['source_roundtable']} ({entry['source_agent']})
- **Uses**: {entry['uses']}

## Pattern
{entry['pattern']}

## When to Apply
{entry['when_to_apply']}
"""
    path.write_text(md, encoding="utf-8")

    # Update index
    index = load_index()
    index.append({
        "id": entry["id"],
        "type": entry["type"],
        "title": entry["title"],
        "context": entry["context"],
        "uses": entry["uses"],
    })
    save_index(index)
    logger.info("Promoted skill %s to shared store", entry["id"])


def search_shared_skills(query: str, limit: int = 5) -> list[dict]:
    """Simple keyword search against shared skill index."""
    index = load_index()
    query_lower = query.lower()
    scored = []
    for entry in index:
        text = f"{entry['title']} {entry['context']}".lower()
        score = sum(1 for word in query_lower.split() if word in text)
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]


def list_agent_skills(agent_name: str) -> list[str]:
    """List all skills an agent has accumulated."""
    skills_dir = SUITE_ROOT / "agents" / agent_name / "skills"
    if not skills_dir.exists():
        return []
    return [f.stem for f in skills_dir.glob("*.md")]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Claude Suite Skill Distiller")
    sub = parser.add_subparsers(dest="command")

    p_create = sub.add_parser("create", help="Create a skill entry for an agent")
    p_create.add_argument("agent", help="Agent name")
    p_create.add_argument("type", choices=["CAPTURE", "FIX", "DERIVE"], help="Skill type")
    p_create.add_argument("title", help="Skill title")
    p_create.add_argument("--context", default="", help="Context description")
    p_create.add_argument("--pattern", default="", help="Pattern description")
    p_create.add_argument("--when", default="", help="When to apply")
    p_create.add_argument("--rt", default="", help="Source roundtable ID")

    p_promote = sub.add_parser("promote", help="Promote a skill to shared store")
    p_promote.add_argument("agent", help="Agent name")
    p_promote.add_argument("skill_id", help="Skill ID to promote")

    p_list = sub.add_parser("list", help="List agent's skills")
    p_list.add_argument("agent", help="Agent name")

    p_search = sub.add_parser("search", help="Search shared skills")
    p_search.add_argument("query", help="Search query")

    args = parser.parse_args()

    if args.command == "create":
        entry = create_skill_entry(
            skill_type=args.type, title=args.title, context=args.context,
            pattern=args.pattern, when_to_apply=args.when,
            source_roundtable=args.rt, source_agent=args.agent,
        )
        save_skill_to_agent(args.agent, entry)
        print(json.dumps({"created": entry["id"], "agent": args.agent}))
    elif args.command == "promote":
        skills = list_agent_skills(args.agent)
        if args.skill_id in skills:
            skill_path = SUITE_ROOT / "agents" / args.agent / "skills" / f"{args.skill_id}.md"
            # Infer original type from skill ID prefix (e.g. "capture-abc123" -> "CAPTURE")
            original_type = "UNKNOWN"
            for prefix in ("capture", "fix", "derive"):
                if args.skill_id.lower().startswith(prefix):
                    original_type = prefix.upper()
                    break
            entry = {"id": args.skill_id, "type": original_type, "title": args.skill_id,
                     "context": "", "uses": 0}
            promote_to_shared(entry)
            print(json.dumps({"promoted": args.skill_id}))
        else:
            print(json.dumps({"error": f"Skill {args.skill_id} not found for {args.agent}"}))
            sys.exit(1)
    elif args.command == "list":
        skills = list_agent_skills(args.agent)
        print(json.dumps({"agent": args.agent, "skills": skills}))
    elif args.command == "search":
        results = search_shared_skills(args.query)
        print(json.dumps(results, indent=2))
    else:
        parser.print_help()
