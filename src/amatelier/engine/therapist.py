"""Therapist — interactive post-roundtable development sessions (Opus).

Runs automatically after every roundtable. Conducts 1-on-1 sessions with each
agent: debrief, coaching, store requests, upgrade approvals, behavior updates.

The Therapist (Opus) leads. The agent (their model) responds. 2-3 exchanges
per session. Outcomes are parsed and applied via evolver.py / scorer.py.

Usage (standalone):
    python engine/therapist.py --digest roundtable-server/digest-abc123.json
    python engine/therapist.py --digest roundtable-server/digest-abc123.json --agents <a>,<b>
    python engine/therapist.py --digest roundtable-server/digest-abc123.json --turns 3

Called automatically by roundtable_runner.py after scoring.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("therapist")

SUITE_ROOT = Path(__file__).resolve().parent.parent

# Amatayo Standard dual-layer paths: bundled assets stay in SUITE_ROOT
# (read-only post-install); mutable runtime state goes to WRITE_ROOT.
try:
    from amatelier import paths as _amatelier_paths
    _amatelier_paths.ensure_user_data()
    WRITE_ROOT = _amatelier_paths.user_data_dir()
except Exception:
    WRITE_ROOT = SUITE_ROOT

WORKSPACE_ROOT = SUITE_ROOT.parent.parent.parent
EVOLVER = SUITE_ROOT / "engine" / "evolver.py"
SCORER = SUITE_ROOT / "engine" / "scorer.py"


# ── Case Notes ──────────────────────────────────────────────────────────────

CASE_NOTES_DIR = WRITE_ROOT / "agents" / "therapist" / "case_notes"


def _load_case_notes(agent_name: str) -> dict:
    """Load the Therapist's persistent case notes for an agent."""
    path = CASE_NOTES_DIR / f"{agent_name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "agent": agent_name,
        "sessions_conducted": 0,
        "treatment_plan": "",
        "active_hypotheses": [],
        "clinical_observations": [],
        "intervention_history": [],
        "risk_flags": [],
        "relationship_notes": {},
    }


def _save_case_notes(agent_name: str, notes: dict):
    """Persist the Therapist's case notes."""
    CASE_NOTES_DIR.mkdir(parents=True, exist_ok=True)
    path = CASE_NOTES_DIR / f"{agent_name}.json"
    path.write_text(json.dumps(notes, indent=2), encoding="utf-8")
    logger.info("Case notes updated for %s (session #%d)", agent_name, notes.get("sessions_conducted", 0))


def _format_case_notes(notes: dict) -> str:
    """Format case notes as text for the Therapist's prompt context.

    Structure: Treatment plan first (with verification note), then observations
    and intervention history as supporting context. The AGENT SNAPSHOT in the
    brief above is the computed ground truth — the treatment plan must be
    consistent with it.
    """
    if notes.get("sessions_conducted", 0) == 0:
        return "CASE NOTES: First session with this agent — no prior notes."

    lines = [
        f"CASE NOTES ({notes['sessions_conducted']} prior sessions):",
    ]

    if notes.get("treatment_plan"):
        lines.append(f"\nTREATMENT PLAN (from last session — verify against AGENT SNAPSHOT above):\n  {notes['treatment_plan']}")

    if notes.get("active_hypotheses"):
        lines.append("\nACTIVE HYPOTHESES:")
        for h in notes["active_hypotheses"][-3:]:
            status = h.get("status", "testing")
            lines.append(f"  [{status}] {h.get('hypothesis', '')} (since {h.get('since', '?')})")

    if notes.get("risk_flags"):
        lines.append("\nRISK FLAGS:")
        for rf in notes["risk_flags"]:
            lines.append(f"  - {rf}")

    if notes.get("clinical_observations"):
        lines.append("\nKEY OBSERVATIONS (most recent):")
        for obs in notes["clinical_observations"][-5:]:
            lines.append(f"  [{obs.get('date', '?')}] {obs.get('note', '')}")

    if notes.get("intervention_history"):
        lines.append("\nINTERVENTION HISTORY (recent):")
        for iv in notes["intervention_history"][-5:]:
            outcome = iv.get("outcome", "pending")
            lines.append(f"  [{iv.get('date', '?')}] {iv.get('intervention', '')} -> {outcome}")

    if notes.get("relationship_notes"):
        lines.append("\nRELATIONSHIP MAP:")
        for other_agent, note in notes["relationship_notes"].items():
            lines.append(f"  {other_agent}: {note}")

    return "\n".join(lines)


def _update_case_notes(agent_name: str, notes: dict, conversation: list[dict],
                       outcomes: dict, digest: dict):
    """Update case notes after a session using the conversation and outcomes."""
    date = time.strftime("%Y-%m-%d")
    rt_id = digest.get("roundtable_id", "unknown")

    notes["sessions_conducted"] = notes.get("sessions_conducted", 0) + 1

    # Extract clinical observation from the Therapist's opening (richest assessment)
    therapist_opening = ""
    for msg in conversation:
        if msg["role"] == "therapist":
            therapist_opening = msg["message"]
            break

    # Compress the key observation from the opening (first 300 chars of the assessment)
    if therapist_opening:
        # Find the core observation — usually after SBI and before options
        observation = ""
        for para in therapist_opening.split("\n\n"):
            if any(kw in para.lower() for kw in ["pattern", "trajectory", "notice", "see across",
                                                   "observation", "what i see", "consistent"]):
                observation = para.strip()[:250]
                break
        if not observation:
            # Fallback: take the paragraph after the score table
            paragraphs = [p.strip() for p in therapist_opening.split("\n\n") if len(p.strip()) > 50]
            if len(paragraphs) > 2:
                observation = paragraphs[2][:250]

        if observation:
            notes.setdefault("clinical_observations", []).append({
                "date": date,
                "rt_id": rt_id,
                "note": observation,
            })
            # Keep last 10 observations
            notes["clinical_observations"] = notes["clinical_observations"][-10:]

    # Record intervention (what behavior was added/removed, what was recommended)
    interventions = []
    for b in outcomes.get("add_behaviors", []):
        interventions.append(f"Added behavior: {b[:80]}")
    for b in outcomes.get("remove_behaviors", []):
        interventions.append(f"Removed behavior: {b[:80]}")
    for req in outcomes.get("store_requests", []):
        interventions.append(f"Store: {req[:80]}")
    if outcomes.get("development_focus"):
        interventions.append(f"Focus set: {outcomes['development_focus'][:80]}")
        notes["treatment_plan"] = outcomes["development_focus"]

    if interventions:
        notes.setdefault("intervention_history", []).append({
            "date": date,
            "rt_id": rt_id,
            "intervention": "; ".join(interventions),
            "outcome": "pending",
        })
        # Keep last 10 interventions
        notes["intervention_history"] = notes["intervention_history"][-10:]

    # Extract relationship notes from the conversation (who they mentioned, how)
    agent_msgs = [m["message"] for m in conversation if m["role"] == agent_name]
    from amatelier import worker_registry
    for other in worker_registry.list_workers():
        if other == agent_name:
            continue
        for msg in agent_msgs:
            if other in msg.lower():
                # Agent mentioned another agent — extract the context
                for sentence in msg.split("."):
                    if other in sentence.lower() and len(sentence.strip()) > 20:
                        notes.setdefault("relationship_notes", {})[other] = sentence.strip()[:120]
                        break
                break

    # Score risk flags
    risk_flags = []
    metrics_path = WRITE_ROOT / "agents" / agent_name / "metrics.json"
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            if metrics.get("sparks", 0) < 20:
                risk_flags.append(f"Low sparks ({metrics['sparks']}) — approaching elimination threshold")
            if metrics.get("in_slump"):
                risk_flags.append("Currently in slump — needs confidence recovery")
            rt_net = metrics.get("rt_net_history", [])
            if len(rt_net) >= 3 and all(r.get("net", 0) < 0 for r in rt_net[-3:]):
                risk_flags.append("3 consecutive net-negative RTs — relegation risk")
        except (json.JSONDecodeError, OSError):
            pass
    notes["risk_flags"] = risk_flags

    _save_case_notes(agent_name, notes)


