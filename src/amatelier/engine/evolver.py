"""CLAUDE.md Evolution Engine — rewrites agent instructions from debrief outputs.

Includes behavior decay system: behaviors carry confidence scores that decay
per RT unless confirmed by the Therapist. Fading behaviors are surfaced for
review; expired behaviors are prompted for removal.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

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


DECAY_RATE = 0.05       # confidence lost per RT without confirmation
FADE_THRESHOLD = 0.5    # Therapist gets nudge
EXPIRE_THRESHOLD = 0.3  # marked (fading) in CLAUDE.md
REMOVE_THRESHOLD = 0.0  # Therapist prompted to remove


def _behaviors_path(agent_name: str) -> Path:
    return WRITE_ROOT / "agents" / agent_name / "behaviors.json"


def load_behaviors(agent_name: str) -> list[dict]:
    """Load structured behavior metadata."""
    path = _behaviors_path(agent_name)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_behaviors(agent_name: str, behaviors: list[dict]):
    path = _behaviors_path(agent_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Auto-compute any missing fires_when embeddings so the runner can do
    # semantic selection without calling the embedder on the hot path.
    # Safe on every save — already-embedded rows are skipped.
    _ensure_fires_when_embeddings(behaviors)
    path.write_text(json.dumps(behaviors, indent=2), encoding="utf-8")


def _ensure_fires_when_embeddings(behaviors: list[dict]) -> None:
    """Populate `fires_when_embedding` for any behavior that has `fires_when`
    but no embedding yet. Silent no-op when no embedder is configured.

    Called from save_behaviors. Idempotent.
    """
    try:
        from embeddings import embed_batch
    except ImportError:
        try:
            from .embeddings import embed_batch  # package-relative fallback
        except ImportError:
            return
    pending_idx: list[int] = []
    pending_text: list[str] = []
    for i, b in enumerate(behaviors):
        fw = (b.get("fires_when") or "").strip()
        if not fw:
            continue
        if b.get("fires_when_embedding"):
            continue
        pending_idx.append(i)
        pending_text.append(fw)
    if not pending_text:
        return
    vectors = embed_batch(pending_text)
    for pos, idx in enumerate(pending_idx):
        v = vectors[pos] if pos < len(vectors) else None
        if v is not None:
            behaviors[idx]["fires_when_embedding"] = v


def _find_behavior(behaviors: list[dict], text: str) -> dict | None:
    """Find a behavior by fuzzy text match."""
    text_lower = text.lower().strip()
    for b in behaviors:
        if text_lower in b.get("text", "").lower() or b.get("text", "").lower() in text_lower:
            return b
    # Word overlap fallback
    text_words = set(text_lower.split())
    for b in behaviors:
        b_words = set(b.get("text", "").lower().split())
        if text_words and b_words:
            overlap = len(text_words & b_words) / len(text_words | b_words)
            if overlap > 0.6:
                return b
    return None


def confirm_behavior(agent_name: str, behavior_text: str, rt_id: str = "") -> bool:
    """Confirm a behavior was useful — resets confidence to 1.0."""
    behaviors = load_behaviors(agent_name)
    match = _find_behavior(behaviors, behavior_text)
    if match:
        match["confidence"] = 1.0
        match["last_confirmed_rt"] = rt_id
        match["last_confirmed_at"] = time.time()
        save_behaviors(agent_name, behaviors)
        logger.info("Confirmed behavior for %s (conf=1.0): %s", agent_name, behavior_text[:60])
        return True
    return False


def decay_behaviors(agent_name: str, rt_id: str = "") -> dict:
    """Apply decay to all behaviors for one RT cycle.

    Returns {"fading": [...], "expired": [...], "healthy": int} for Therapist injection.
    """
    behaviors = load_behaviors(agent_name)
    if not behaviors:
        return {"fading": [], "expired": [], "healthy": 0}

    fading = []
    expired = []
    healthy = 0

    for b in behaviors:
        # Skip if just confirmed this RT
        if b.get("last_confirmed_rt") == rt_id:
            healthy += 1
            continue

        old_conf = b.get("confidence", 1.0)
        new_conf = max(0.0, old_conf - DECAY_RATE)
        b["confidence"] = round(new_conf, 2)

        if new_conf <= REMOVE_THRESHOLD:
            expired.append(b["text"])
        elif new_conf <= FADE_THRESHOLD:
            fading.append({"text": b["text"], "confidence": new_conf})
        else:
            healthy += 1

    save_behaviors(agent_name, behaviors)

    # Update CLAUDE.md to reflect fading markers
    _sync_fading_markers(agent_name, behaviors)

    if fading:
        logger.info("Decay: %s has %d fading behaviors", agent_name, len(fading))
    if expired:
        logger.info("Decay: %s has %d expired behaviors for removal", agent_name, len(expired))

    return {"fading": fading, "expired": expired, "healthy": healthy}


def _sync_fading_markers(agent_name: str, behaviors: list[dict]):
    """Update CLAUDE.md behavior lines with (fading) markers based on confidence."""
    content = read_claude_md(agent_name)
    if "## Learned Behaviors" not in content:
        return

    idx = content.index("## Learned Behaviors")
    end_idx = content.find("\n## ", idx + 1)
    if end_idx == -1:
        end_idx = len(content)
    section = content[idx:end_idx]

    lines = section.split("\n")
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            # Remove existing markers
            clean = stripped.replace(" (fading)", "").replace(" (expired)", "")
            # Find matching behavior
            match = _find_behavior(behaviors, clean[2:])
            if match:
                conf = match.get("confidence", 1.0)
                if conf <= REMOVE_THRESHOLD:
                    clean += " (expired)"
                elif conf <= EXPIRE_THRESHOLD:
                    clean += " (fading)"
            new_lines.append(f"  {clean}" if line.startswith("  ") else clean)
        else:
            new_lines.append(line)

    new_section = "\n".join(new_lines)
    content = content[:idx] + new_section + content[end_idx:]
    write_claude_md(agent_name, content)


def get_behavior_decay_summary(agent_name: str) -> str:
    """Build a summary string for Therapist injection."""
    behaviors = load_behaviors(agent_name)
    if not behaviors:
        return ""

    lines = []
    fading = [b for b in behaviors if b.get("confidence", 1.0) <= FADE_THRESHOLD]
    expired = [b for b in behaviors if b.get("confidence", 1.0) <= REMOVE_THRESHOLD]

    if expired:
        lines.append(f"EXPIRED BEHAVIORS ({len(expired)} — recommend removal):")
        for b in expired:
            lines.append(f"  - {b['text'][:80]} (conf={b.get('confidence', 0):.2f})")

    if fading:
        non_expired_fading = [b for b in fading if b.get("confidence", 1.0) > REMOVE_THRESHOLD]
        if non_expired_fading:
            lines.append(f"FADING BEHAVIORS ({len(non_expired_fading)} — not confirmed recently):")
            for b in non_expired_fading:
                lines.append(f"  - {b['text'][:80]} (conf={b.get('confidence', 0):.2f})")

    if lines:
        lines.insert(0, "\n--- BEHAVIOR HEALTH ---")
        lines.append("If a behavior is expired, consider removing it. If fading, confirm it if still valuable or let it continue to decay.")
    return "\n".join(lines)


def read_claude_md(agent_name: str) -> str:
    path = WRITE_ROOT / "agents" / agent_name / "CLAUDE.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_claude_md(agent_name: str, content: str):
    path = WRITE_ROOT / "agents" / agent_name / "CLAUDE.md"
    # Backup before overwriting
    backup_dir = WRITE_ROOT / "agents" / agent_name / "sessions"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"CLAUDE_backup_{time.strftime('%Y%m%d_%H%M%S')}.md"
    if path.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(content, encoding="utf-8")
    logger.info("Updated CLAUDE.md for %s (backup: %s)", agent_name, backup.name)



def append_to_memory(agent_name: str, entry: str):
    """Dual-write: structured MEMORY.json (primary) + legacy MEMORY.md (backup)."""
    # Primary: structured memory system
    try:
        from agent_memory import add_session_summary
        add_session_summary(agent_name, "", entry[:300])
        logger.info("Written to structured memory for %s", agent_name)
    except ImportError:
        pass  # Fall through to legacy

    # Legacy backup: append to MEMORY.md
    path = WRITE_ROOT / "agents" / agent_name / "MEMORY.md"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    date = time.strftime("%Y-%m-%d")
    updated = current.rstrip() + f"\n\n## {date}\n{entry}\n"
    path.write_text(updated, encoding="utf-8")
    logger.info("Appended to MEMORY.md for %s", agent_name)


def _behavior_is_duplicate(existing_section: str, new_behavior: str) -> bool:
    """Check if new_behavior overlaps >70% with any existing behavior (word-set)."""
    new_words = set(new_behavior.lower().split())
    if not new_words:
        return False
    for line in existing_section.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            existing_words = set(line[2:].lower().split())
            if existing_words:
                overlap = len(new_words & existing_words) / len(new_words | existing_words)
                if overlap > 0.7:
                    return True
    return False


def add_learned_behavior(
    agent_name: str,
    behavior: str,
    rt_id: str = "",
    fires_when: str = "",
):
    """Add a learned behavior to CLAUDE.md + behaviors.json.

    Skips duplicates (>70% word overlap on behavior text).

    `fires_when` is optional prose describing briefing contexts where this
    behavior applies — authored by the therapist at add time. When present,
    save_behaviors() auto-computes its embedding so the runner can semantically
    match it to a briefing at RT spawn. Old callers without fires_when continue
    to work; those behaviors will be selected by confidence-only fallback.
    """
    content = read_claude_md(agent_name)
    # S3: fuzzy-match dedup gate
    if "## Learned Behaviors" in content:
        idx = content.index("## Learned Behaviors")
        end_idx = content.find("\n## ", idx + 1)
        section = content[idx:end_idx] if end_idx != -1 else content[idx:]
        if _behavior_is_duplicate(section, behavior):
            logger.info("Skipping duplicate behavior for %s: %s", agent_name, behavior[:60])
            return

    if "## Learned Behaviors" in content:
        # Append to existing section
        idx = content.index("## Learned Behaviors")
        end_idx = content.find("\n## ", idx + 1)
        if end_idx == -1:
            end_idx = len(content)
        section = content[idx:end_idx]
        updated_section = section.rstrip() + f"\n- {behavior}\n"
        content = content[:idx] + updated_section + content[end_idx:]
    else:
        content = content.rstrip() + f"\n\n## Learned Behaviors\n- {behavior}\n"
    write_claude_md(agent_name, content)

    # Write to structured behaviors.json
    behaviors = load_behaviors(agent_name)
    entry: dict = {
        "text": behavior,
        "confidence": 1.0,
        "added_at": time.time(),
        "added_rt": rt_id,
        "last_confirmed_rt": rt_id,
        "last_confirmed_at": time.time(),
    }
    if fires_when and fires_when.strip():
        entry["fires_when"] = fires_when.strip()
        # fires_when_embedding populated by save_behaviors below.
    behaviors.append(entry)
    save_behaviors(agent_name, behaviors)
    logger.info("Added learned behavior to %s: %s", agent_name, behavior[:60])


def remove_learned_behavior(agent_name: str, behavior_fragment: str) -> bool:
    """Remove a learned behavior from CLAUDE.md + behaviors.json by fuzzy match.

    Matches if the fragment appears (case-insensitive) in any behavior line.
    Returns True if a behavior was removed, False if no match found.
    """
    content = read_claude_md(agent_name)
    if "## Learned Behaviors" not in content:
        logger.warning("No Learned Behaviors section for %s", agent_name)
        return False

    idx = content.index("## Learned Behaviors")
    end_idx = content.find("\n## ", idx + 1)
    if end_idx == -1:
        end_idx = len(content)
    section = content[idx:end_idx]

    lines = section.split("\n")
    fragment_lower = behavior_fragment.lower().strip()
    new_lines = []
    removed = False
    for line in lines:
        if line.strip().startswith("- ") and fragment_lower in line.lower():
            logger.info("Removing behavior from %s: %s", agent_name, line.strip()[:80])
            removed = True
        else:
            new_lines.append(line)

    if removed:
        new_section = "\n".join(new_lines)
        content = content[:idx] + new_section + content[end_idx:]
        write_claude_md(agent_name, content)

        # Also remove from behaviors.json
        behaviors = load_behaviors(agent_name)
        behaviors = [b for b in behaviors if fragment_lower not in b.get("text", "").lower()]
        save_behaviors(agent_name, behaviors)

    return removed


def update_emerging_trait(agent_name: str, trait: str):
    """Update the Emerging Traits section in an agent's CLAUDE.md.

    Traits accumulate — the Therapist observes patterns across roundtables
    and proposes them here. These form the agent's emerging persona.
    """
    content = read_claude_md(agent_name)
    if "## Emerging Traits" not in content:
        content = content.rstrip() + f"\n\n## Emerging Traits\n- {trait}\n"
        write_claude_md(agent_name, content)
        logger.info("Created Emerging Traits for %s: %s", agent_name, trait[:60])
        return

    idx = content.index("## Emerging Traits")
    end_idx = content.find("\n## ", idx + 1)
    if end_idx == -1:
        end_idx = len(content)
    section = content[idx:end_idx]

    # Replace "None yet" placeholder if present
    if "None yet" in section or "none yet" in section.lower():
        new_section = f"## Emerging Traits\n- {trait}\n"
    else:
        # Check for duplicate (don't add the same trait twice)
        if trait.lower().strip() in section.lower():
            logger.info("Trait already exists for %s, skipping: %s", agent_name, trait[:60])
            return
        new_section = section.rstrip() + f"\n- {trait}\n"

    content = content[:idx] + new_section + content[end_idx:]
    write_claude_md(agent_name, content)
    logger.info("Updated Emerging Traits for %s: %s", agent_name, trait[:60])


def sync_skills_owned(agent_name: str):
    """Update the ## Skills Owned section in an agent's CLAUDE.md from the ledger.

    Called after purchases and at RT start so agents always know what they have.
    Permanent skills persist. Consumed boosts are excluded.
    """
    try:
        from store import get_owned_skills
    except ImportError:
        logger.error("Cannot import store module for skills sync")
        return

    skills = get_owned_skills(agent_name)
    content = read_claude_md(agent_name)
    if not content:
        logger.warning("No CLAUDE.md for %s — skipping skills sync", agent_name)
        return

    # Build the new section
    if skills:
        lines = ["## Skills Owned"]
        for s in skills:
            lines.append(f"- **{s['name']}** (acquired {s['date']})")
        new_section = "\n".join(lines) + "\n"
    else:
        new_section = "## Skills Owned\nNone yet.\n"

    # Replace existing section or insert before Learned Behaviors
    if "## Skills Owned" in content:
        idx = content.index("## Skills Owned")
        end_idx = content.find("\n## ", idx + 1)
        if end_idx == -1:
            end_idx = len(content)
        content = content[:idx] + new_section + content[end_idx:]
    elif "## Learned Behaviors" in content:
        idx = content.index("## Learned Behaviors")
        content = content[:idx] + new_section + "\n" + content[idx:]
    elif "## Emerging Traits" in content:
        idx = content.index("## Emerging Traits")
        content = content[:idx] + new_section + "\n" + content[idx:]
    else:
        content = content.rstrip() + "\n\n" + new_section

    write_claude_md(agent_name, content)
    logger.info("Synced Skills Owned for %s: %d skills", agent_name, len(skills))


# ── traits.json persistence + CLAUDE.md render ──────────────────────────────


def _traits_path(agent_name: str) -> Path:
    return WRITE_ROOT / "agents" / agent_name / "traits.json"


def _load_traits(agent_name: str) -> dict:
    path = _traits_path(agent_name)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "agent": agent_name,
        "schema_version": 1,
        "updated_at": "",
        "confirmed": [],
        "candidate": [],
        "rejected": [],
        "history": [],
    }


def _save_traits(agent_name: str, data: dict) -> None:
    path = _traits_path(agent_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _observation_rt_ids(agent_name: str) -> set[str]:
    obs_dir = WRITE_ROOT / "agents" / agent_name / "observations"
    if not obs_dir.exists():
        return set()
    ids: set[str] = set()
    for p in obs_dir.glob("obs-*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            rid = d.get("rt_id")
            if rid:
                ids.add(str(rid))
        except Exception:
            continue
    return ids


def apply_trait_action(agent_name: str, trait_eval: dict, rt_id: str = "") -> dict:
    """Evidence-gated trait writer.

    Evaluates the therapist's TRAIT_EVALUATION verdict against the evidence
    gate and writes the result to traits.json. Also resets the
    obs_since_last_trait_review counter in case_notes and rebuilds the
    CLAUDE.md Emerging Traits section from the new traits.json state.

    CONFIRM gate: verdict "confirm" + >=3 matched rt_ids + >=2 signal types.
    CANDIDATE gate: verdict "candidate" + >=1 matched rt + >=1 signal.
    """
    trait_eval = trait_eval or {}
    verdict = (trait_eval.get("verdict") or "").lower()
    label = (trait_eval.get("label") or "").strip()
    rationale = (trait_eval.get("rationale") or "").strip()
    evidence_rts = [str(x).strip() for x in (trait_eval.get("evidence_rts") or []) if str(x).strip()]
    signals = trait_eval.get("converging_signals") or {}
    signal_types = [k for k, v in signals.items() if v and str(v).strip()]

    if not label:
        _reset_trait_counter(agent_name, rt_id)
        return {"accepted": False, "action": "rejected", "reason": "missing label"}

    obs_ids = _observation_rt_ids(agent_name)
    matched = [r for r in evidence_rts if r in obs_ids]

    data = _load_traits(agent_name)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    entry_base = {
        "label": label,
        "rationale": rationale,
        "evidence_rts": evidence_rts,
        "matched_rts": matched,
        "converging_signals": signals,
        "rt_id": rt_id,
        "timestamp": now,
    }

    if verdict == "confirm":
        if len(matched) < 3:
            data.setdefault("history", []).append({
                "action": "rejected_bad_evidence",
                "label": label, "rt_id": rt_id, "timestamp": now,
                "reason": f"need >=3 matched RTs, got {len(matched)}/{len(evidence_rts)}",
            })
            _save_traits(agent_name, data)
            _render_traits_section(agent_name, data)
            _reset_trait_counter(agent_name, rt_id)
            return {"accepted": False, "action": "rejected_bad_evidence",
                    "reason": f"only {len(matched)} RTs matched observations"}
        if len(signal_types) < 2:
            data.setdefault("history", []).append({
                "action": "rejected_bad_evidence",
                "label": label, "rt_id": rt_id, "timestamp": now,
                "reason": f"need >=2 signal types, got {len(signal_types)}",
            })
            _save_traits(agent_name, data)
            _render_traits_section(agent_name, data)
            _reset_trait_counter(agent_name, rt_id)
            return {"accepted": False, "action": "rejected_bad_evidence",
                    "reason": f"only {len(signal_types)} signal types"}

        confirmed = data.setdefault("confirmed", [])
        if any(c.get("label", "").lower() == label.lower() for c in confirmed):
            for c in confirmed:
                if c.get("label", "").lower() == label.lower():
                    c.update(entry_base)
                    c["confirmed_at"] = c.get("confirmed_at") or now
                    break
            data.setdefault("history", []).append({
                "action": "re_confirmed", "label": label, "rt_id": rt_id, "timestamp": now,
            })
        else:
            entry = dict(entry_base)
            entry["confirmed_at"] = now
            confirmed.append(entry)
            data["candidate"] = [c for c in data.get("candidate", [])
                                 if c.get("label", "").lower() != label.lower()]
            data.setdefault("history", []).append({
                "action": "confirmed", "label": label, "rt_id": rt_id, "timestamp": now,
            })

        _save_traits(agent_name, data)
        _render_traits_section(agent_name, data)
        _reset_trait_counter(agent_name, rt_id)
        return {"accepted": True, "action": "confirmed",
                "reason": f"{len(matched)} RTs, {len(signal_types)} signal types"}

    if verdict == "candidate":
        if not matched or not signal_types:
            data.setdefault("history", []).append({
                "action": "rejected_bad_evidence",
                "label": label, "rt_id": rt_id, "timestamp": now,
                "reason": "candidate needs >=1 matched RT and >=1 signal",
            })
            _save_traits(agent_name, data)
            _reset_trait_counter(agent_name, rt_id)
            return {"accepted": False, "action": "rejected_bad_evidence",
                    "reason": "candidate lacks evidence"}

        candidate = data.setdefault("candidate", [])
        found = False
        for c in candidate:
            if c.get("label", "").lower() == label.lower():
                c.update(entry_base)
                c["why_candidate"] = rationale or c.get("why_candidate", "")
                found = True
                break
        if not found:
            entry = dict(entry_base)
            entry["why_candidate"] = rationale
            candidate.append(entry)
        data.setdefault("history", []).append({
            "action": "candidate", "label": label, "rt_id": rt_id, "timestamp": now,
        })
        _save_traits(agent_name, data)
        _render_traits_section(agent_name, data)
        _reset_trait_counter(agent_name, rt_id)
        return {"accepted": True, "action": "candidate",
                "reason": f"{len(matched)} RTs, {len(signal_types)} signal types"}

    _reset_trait_counter(agent_name, rt_id)
    return {"accepted": False, "action": "rejected",
            "reason": f"unknown verdict {verdict!r}"}


def _reset_trait_counter(agent_name: str, rt_id: str) -> None:
    """Reset obs_since_last_trait_review to 0 in case_notes."""
    path = WRITE_ROOT / "agents" / "therapist" / "case_notes" / f"{agent_name}.json"
    if not path.exists():
        return
    try:
        notes = json.loads(path.read_text(encoding="utf-8"))
        notes["obs_since_last_trait_review"] = 0
        if rt_id:
            notes["last_trait_review_rt"] = rt_id
        path.write_text(json.dumps(notes, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to reset trait counter for %s: %s", agent_name, e)


def _render_traits_section(agent_name: str, data: dict | None = None) -> None:
    """Deterministically rebuild the ## Emerging Traits section in CLAUDE.md
    from traits.json. Only writer of this section.
    """
    if data is None:
        data = _load_traits(agent_name)

    lines = ["## Emerging Traits"]
    confirmed = data.get("confirmed") or []
    candidate = data.get("candidate") or []
    if not confirmed and not candidate:
        lines.append("None yet.")
    if confirmed:
        lines.append("")
        lines.append("**Confirmed** (evidence-gated):")
        for t in confirmed:
            label = t.get("label", "?")
            rationale = t.get("rationale", "")
            n_rts = len(t.get("matched_rts") or t.get("evidence_rts") or [])
            if rationale:
                lines.append(f"- **{label}** — {rationale} ({n_rts} RTs)")
            else:
                lines.append(f"- **{label}** ({n_rts} RTs)")
    if candidate:
        lines.append("")
        lines.append("**Candidate** (needs more data):")
        for t in candidate:
            label = t.get("label", "?")
            why = t.get("why_candidate", "")
            if why:
                lines.append(f"- {label} — {why}")
            else:
                lines.append(f"- {label}")
    new_section = "\n".join(lines) + "\n"

    content = read_claude_md(agent_name)
    if not content:
        logger.warning("No CLAUDE.md for %s — cannot render traits", agent_name)
        return

    if "## Emerging Traits" in content:
        idx = content.index("## Emerging Traits")
        end_idx = content.find("\n## ", idx + 1)
        if end_idx == -1:
            end_idx = len(content)
        content = content[:idx] + new_section + content[end_idx:]
    else:
        content = content.rstrip() + "\n\n" + new_section

    write_claude_md(agent_name, content)
    logger.info("Rendered Emerging Traits for %s (confirmed=%d, candidate=%d)",
                agent_name, len(confirmed), len(candidate))


def render_traits_section(agent_name: str) -> None:
    _render_traits_section(agent_name)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Claude Suite CLAUDE.md Evolution Engine")
    sub = parser.add_subparsers(dest="command")

    p_read = sub.add_parser("read", help="Read an agent's CLAUDE.md")
    p_read.add_argument("agent", help="Agent name")

    p_memory = sub.add_parser("memory", help="Append to an agent's MEMORY.md")
    p_memory.add_argument("agent", help="Agent name")
    p_memory.add_argument("entry", help="Text to append")

    p_behavior = sub.add_parser("behavior", help="Add a learned behavior to CLAUDE.md")
    p_behavior.add_argument("agent", help="Agent name")
    p_behavior.add_argument("text", help="Behavior description")
    p_behavior.add_argument("--fires-when", default="",
                            help="Prose describing briefing contexts where this behavior applies. "
                                 "Used for semantic selection at RT spawn (optional).")
    p_behavior.add_argument("--rt", default="", help="RT id (for provenance)")

    p_remove = sub.add_parser("remove-behavior", help="Remove a learned behavior from CLAUDE.md")
    p_remove.add_argument("agent", help="Agent name")
    p_remove.add_argument("fragment", help="Text fragment to match (case-insensitive)")

    p_trait = sub.add_parser("trait", help="Update Emerging Traits in CLAUDE.md")
    p_trait.add_argument("agent", help="Agent name")
    p_trait.add_argument("text", help="Trait description")

    p_sync = sub.add_parser("sync-skills", help="Sync Skills Owned section from ledger")
    p_sync.add_argument("agent", help="Agent name")

    p_sync_all = sub.add_parser("sync-all-skills", help="Sync Skills Owned for all agents")

    p_confirm = sub.add_parser("confirm-behavior", help="Confirm a behavior was useful (resets confidence)")
    p_confirm.add_argument("agent", help="Agent name")
    p_confirm.add_argument("text", help="Behavior text or fragment")
    p_confirm.add_argument("--rt", default="", help="Roundtable ID")

    p_decay = sub.add_parser("decay", help="Apply one RT cycle of behavior decay")
    p_decay.add_argument("agent", help="Agent name")
    p_decay.add_argument("--rt", default="", help="Roundtable ID")

    p_decay_all = sub.add_parser("decay-all", help="Apply behavior decay for all agents")
    p_decay_all.add_argument("--rt", default="", help="Roundtable ID")

    p_health = sub.add_parser("behavior-health", help="Show behavior decay summary")
    p_health.add_argument("agent", help="Agent name")

    args = parser.parse_args()

    if args.command == "read":
        content = read_claude_md(args.agent)
        print(content)
    elif args.command == "memory":
        append_to_memory(args.agent, args.entry)
        print(json.dumps({"appended": True, "agent": args.agent}))
    elif args.command == "remove-behavior":
        result = remove_learned_behavior(args.agent, args.fragment)
        print(json.dumps({"removed": result, "agent": args.agent, "fragment": args.fragment[:60]}))
    elif args.command == "trait":
        update_emerging_trait(args.agent, args.text)
        print(json.dumps({"updated": True, "agent": args.agent, "trait": args.text[:60]}))
    elif args.command == "behavior":
        add_learned_behavior(
            args.agent,
            args.text,
            rt_id=getattr(args, "rt", ""),
            fires_when=getattr(args, "fires_when", ""),
        )
        print(json.dumps({
            "added": True,
            "agent": args.agent,
            "behavior": args.text[:60],
            "has_fires_when": bool(getattr(args, "fires_when", "")),
        }))
    elif args.command == "sync-skills":
        sync_skills_owned(args.agent)
        print(json.dumps({"synced": True, "agent": args.agent}))
    elif args.command == "sync-all-skills":
        from amatelier import worker_registry
        all_agents = worker_registry.list_workers()
        for a in all_agents:
            sync_skills_owned(a)
        print(json.dumps({"synced": True, "agents": all_agents}))
    elif args.command == "confirm-behavior":
        result = confirm_behavior(args.agent, args.text, args.rt)
        print(json.dumps({"confirmed": result, "agent": args.agent}))
    elif args.command == "decay":
        result = decay_behaviors(args.agent, args.rt)
        print(json.dumps(result))
    elif args.command == "decay-all":
        from amatelier import worker_registry
        all_agents = worker_registry.list_workers()
        results = {}
        for a in all_agents:
            results[a] = decay_behaviors(a, args.rt)
        print(json.dumps(results, indent=2))
    elif args.command == "behavior-health":
        summary = get_behavior_decay_summary(args.agent)
        print(summary if summary else "(no behaviors tracked)")
    else:
        parser.print_help()