# ── Context Loading ─────────────────────────────────────────────────────────

def _load_therapist_context() -> str:
    """Load the Therapist's CLAUDE.md."""
    path = WRITE_ROOT / "agents" / "therapist" / "CLAUDE.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "You are the Therapist. Coach agents on their development."


def _load_agent_state(agent_name: str) -> dict:
    """Load agent's full state: CLAUDE.md, MEMORY.md, metrics.json."""
    agent_dir = WRITE_ROOT / "agents" / agent_name
    state = {"memory": "", "claude": "", "metrics": {}}

    memory_path = agent_dir / "MEMORY.md"
    if memory_path.exists():
        state["memory"] = memory_path.read_text(encoding="utf-8")

    claude_path = agent_dir / "CLAUDE.md"
    if claude_path.exists():
        state["claude"] = claude_path.read_text(encoding="utf-8")

    metrics_path = agent_dir / "metrics.json"
    if metrics_path.exists():
        try:
            state["metrics"] = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    return state


def _extract_agent_data(digest: dict, agent_name: str) -> str:
    """Build a data packet about an agent's roundtable performance."""
    contributions = []
    for msg in digest.get("transcript", []):
        if msg.get("agent") == agent_name:
            contributions.append(msg["message"])

    # Score — scoring can be a list of dicts or a dict with a "scores" key
    score_str = "No score available"
    scoring_data = digest.get("scoring", [])
    if isinstance(scoring_data, dict):
        scoring_data = scoring_data.get("scores", [])
    for s in scoring_data:
        if isinstance(s, dict) and s.get("agent") == agent_name:
            score_str = (f"Score: {s.get('score', '?')}/12 "
                         f"(Novelty={s.get('novelty', '?')} Accuracy={s.get('accuracy', '?')} "
                         f"Impact={s.get('impact', s.get('net_impact', s.get('influence', '?')))} Challenge={s.get('challenge', '?')})")
            break

    # Budget
    budget_str = "No budget data"
    usage = digest.get("budget_usage", {}).get(agent_name, {})
    if usage:
        budget_str = f"Budget: spent {usage.get('spent', 0)}/{usage.get('starting_budget', '?')} extra turns"

    # Judge redirects aimed at this agent
    redirects = []
    for msg in digest.get("transcript", []):
        if msg.get("agent") == "judge" and agent_name in msg.get("message", "").lower():
            redirects.append(msg["message"])

    parts = [
        f"ROUNDTABLE: {digest.get('topic', 'Unknown')}",
        f"RT ID: {digest.get('roundtable_id', 'unknown')}",
        f"Rounds: {digest.get('rounds', '?')} | Messages: {digest.get('total_messages', '?')}",
        score_str,
        budget_str,
        "",
        f"CONTRIBUTIONS ({len(contributions)}):",
        "\n---\n".join(contributions[:5]) if contributions else "(none)",
    ]

    if redirects:
        parts.append(f"\nJUDGE REDIRECTS ({len(redirects)}):")
        parts.extend(redirects[:3])

    return "\n".join(parts)


def _compute_skill_impact(agent_name: str, owned_skills: list[dict], metrics: dict) -> str:
    """Correlate skill purchases with scoring dimension changes.

    For each owned skill, compare the agent's avg on the relevant dimension(s)
    before vs after acquisition. This gives the Therapist concrete evidence of
    whether a skill purchase is paying off.
    """
    # Map skill IDs to the scoring dimensions they should affect
    skill_to_dimensions = {
        "code-review-framework": ["accuracy"],
        "debate-tactics": ["challenge", "impact"],
        "evidence-gathering": ["accuracy", "novelty"],
        "cross-cutting-analysis": ["novelty", "impact"],
        "risk-assessment": ["accuracy", "challenge"],
        "conciseness-training": ["impact"],  # Say more with less → higher impact
        "novelty-injection": ["novelty"],
        "influence-mapping": ["impact", "challenge"],
    }

    scores = metrics.get("scores", [])
    if len(scores) < 3:
        return ""  # Not enough data

    # Build a list of (roundtable_id, index) for ordering
    rt_order = [(s.get("roundtable_id", ""), i) for i, s in enumerate(scores)]

    lines = ["SKILL IMPACT ANALYSIS:"]
    has_data = False

    for skill in owned_skills:
        skill_id = skill.get("item_id", "")
        dims = skill_to_dimensions.get(skill_id, [])
        if not dims:
            continue

        # Find purchase date from the ledger entry
        purchase_date = skill.get("date", "")
        if not purchase_date:
            continue

        # Find roughly which score index corresponds to the purchase
        # We use the ledger to find the transaction, then count how many scores came before
        try:
            from store import load_ledger
            ledger = load_ledger()
            purchase_ts = None
            for entry in ledger:
                if (entry.get("agent") == agent_name and
                        entry.get("item_id") == skill_id and
                        entry.get("status") == "completed"):
                    purchase_ts = entry.get("timestamp", 0)
                    break

            if not purchase_ts:
                continue

            # Split scores into before/after purchase
            # Scores don't have timestamps, but we can use the count of scores at purchase time
            # vs total scores now. The ledger timestamp tells us roughly when in the sequence.
            # For simplicity: use the last N scores before purchase date as "before",
            # and scores since then as "after"
            before_scores = []
            after_scores = []

            # We know the purchase date string — match it roughly against when scores were added
            # Simpler approach: count total scores at time of purchase = assignments at that time
            # The ledger transaction was after a specific RT, so scores before it are "before"
            purchase_rt = None
            for entry in ledger:
                if (entry.get("agent") == agent_name and
                        entry.get("item_id") == skill_id and
                        entry.get("status") == "completed"):
                    # Look for the RT that happened around this timestamp
                    # The purchase happens during therapist debrief, which is after scoring
                    # So the RT that just ended is the last one before the skill takes effect
                    break

            # Fallback: split scores roughly in half around purchase time
            # Use proportion of time elapsed
            total_scores = len(scores)
            first_ts = ledger[0].get("timestamp", 0) if ledger else 0
            last_ts = ledger[-1].get("timestamp", 0) if ledger else 0
            total_time = last_ts - first_ts if last_ts > first_ts else 1

            # Estimate which score index the purchase fell at
            if purchase_ts <= first_ts:
                split_idx = 0
            elif purchase_ts >= last_ts:
                split_idx = total_scores
            else:
                # Find how many RTs had scores logged before this purchase
                # by checking metrics.json score entries
                split_idx = 0
                for i, s in enumerate(scores):
                    # Each score entry is one RT. Count entries that were likely before purchase.
                    # Since we don't have exact timestamps per score, estimate by position
                    ratio = (i + 1) / total_scores
                    estimated_ts = first_ts + ratio * total_time
                    if estimated_ts < purchase_ts:
                        split_idx = i + 1

            before_scores = scores[:split_idx] if split_idx > 0 else scores[:max(1, total_scores // 2)]
            after_scores = scores[split_idx:] if split_idx < total_scores else []

            if not after_scores or len(after_scores) < 1:
                lines.append(f"  {skill['name']}: too early to measure (acquired {purchase_date})")
                has_data = True
                continue

            # Compute dimension averages before and after
            for dim in dims:
                # Handle legacy field names
                dim_key = dim
                before_vals = [s.get(dim_key, s.get("net_impact", s.get("influence", 0))) if dim_key == "impact"
                               else s.get(dim_key, 0) for s in before_scores]
                after_vals = [s.get(dim_key, s.get("net_impact", s.get("influence", 0))) if dim_key == "impact"
                              else s.get(dim_key, 0) for s in after_scores]

                before_avg = sum(before_vals) / len(before_vals) if before_vals else 0
                after_avg = sum(after_vals) / len(after_vals) if after_vals else 0
                delta = after_avg - before_avg

                if abs(delta) < 0.1:
                    verdict = "no change"
                elif delta > 0:
                    verdict = f"+{delta:.1f} improvement"
                else:
                    verdict = f"{delta:.1f} decline"

                lines.append(
                    f"  {skill['name']} → {dim}: {before_avg:.1f} → {after_avg:.1f} ({verdict}) "
                    f"[{len(before_scores)} RTs before, {len(after_scores)} after]"
                )
                has_data = True

        except Exception as e:
            logger.debug("Skill impact calc failed for %s/%s: %s", agent_name, skill_id, e)
            continue

    if not has_data:
        return ""

    lines.append("Use this data to advise the agent: is the skill paying off? Should they deploy it differently?")
    return "\n".join(lines)


def _get_retired_skills(agent_name: str) -> list[dict]:
    """Get recently retired skills for an agent from the store ledger."""
    try:
        from store import load_ledger
        ledger = load_ledger()
        retired = []
        for entry in ledger:
            if (entry.get("agent") == agent_name and
                    entry.get("category") == "skills" and
                    entry.get("status") == "retired"):
                retired.append({
                    "name": entry.get("item_name", entry.get("item_id", "?")),
                    "retired_at": entry.get("retired_at", "?"),
                    "reason": entry.get("retire_reason", ""),
                })
        return retired
    except Exception:
        return []


def _build_agent_brief(agent_name: str, state: dict) -> str:
    """Build a brief about the agent for the Therapist's context, including analytics.

    Structure: SNAPSHOT (computed ground truth) first, then supporting context.
    The snapshot is the reconciled current state — the therapist should verify
    any treatment plan against it before continuing.
    """
    metrics = state["metrics"]
    tier_labels = {0: "Starting", 1: "Expanded Context", 2: "Model Upgrade", 3: "Autonomous"}
    tier = metrics.get("tier", 0)

    # Extract learned behaviors
    behaviors = "(none)"
    behavior_count = 0
    if "## Learned Behaviors" in state["claude"]:
        idx = state["claude"].index("## Learned Behaviors")
        end_idx = state["claude"].find("\n## ", idx + 1)
        if end_idx == -1:
            end_idx = len(state["claude"])
        behaviors = state["claude"][idx:end_idx].strip()
        behavior_count = behaviors.count("\n- ") + (1 if behaviors.strip().endswith("") else 0)

    # Recent memory (last 800 chars)
    memory_tail = state["memory"][-800:] if len(state["memory"]) > 800 else state["memory"]

    # Diary stats — what the agent writes to themselves
    diary_info = ""
    try:
        from agent_memory import diary_stats, read_diary
        stats = diary_stats(agent_name)
        if stats.get("total_entries", 0) > 0:
            recent = read_diary(agent_name, limit=3)
            diary_info = f"\n\nAGENT DIARY ({stats['total_entries']} entries, {stats['total_eras']} eras):"
            diary_info += f"\n  Top topics: {', '.join(list(stats.get('topic_frequency', {}).keys())[:5])}"
            for entry in recent[-2:]:
                diary_info += f"\n  [{entry.get('date', '?')}] {entry.get('summary', '')[:150]}"
    except Exception:
        pass

    # Growth analytics
    try:
        from analytics import agent_report, format_report_text
        report = agent_report(agent_name)
        growth_report = format_report_text(report)
    except Exception as e:
        logger.warning("Analytics unavailable for %s: %s", agent_name, e)
        growth_report = "(analytics unavailable)"

    # Store affordability + owned skills + retired skills
    store_affordability = "(store unavailable)"
    owned = []
    retired = []
    skill_impact = ""
    try:
        from store import what_can_afford, get_owned_skills
        store_affordability = what_can_afford(agent_name)
        owned = get_owned_skills(agent_name)
        retired = _get_retired_skills(agent_name)
        if owned:
            skill_impact_text = _compute_skill_impact(agent_name, owned, metrics)
            if skill_impact_text:
                skill_impact = skill_impact_text
    except Exception as e:
        logger.warning("Store info unavailable for %s: %s", agent_name, e)

    # Load pending private requests (from previous sessions)
    private_requests_info = ""
    try:
        private_dir = SUITE_ROOT / "store" / "private-requests"
        if private_dir.exists():
            pending = []
            for f in sorted(private_dir.glob(f"{agent_name}_*.json")):
                req = json.loads(f.read_text(encoding="utf-8"))
                if req.get("status", "open") == "open":
                    pending.append(req)
            if pending:
                private_requests_info = (
                    "\n\nPENDING PRIVATE REQUESTS (from previous sessions):\n"
                    + "\n".join(f"  - [{r.get('date', '?')}] {r.get('description', '?')}"
                                for r in pending[-3:])
                    + "\nThe Therapist should address these during this session — "
                    "scope them into skills, reject with explanation, or queue for Admin."
                )
    except Exception as e:
        logger.warning("Private requests unavailable for %s: %s", agent_name, e)

    # Model cost analysis
    model_costs = {"haiku": 2, "flash": 2, "sonnet": 5, "opus": 10}
    current_model = "haiku"  # default
    config_path = SUITE_ROOT / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            worker_cfg = cfg.get("team", {}).get("workers", {}).get(agent_name, {})
            model_str = worker_cfg.get("model", "")
            if "opus" in model_str:
                current_model = "opus"
            elif "sonnet" in model_str:
                current_model = "sonnet"
            elif "gemini" in model_str and "pro" in model_str:
                current_model = "opus"  # Gemini Pro ≈ Opus cost tier
            elif "gemini" in model_str or "flash" in model_str:
                current_model = "flash"
        except (json.JSONDecodeError, OSError):
            pass
    # No automatic tier overrides — upgrades are request-based
    cost_per_round = model_costs.get(current_model, 2)
    avg_score = metrics.get("avg_score", 0)
    net_per_round = avg_score - cost_per_round
    cost_analysis = (
        f"Running as: {current_model} (cost: -{cost_per_round} sparks/round)\n"
        f"Avg score: {avg_score}/12 -> avg earning: +{avg_score} sparks/round\n"
        f"Net per round: {'+' if net_per_round >= 0 else ''}{net_per_round:.1f} sparks\n"
    )
    if net_per_round < 0:
        cost_analysis += "WARNING: Operating at a loss. Consider downgrading model for non-specialty topics."
    elif net_per_round < 2:
        cost_analysis += "MARGINAL: Barely profitable. Only run this model on topics where you expect top-2 placement."
    else:
        cost_analysis += "HEALTHY: Model cost is well-covered by performance."

    # Behavior decay health summary
    behavior_health = ""
    try:
        from evolver import get_behavior_decay_summary
        behavior_health = get_behavior_decay_summary(agent_name)
    except ImportError:
        pass

    # ── Build SNAPSHOT (computed ground truth) ───────────────────────────────
    active_skills_text = ", ".join(s["name"] for s in owned) if owned else "(none)"
    retired_skills_text = ""
    if retired:
        retired_skills_text = "\n  Recently retired: " + ", ".join(
            f"{s['name']} ({s['retired_at']} — {s['reason'][:60]})" for s in retired[-5:])

    snapshot = f"""AGENT SNAPSHOT — {agent_name} (this is computed ground truth):
  Tier: {tier} ({tier_labels.get(tier, 'Unknown')}) | Assignments: {metrics.get('assignments', 0)}
  Sparks: {metrics.get('sparks', 0)} | Avg Score: {avg_score}/12 | Net/round: {'+' if net_per_round >= 0 else ''}{net_per_round:.1f}
  Model: {current_model}
  Active skills: {active_skills_text}{retired_skills_text}
  Active behaviors: {behavior_count}"""

    return f"""{snapshot}

---

MODEL COST ANALYSIS:
{cost_analysis}

CURRENT BEHAVIORS:
{behaviors}
{behavior_health}

RECENT MEMORY:
{memory_tail if memory_tail else '(no prior sessions)'}

GROWTH ANALYTICS:
{growth_report}

STORE:
{store_affordability}
{skill_impact if skill_impact else ''}
{private_requests_info}{diary_info}"""


# ── LLM Calls ───────────────────────────────────────────────────────────────

def _call_llm(prompt: str, model: str) -> str:
    """One-shot LLM call.

    Routes through llm_backend when in open mode (anthropic-sdk / openai-compat),
    else shells out to the Claude CLI preserving all original flags.
    """
    # Try backend first
    try:
        from amatelier.llm_backend import get_backend
        backend = get_backend()
        if backend.name != "claude-code":
            res = backend.complete(
                system="", prompt=prompt, model=model,
                max_tokens=8000, timeout=180,
            )
            text = (res.text or "").strip()
            if text:
                return text
            raise RuntimeError(f"{model} backend returned empty response")
    except RuntimeError:
        raise
    except Exception as e:
        logger.debug("Backend unavailable for therapist call, falling back to CLI: %s", e)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        ["claude", "-p", "--model", model,
         "--no-session-persistence", "--output-format", "text",
         "--disable-slash-commands", "--dangerously-skip-permissions",
         "--max-budget-usd", "5.00"],
        input=prompt, capture_output=True, text=True, timeout=180,
        cwd=str(WORKSPACE_ROOT), encoding="utf-8", errors="replace", env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{model} call failed (exit {result.returncode}): {result.stderr[:300]}")
    return result.stdout.strip()


def _call_therapist(therapist_context: str, conversation: list[dict], opening_data: str = "") -> str:
    """Call the Therapist (Opus) with conversation history."""
    conv_text = "\n\n".join(f"[{m['role']}]: {m['message']}" for m in conversation)

    prompt = f"""{therapist_context}

---
{opening_data}

CONVERSATION SO FAR:
{conv_text if conv_text else '(session opening — you speak first)'}

---
Respond as the Therapist. If this is the final exchange, end with the SESSION OUTCOMES block."""

    return _call_llm(prompt, "opus")


def _call_gemini(prompt: str) -> str:
    """One-shot Gemini call for Naomi's debrief.

    Uses the shared gemini_client module — same retries, rate limiting, and
    error classification as gemini_agent.py. No more subprocess black box.
    """
    from gemini_client import call_gemini
    return call_gemini(prompt)


def _call_agent(agent_name: str, model: str, agent_context: str, conversation: list[dict]) -> str:
    """Call the agent with conversation history for their debrief response."""
    conv_text = "\n\n".join(f"[{m['role']}]: {m['message']}" for m in conversation)

    prompt = f"""{agent_context}

---
You're in a 1-on-1 development session with the Therapist after your roundtable.
This is your chance to:
- React to your debrief and score
- Request store items (public = free, private = 20 sparks)
- Discuss tier upgrades or strategy shifts
- Ask for skill development resources
- Push back on assessments you disagree with

Be honest about what worked and what didn't. Make requests if you have them.

CONVERSATION:
{conv_text}

---
Respond as {agent_name}. Be concise (100-250 words). Make specific requests if you want something."""

    if model == "gemini":
        return _call_gemini(prompt)
    return _call_llm(prompt, model)


# ── Outcome Parsing ─────────────────────────────────────────────────────────

def _parse_outcomes(conversation: list[dict]) -> dict:
    """Parse SESSION OUTCOMES from the Therapist's final message."""
    outcomes = {
        "memory_entry": "",
        "trait": "",
        "add_behaviors": [],
        "remove_behaviors": [],
        "store_requests": [],
        "upgrade_request": "",
        "development_focus": "",
        "sparks_deducted": 0,
    }

    # Find the last therapist message containing SESSION OUTCOMES
    final_msg = ""
    for msg in reversed(conversation):
        if msg["role"] == "therapist" and "SESSION OUTCOMES" in msg["message"]:
            final_msg = msg["message"]
            break

    if not final_msg:
        # No structured outcomes — extract what we can from the last therapist message
        for msg in reversed(conversation):
            if msg["role"] == "therapist":
                outcomes["memory_entry"] = msg["message"][:500]
                break
        return outcomes

    # Parse the structured block
    in_outcomes = False
    for line in final_msg.split("\n"):
        stripped = line.strip()
        upper = stripped.upper()

        if "SESSION OUTCOMES" in upper:
            in_outcomes = True
            continue
        if not in_outcomes:
            continue

        if upper.startswith("MEMORY:"):
            outcomes["memory_entry"] = stripped.split(":", 1)[1].strip()
        elif upper.startswith("TRAIT:"):
            outcomes["trait"] = stripped.split(":", 1)[1].strip()
        elif upper.startswith("ADD BEHAVIOR:"):
            val = stripped.split(":", 1)[1].strip()
            if val.lower() != "none":
                outcomes["add_behaviors"].append(val)
        elif upper.startswith("REMOVE BEHAVIOR:"):
            val = stripped.split(":", 1)[1].strip()
            if val.lower() != "none":
                outcomes["remove_behaviors"].append(val)
        elif upper.startswith("STORE REQUEST:"):
            val = stripped.split(":", 1)[1].strip()
            if val.lower() != "none":
                outcomes["store_requests"].append(val)
        elif upper.startswith("UPGRADE REQUEST:"):
            outcomes["upgrade_request"] = stripped.split(":", 1)[1].strip()
        elif upper.startswith("DEVELOPMENT FOCUS:"):
            outcomes["development_focus"] = stripped.split(":", 1)[1].strip()
        elif upper.startswith("SPARKS DEDUCTED:"):
            try:
                val = stripped.split(":", 1)[1].strip()
                outcomes["sparks_deducted"] = int(val.split()[0]) if val[0].isdigit() else 0
            except (ValueError, IndexError):
                pass

    return outcomes


# ── Outcome Application ─────────────────────────────────────────────────────

def _apply_outcomes(agent_name: str, outcomes: dict, rt_id: str):
    """Apply session outcomes via evolver.py and scorer.py."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    # 1. Memory entry — write to structured memory system
    if outcomes["memory_entry"] and outcomes["memory_entry"].lower() != "none":
        entry = outcomes["memory_entry"]
        if outcomes["trait"] and outcomes["trait"].lower() != "none":
            entry += f" Trait: {outcomes['trait']}"
        if outcomes["development_focus"]:
            entry += f" Focus: {outcomes['development_focus']}"

        try:
            from agent_memory import add_session_summary, add_lesson
            add_session_summary(agent_name, rt_id, entry[:300])
            # If there's a development focus, add it as a lesson
            if outcomes["development_focus"] and outcomes["development_focus"].lower() != "none":
                add_lesson(agent_name, outcomes["development_focus"][:200], source="therapist")
            logger.info("Updated structured memory for %s", agent_name)
        except ImportError:
            # Fallback to legacy MEMORY.md append
            subprocess.run(
                [sys.executable, str(EVOLVER), "memory", agent_name, entry],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", errors="replace", env=env,
            )
            logger.info("Updated MEMORY.md for %s (legacy)", agent_name)

    # 1b. Emerging trait → CLAUDE.md "Emerging Traits" section
    if outcomes["trait"] and outcomes["trait"].lower() != "none":
        subprocess.run(
            [sys.executable, str(EVOLVER), "trait", agent_name, outcomes["trait"]],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace", env=env,
        )
        logger.info("Updated Emerging Traits for %s: %s", agent_name, outcomes["trait"][:60])

    # 2. Add behaviors
    for behavior in outcomes["add_behaviors"]:
        subprocess.run(
            [sys.executable, str(EVOLVER), "behavior", agent_name, behavior],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace", env=env,
        )
        logger.info("Added behavior to %s: %s", agent_name, behavior[:60])

    # 3. Remove behaviors
    for behavior in outcomes["remove_behaviors"]:
        subprocess.run(
            [sys.executable, str(EVOLVER), "remove-behavior", agent_name, behavior],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace", env=env,
        )
        logger.info("Removed behavior from %s: %s", agent_name, behavior[:60])

    # 3b. Confirm any behaviors the Therapist referenced positively
    # (If Therapist didn't remove it and didn't add a replacement, it's implicitly confirmed)
    try:
        from evolver import confirm_behavior, decay_behaviors
        for behavior in outcomes["add_behaviors"]:
            confirm_behavior(agent_name, behavior, rt_id=rt_id)
        # Apply one RT cycle of decay
        decay_result = decay_behaviors(agent_name, rt_id=rt_id)
        if decay_result.get("expired"):
            logger.info("Decay: %d expired behaviors for %s — Therapist should have removed them",
                        len(decay_result["expired"]), agent_name)
    except ImportError:
        logger.debug("Behavior decay not available")

    # 4. Store requests — attempt to process via store.py
    for req in outcomes["store_requests"]:
        logger.info("STORE REQUEST from %s: %s", agent_name, req[:80])
        _process_store_request(agent_name, req, env)

    # 5. Upgrade requests — auto-execute via scorer.promote_tier()
    if outcomes["upgrade_request"] and outcomes["upgrade_request"].lower() != "none":
        logger.info("UPGRADE REQUEST from %s: %s", agent_name, outcomes["upgrade_request"])
        SCORER = SUITE_ROOT / "engine" / "scorer.py"
        promo_result = subprocess.run(
            [sys.executable, str(SCORER), "promote", agent_name],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace", env=env,
        )
        if promo_result.returncode == 0:
            logger.info("PROMOTION EXECUTED for %s: %s", agent_name, promo_result.stdout.strip()[:200])
        else:
            logger.warning("PROMOTION DENIED for %s: %s", agent_name, promo_result.stdout.strip()[:200])

    # 6. Spark deductions — DISABLED (was double-charging)
    # store.purchase() in step 4 already deducts sparks atomically.
    # The old flow called deduct-fee HERE *and* queued a proposal in step 4
    # that would deduct again if approved. This caused double-charging and
    # duplicate skill purchases totaling ~1000 sparks of overcharges.
    # If a non-purchase deduction is ever needed, add a separate mechanism.
    if outcomes["sparks_deducted"] > 0:
        logger.info("SPARKS_DEDUCTED=%d from %s — skipped (purchases handled atomically in step 4)",
                     outcomes["sparks_deducted"], agent_name)

    # 7. Mark any pending private requests as addressed (Therapist reviewed them)
    _mark_private_requests_addressed(agent_name)


def _process_store_request(agent_name: str, request_text: str, env: dict):
    """Execute store purchases and retirements atomically.

    Skills and boosts are purchased via store.purchase() which deducts sparks,
    records to ledger, and delivers the skill file in one step. Duplicate
    purchases are blocked by store.purchase()'s dedup check.

    Private skills and unrecognized requests are queued as proposals for
    user review.
    """
    req_lower = request_text.lower().strip()
    if req_lower in ("none", "none.", "n/a", ""):
        return

    # Keyword map for matching request text to catalog item IDs
    item_map = {
        "dev call": "dev-call", "dev-call": "dev-call", "strategy session": "dev-call",
        "strategy review": "strategy-review", "strategy-review": "strategy-review",
        "code review": "code-review-framework", "code-review": "code-review-framework",
        "debate": "debate-tactics", "debate tactics": "debate-tactics",
        "evidence": "evidence-gathering", "evidence gathering": "evidence-gathering",
        "cross-cutting": "cross-cutting-analysis", "cross cutting": "cross-cutting-analysis",
        "risk": "risk-assessment", "risk assessment": "risk-assessment",
        "conciseness": "conciseness-training", "concise": "conciseness-training",
        "novelty": "novelty-injection", "novelty injection": "novelty-injection",
        "influence": "influence-mapping", "influence mapping": "influence-mapping",
        "extra budget": "extra-budget", "floor turns": "extra-budget", "extra turns": "extra-budget",
        "extra slot": "extra-slot", "skill slot": "extra-slot",
        "first speaker": "first-speaker", "first-speaker": "first-speaker",
        "private request": "private-request", "private": "private-request",
    }

    # ── Step 1: Try to parse as JSON-formatted request ───────────────────
    parsed = _try_parse_store_json(request_text)
    item_id = None
    op = None

    if parsed:
        req_type = parsed.get("type", "").lower()

        if req_type == "private":
            desc = parsed.get("description", request_text[:200])
            _queue_proposal(
                agent_name=agent_name,
                change_type="store_private_skill",
                title=f"{agent_name}: private skill — {desc[:50]}",
                description=desc,
                action=json.dumps({
                    "agent": agent_name, "op": "private_skill",
                    "cost": parsed.get("cost", 20), "description": desc,
                }),
            )
            return

        if req_type in ("skill-retire", "skill-deactivate"):
            item_id = parsed.get("id", parsed.get("item", ""))
            op = "retire"

        elif req_type in ("purchase", "skill", "skill-purchase", "boost",
                          "boost-purchase", "strategy-review", "dev-call"):
            item_id = parsed.get("id", parsed.get("item", ""))
            if not item_id and req_type in ("strategy-review", "dev-call"):
                item_id = req_type
            op = "purchase"

    # ── Step 2: Keyword matching (if JSON didn't yield an item_id) ───────
    if not item_id:
        if "retire" in req_lower or "unequip" in req_lower:
            op = "retire"
        else:
            op = "purchase"
        for keyword, mapped_id in item_map.items():
            if keyword in req_lower:
                item_id = mapped_id
                break

    # ── Step 3: Execute the operation ────────────────────────────────────
    if item_id and op == "retire":
        try:
            from store import retire_skill
            result = retire_skill(agent_name, item_id, reason=request_text[:200])
            if "error" in result:
                logger.warning("Retire failed for %s/%s: %s", agent_name, item_id, result["error"])
            else:
                logger.info("RETIRED %s for %s", item_id, agent_name)
        except Exception as e:
            logger.error("Retire exception for %s/%s: %s", agent_name, item_id, e)
        return

    if item_id and op == "purchase":
        try:
            from store import purchase
            result = purchase(agent_name, item_id)
            if "error" in result:
                logger.warning("Purchase blocked for %s/%s: %s", agent_name, item_id, result["error"])
            else:
                logger.info("PURCHASED %s for %s (-%d sparks, balance: %d)",
                            item_id, agent_name, result["cost"], result["new_balance"])
        except Exception as e:
            logger.error("Purchase exception for %s/%s: %s", agent_name, item_id, e)
        return

    # ── Step 4: Fallback — queue unrecognized requests for user review ───
    _queue_proposal(
        agent_name=agent_name,
        change_type="other",
        title=f"{agent_name}: store request",
        description=request_text,
        action=json.dumps({"agent": agent_name, "op": "bulletin", "text": request_text[:200]}),
    )


def _try_parse_store_json(text: str) -> dict | None:
    """Try to parse a store request as JSON. Handles both strict JSON and
    the common {type: x, ...} format from SESSION OUTCOMES blocks."""
    import re as _re
    text = text.strip()
    if not text.startswith("{"):
        return None
    fixed = text
    fixed = _re.sub(r'(?<=[{,])\s*(\w+)\s*:', r' "\1":', fixed)
    fixed = fixed.replace("'", '"')
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        return None


def _queue_proposal(agent_name: str, change_type: str, title: str,
                    description: str, action: str):
    """Insert a store request as a pending proposal in an optional external
    evolution harness DB. Set CLAUDE_EVOLUTION_HARNESS to the harness repo
    root to enable this. When unset, proposals are logged and skipped.
    """
    harness_env = os.environ.get("CLAUDE_EVOLUTION_HARNESS", "").strip()
    if not harness_env:
        logger.info("Skipping harness proposal (CLAUDE_EVOLUTION_HARNESS not set): [%s] %s",
                    change_type, title)
        return
    try:
        harness_root = Path(harness_env)
        _sys_path_orig = sys.path[:]
        sys.path.insert(0, str(harness_root))
        from src.db import get_db
        conn = get_db()
        conn.execute(
            """INSERT INTO proposed_changes
               (change_type, title, description, proposed_action, status, created_at, confidence)
               VALUES (?, ?, ?, ?, 'pending', datetime('now'), 1.0)""",
            (change_type, title, description, action),
        )
        conn.commit()
        conn.close()
        sys.path[:] = _sys_path_orig
        logger.info("Queued proposal for review: [%s] %s", change_type, title)
    except Exception as e:
        logger.error("Failed to queue proposal for %s: %s", agent_name, e)


def _mark_private_requests_addressed(agent_name: str, resolution: str = "addressed"):
    """Mark all pending private requests for an agent as addressed after Therapist review."""
    private_dir = SUITE_ROOT / "store" / "private-requests"
    if not private_dir.exists():
        return
    for f in private_dir.glob(f"{agent_name}_*.json"):
        try:
            req = json.loads(f.read_text(encoding="utf-8"))
            if req.get("status", "open") == "open":
                req["status"] = resolution
                req["resolved_date"] = time.strftime("%Y-%m-%d")
                f.write_text(json.dumps(req, indent=2), encoding="utf-8")
                logger.info("Private request marked %s for %s: %s",
                            resolution, agent_name, req.get("description", "")[:60])
        except Exception as e:
            logger.warning("Failed to update private request %s: %s", f.name, e)


# ── Session Runner ───────────────────────────────────────────────────────────

def _resolve_agent_model(agent_name: str) -> str:
    """Resolve which model to use for the agent in the debrief.

    v0.4.0: reads backend + model from worker_registry. Gemini-backed agents
    debrief with gemini; other backends default to the worker's configured
    model alias or "sonnet" if none.
    """
    from amatelier import worker_registry

    if worker_registry.get_worker_backend(agent_name) == "gemini":
        return "gemini"

    tier_model_map = {0: None, 1: None, 2: "sonnet", 3: "opus"}

    # Pull default from config via worker_registry (falls back to "sonnet")
    default = worker_registry.get_worker_model(agent_name, default="sonnet")
    # Normalize full model IDs to aliases where possible (sonnet/haiku/opus)
    for alias in ("opus", "sonnet", "haiku"):
        if alias in default:
            default = alias
            break
    metrics_path = WRITE_ROOT / "agents" / agent_name / "metrics.json"
    if not metrics_path.exists():
        return default
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        tier = metrics.get("tier", 0)
        override = tier_model_map.get(tier)
        return override if override else default
    except (json.JSONDecodeError, OSError):
        return default


def run_session(agent_name: str, digest: dict, max_turns: int = 2) -> dict:
    """Run a single Therapist session with one agent.

    Structure: Therapist opens -> Agent responds -> [repeat max_turns] -> Therapist closes.
    Total calls: (max_turns + 1) Opus + max_turns agent = 2*max_turns + 1
    """
    therapist_context = _load_therapist_context()
    state = _load_agent_state(agent_name)
    agent_brief = _build_agent_brief(agent_name, state)
    rt_data = _extract_agent_data(digest, agent_name)
    case_notes = _load_case_notes(agent_name)
    case_notes_text = _format_case_notes(case_notes)

    # Resolve agent model using local logic (avoids circular import from roundtable_runner)
    agent_model = _resolve_agent_model(agent_name)

    agent_context = state["claude"][:4000]  # Trim for prompt budget

    opening_data = f"""{agent_brief}

---
{case_notes_text}

---
THIS ROUNDTABLE:
{rt_data}"""

    conversation: list[dict] = []

    logger.info("Starting session with %s (model: %s, turns: %d)", agent_name, agent_model, max_turns)

    # Therapist opens
    therapist_msg = _call_therapist(therapist_context, conversation, opening_data)
    conversation.append({"role": "therapist", "message": therapist_msg})
    logger.info("Therapist opened session with %s (%d chars)", agent_name, len(therapist_msg))

    # Exchange turns
    for turn in range(max_turns):
        # Agent responds
        agent_msg = _call_agent(agent_name, agent_model, agent_context, conversation)
        conversation.append({"role": agent_name, "message": agent_msg})
        logger.info("  %s responded (%d chars)", agent_name, len(agent_msg))

        # Therapist responds (on last turn, this is the closing with SESSION OUTCOMES)
        is_final = turn == max_turns - 1
        if is_final:
            # Add instruction to close with outcomes
            conversation.append({
                "role": "system",
                "message": "This is the final exchange. Close the session with your SESSION OUTCOMES block."
            })

        therapist_msg = _call_therapist(therapist_context, conversation, opening_data if turn == 0 else "")
        conversation.append({"role": "therapist", "message": therapist_msg})
        logger.info("  Therapist responded (%d chars)%s", len(therapist_msg),
                     " [CLOSING]" if is_final else "")

    # Parse and apply outcomes
    outcomes = _parse_outcomes(conversation)
    rt_id = digest.get("roundtable_id", "unknown")
    _apply_outcomes(agent_name, outcomes, rt_id)

    # Update Therapist's persistent case notes
    _update_case_notes(agent_name, case_notes, conversation, outcomes, digest)

    # Extract episodic memories from this session (peaks, failures, insights)
    try:
        from agent_memory import extract_episodes_from_therapist, add_goal
        extract_episodes_from_therapist(agent_name, conversation, outcomes, digest)
        # If Therapist set a development focus, track it as an active goal
        if outcomes.get("development_focus") and outcomes["development_focus"].lower() != "none":
            add_goal(agent_name, outcomes["development_focus"][:200],
                     rt_started=digest.get("roundtable_id", "")[:12])
        logger.info("Episodic memory extracted for %s", agent_name)
    except ImportError:
        logger.debug("agent_memory not available — skipping episode extraction")
    except Exception as e:
        logger.warning("Episode extraction failed for %s (non-fatal): %s", agent_name, e)

    # Auto-generate diary entry from the agent's own debrief words
    try:
        from agent_memory import write_diary_entry
        agent_words = [m["message"] for m in conversation if m["role"] == agent_name]
        if agent_words:
            # Combine the agent's debrief responses into a diary entry
            combined = " ".join(agent_words)
            # Frame as first-person reflection
            topic = digest.get("topic", "the roundtable")
            rt_id_short = digest.get("roundtable_id", "")[:12]
            diary_text = f"After RT {rt_id_short} on \"{topic}\": {combined[:600]}"
            result = write_diary_entry(agent_name, diary_text,
                                       rt_id=digest.get("roundtable_id", ""))
            if result.get("written"):
                logger.info("Diary entry written for %s", agent_name)
            else:
                logger.info("Diary entry skipped for %s: %s", agent_name, result.get("reason", ""))
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Diary write failed for %s (non-fatal): %s", agent_name, e)

    # Save session transcript
    session_dir = WRITE_ROOT / "agents" / agent_name / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_file = session_dir / f"therapist_{time.strftime('%Y-%m-%d_%H%M%S')}.json"
    session_file.write_text(json.dumps({
        "type": "therapist_debrief",
        "roundtable_id": rt_id,
        "agent": agent_name,
        "conversation": conversation,
        "outcomes": outcomes,
        "timestamp": time.time(),
    }, indent=2), encoding="utf-8")
    logger.info("Session saved to %s", session_file.name)

    return {
        "conversation_turns": len(conversation),
        "memory_updated": bool(outcomes["memory_entry"]),
        "behaviors_added": len(outcomes["add_behaviors"]),
        "behaviors_removed": len(outcomes["remove_behaviors"]),
        "store_requests": outcomes["store_requests"],
        "upgrade_request": outcomes["upgrade_request"],
        "development_focus": outcomes["development_focus"],
        "sparks_deducted": outcomes["sparks_deducted"],
        "trait": outcomes["trait"],
    }


def run_therapist(digest_path: str, agents: list[str] | None = None, max_turns: int = 2) -> dict:
    """Run Therapist sessions for all agents in a roundtable."""
    path = Path(digest_path)
    if not path.is_absolute():
        path = SUITE_ROOT / digest_path
    if not path.exists():
        raise FileNotFoundError(f"Digest not found: {digest_path}")

    digest = json.loads(path.read_text(encoding="utf-8"))
    rt_id = digest.get("roundtable_id", "unknown")

    if agents:
        target_agents = agents
    else:
        target_agents = [
            name for name in digest.get("contributions", {})
            if name not in ("runner", "assistant", "judge")
        ]

    logger.info("=== THERAPIST SESSIONS for RT %s ===", rt_id)
    logger.info("Agents: %s | Turns per session: %d", ", ".join(target_agents), max_turns)

    results = {}
    for agent_name in target_agents:
        try:
            results[agent_name] = run_session(agent_name, digest, max_turns)
        except Exception as e:
            logger.error("Session failed for %s: %s", agent_name, e)
            results[agent_name] = {"error": str(e)}

    # Generate and save the therapist report
    report = _generate_report(rt_id, digest, target_agents, results)
    report_dir = SUITE_ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"therapist-{rt_id}.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info("Therapist report saved to %s", report_path)

    return results


def _generate_report(rt_id: str, digest: dict, agents: list[str], results: dict) -> str:
    """Generate a readable markdown report of all therapist sessions."""
    lines = [
        f"# Therapist Report — RT {rt_id}",
        f"**Date:** {time.strftime('%Y-%m-%d %H:%M')}",
        f"**Topic:** {digest.get('topic', 'Unknown')}",
        f"**Agents debriefed:** {', '.join(agents)}",
        "",
    ]

    # Summary table
    lines.extend([
        "## Summary",
        "",
        "| Agent | Phase | Score | Focus | Behaviors +/- | Requests |",
        "|-------|-------|-------|-------|----------------|----------|",
    ])

    for agent_name in agents:
        r = results.get(agent_name, {})
        if "error" in r:
            lines.append(f"| {agent_name} | — | — | ERROR: {r['error'][:40]} | — | — |")
            continue

        # Get phase from analytics
        try:
            from analytics import detect_phase, load_metrics
            phase = detect_phase(load_metrics(agent_name))
        except Exception:
            phase = "?"

        # Score from digest — handle both list and dict formats
        score_str = "?"
        report_scoring = digest.get("scoring", [])
        if isinstance(report_scoring, dict):
            report_scoring = report_scoring.get("scores", [])
        for s in report_scoring:
            if isinstance(s, dict) and s.get("agent") == agent_name:
                score_str = f"{s.get('score', s.get('total', '?'))}/12"
                break

        focus = r.get("development_focus", "—")[:50]
        b_added = r.get("behaviors_added", 0)
        b_removed = r.get("behaviors_removed", 0)
        b_str = f"+{b_added}" + (f" -{b_removed}" if b_removed else "")

        reqs = []
        if r.get("store_requests"):
            reqs.append(f"{len(r['store_requests'])} store")
        if r.get("upgrade_request") and r["upgrade_request"].lower() != "none":
            reqs.append("upgrade")
        if r.get("sparks_deducted", 0) > 0:
            reqs.append(f"-{r['sparks_deducted']}sp")
        req_str = ", ".join(reqs) if reqs else "—"

        lines.append(f"| {agent_name} | {phase} | {score_str} | {focus} | {b_str} | {req_str} |")

    lines.append("")

    # Per-agent detail sections
    for agent_name in agents:
        r = results.get(agent_name, {})
        if "error" in r:
            lines.extend([f"## {agent_name}", f"Session failed: {r['error']}", ""])
            continue

        lines.extend([
            f"## {agent_name}",
            "",
        ])

        # Load the session transcript for this agent
        session_dir = WRITE_ROOT / "agents" / agent_name / "sessions"
        transcript = _load_latest_session(session_dir, rt_id)

        if transcript:
            for msg in transcript:
                role = msg.get("role", "unknown")
                text = msg.get("message", "")
                if role == "system":
                    continue
                label = "**Therapist:**" if role == "therapist" else f"**{agent_name}:**"
                lines.extend([label, "", text, ""])
        else:
            lines.append("*(transcript not available)*")
            lines.append("")

        # Outcomes
        if r.get("trait"):
            lines.append(f"**Trait observed:** {r['trait']}")
        if r.get("development_focus"):
            lines.append(f"**Development focus:** {r['development_focus']}")
        if r.get("store_requests"):
            for req in r["store_requests"]:
                lines.append(f"**Store request:** {req}")
        if r.get("upgrade_request") and r["upgrade_request"].lower() != "none":
            lines.append(f"**Upgrade request:** {r['upgrade_request']}")
        lines.extend(["", "---", ""])

    return "\n".join(lines)


def _load_latest_session(session_dir: Path, rt_id: str) -> list[dict] | None:
    """Load the most recent therapist session transcript matching an RT.

    Only returns transcripts that match the given rt_id — never falls back
    to an unrelated roundtable's transcript.
    """
    if not session_dir.exists():
        return None
    candidates = sorted(session_dir.glob("therapist_*.json"), reverse=True)
    for f in candidates:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("roundtable_id") == rt_id:
                return data.get("conversation", [])
        except (json.JSONDecodeError, OSError):
            continue
    return None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Therapist — interactive post-roundtable development sessions")
    parser.add_argument("--digest", required=True, help="Path to digest JSON file")
    parser.add_argument("--agents", default=None, help="Comma-separated agent names (default: all)")
    parser.add_argument("--turns", type=int, default=2, help="Exchange turns per session (default: 2)")

    args = parser.parse_args()
    agents = args.agents.split(",") if args.agents else None

    results = run_therapist(args.digest, agents, args.turns)
    print(json.dumps(results, indent=2))
