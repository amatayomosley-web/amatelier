"""Competition Scorer — leaderboard management, ranking, reward tier tracking."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SUITE_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = SUITE_ROOT / "agents"
CONFIG_PATH = SUITE_ROOT / "config.json"

# Cross-platform file locking for metrics.json safety
if sys.platform == "win32":
    import msvcrt

    def _lock_file(f):
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock_file(f):
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _lock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def _unlock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


_METRICS_DEFAULTS = {
    "tier": 0, "assignments": 0, "total_score": 0, "avg_score": 0,
    "scores": [], "leaderboard_rank": 0, "sparks": 0, "ventures": [],
}


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_metrics(agent_name: str) -> dict:
    path = AGENTS_DIR / agent_name / "metrics.json"
    if path.exists():
        m = json.loads(path.read_text(encoding="utf-8"))
        # Ensure sparks fields exist (backcompat)
        m.setdefault("sparks", 0)
        m.setdefault("ventures", [])
        return m
    return dict(_METRICS_DEFAULTS)


def save_metrics(agent_name: str, metrics: dict):
    """Write metrics.json with file locking to prevent concurrent-write corruption."""
    path = AGENTS_DIR / agent_name / "metrics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        _lock_file(f)
        try:
            json.dump(metrics, f, indent=2)
        finally:
            _unlock_file(f)
    # Atomic rename (on Windows, need to remove target first)
    if sys.platform == "win32" and path.exists():
        path.unlink()
    tmp.rename(path)



def score_agent(
    agent_name: str,
    novelty: int,
    accuracy: int,
    impact: int,
    challenge: int,
    roundtable_id: str = "",
) -> dict:
    """Score an agent's roundtable contribution and update their metrics.

    Absolute scoring: each axis point = 1 spark earned directly.
    Valid scores per axis: 0, 1, 2, 3, or 10 (grand insight).
    """
    total = novelty + accuracy + impact + challenge
    metrics = load_metrics(agent_name)

    entry = {
        "roundtable_id": roundtable_id,
        "novelty": novelty,
        "accuracy": accuracy,
        "impact": impact,
        "challenge": challenge,
        "total": total,
    }
    metrics["scores"].append(entry)
    metrics["assignments"] += 1
    metrics["total_score"] += total
    metrics["avg_score"] = round(metrics["total_score"] / metrics["assignments"], 2)

    # Award sparks — 1:1 with score (absolute model, no earn_rate multiplier)
    metrics["sparks"] = metrics.get("sparks", 0) + total
    logger.info("%s earned %d sparks (balance: %d)", agent_name, total, metrics["sparks"])

    # Track net result for relegation checks
    metrics.setdefault("rt_net_history", []).append({
        "roundtable_id": roundtable_id,
        "gross": total,
    })

    save_metrics(agent_name, metrics)
    return {
        "agent": agent_name, "score": total, "tier": metrics["tier"],
        "avg": metrics["avg_score"], "sparks_earned": total,
        "sparks_balance": metrics["sparks"],
    }


def deduct_entry_fee(agent_name: str, fee: int, roundtable_id: str = "") -> dict:
    """Deduct flat RT entry fee from agent's spark balance."""
    metrics = load_metrics(agent_name)
    metrics["sparks"] = metrics.get("sparks", 0) - fee

    # Record the fee in the last rt_net_history entry if it exists,
    # otherwise create a placeholder
    rt_history = metrics.setdefault("rt_net_history", [])
    if rt_history and rt_history[-1].get("roundtable_id") == roundtable_id:
        rt_history[-1]["entry_fee"] = fee
        rt_history[-1]["net"] = rt_history[-1].get("gross", 0) - fee
    else:
        rt_history.append({
            "roundtable_id": roundtable_id,
            "entry_fee": fee,
            "gross": 0,
            "net": -fee,
        })

    save_metrics(agent_name, metrics)
    logger.info("%s entry fee: -%d sparks (balance: %d)", agent_name, fee, metrics["sparks"])
    return {"agent": agent_name, "fee": fee, "sparks_balance": metrics["sparks"]}


def get_leaderboard() -> list[dict]:
    """Get ranked leaderboard of all workers."""
    config = load_config()
    workers = config.get("team", {}).get("workers", {})
    board = []
    for name in workers:
        m = load_metrics(name)
        board.append({
            "agent": name,
            "model": workers[name].get("model", "unknown"),
            "assignments": m["assignments"],
            "total_score": m["total_score"],
            "avg_score": m["avg_score"],
            "tier": m["tier"],
            "sparks": m.get("sparks", 0),
        })
    board.sort(key=lambda x: x["avg_score"], reverse=True)
    for i, entry in enumerate(board):
        entry["rank"] = i + 1
    return board


TIER_NAMES = {1: "expanded_context", 2: "model_upgrade", 3: "autonomy"}
TIER_LABELS = {0: "Starting", 1: "Expanded", 2: "Upgraded", 3: "Autonomous"}


def promote_tier(agent_name: str) -> dict:
    """Agent purchases a tier promotion with sparks.

    Requirements: sufficient assignments AND sufficient sparks.
    The spark cost is consumed on promotion.
    """
    metrics = load_metrics(agent_name)
    current_tier = metrics.get("tier", 0)
    next_tier = current_tier + 1

    if next_tier > 3:
        return {"error": f"{agent_name} is already at max tier (Autonomous)"}

    config = load_config()
    thresholds = config.get("competition", {}).get("tier_thresholds", {})
    tier_key = TIER_NAMES.get(next_tier)
    tier_config = thresholds.get(tier_key, {})

    req_assignments = tier_config.get("assignments", 999)
    spark_cost = tier_config.get("spark_cost", 999)

    if metrics["assignments"] < req_assignments:
        return {"error": f"{agent_name} needs {req_assignments} assignments for {TIER_LABELS[next_tier]} (has {metrics['assignments']})"}

    balance = metrics.get("sparks", 0)
    if balance < spark_cost:
        return {"error": f"{agent_name} needs {spark_cost} sparks for {TIER_LABELS[next_tier]} (has {balance})"}

    # Purchase the promotion
    metrics["sparks"] = balance - spark_cost
    metrics["tier"] = next_tier
    save_metrics(agent_name, metrics)
    logger.info("%s promoted to Tier %d (%s) for %d sparks", agent_name, next_tier, TIER_LABELS[next_tier], spark_cost)
    return {
        "agent": agent_name,
        "new_tier": next_tier,
        "tier_label": TIER_LABELS[next_tier],
        "spark_cost": spark_cost,
        "sparks_balance": metrics["sparks"],
    }


def check_self_determined(agent_name: str) -> dict:
    """Check if an agent has earned the right to choose their own evolution path.

    Reads self_determined_thresholds from config — an agent needs N assignments
    at the required role tier to unlock self-determination.
    """
    config = load_config()
    thresholds = config.get("self_determined_thresholds", {})
    metrics = load_metrics(agent_name)

    # Determine the agent's role category
    role = "worker"  # default
    agent_dir = AGENTS_DIR / agent_name
    identity_path = agent_dir / "IDENTITY.md"
    if identity_path.exists():
        identity_text = identity_path.read_text(encoding="utf-8").lower()
        for r in ("admin", "judge", "therapist"):
            if r in identity_text:
                role = r
                break

    threshold = thresholds.get(role, 20)
    assignments = metrics.get("assignments", 0)
    eligible = assignments >= threshold

    return {
        "agent": agent_name,
        "role": role,
        "assignments": assignments,
        "threshold": threshold,
        "eligible": eligible,
    }


def pitch_venture(agent_name: str, tier: str, idea: str, roundtable_id: str = "") -> dict:
    """Agent stakes sparks on an experimental idea.

    Tiers: scout (5 sparks), venture (15), moonshot (30).
    Returns the venture record or an error.
    """
    config = load_config()
    venture_config = config.get("competition", {}).get("ventures", {})
    if tier not in venture_config:
        return {"error": f"Unknown venture tier '{tier}'. Options: {list(venture_config.keys())}"}

    stake = venture_config[tier]["stake"]
    multiplier = venture_config[tier]["multiplier"]

    metrics = load_metrics(agent_name)
    balance = metrics.get("sparks", 0)
    if balance < stake:
        return {"error": f"{agent_name} has {balance} sparks but needs {stake} for a {tier}"}

    # Deduct the stake
    metrics["sparks"] = balance - stake

    venture = {
        "id": f"v-{len(metrics.get('ventures', []))+1:03d}",
        "tier": tier,
        "stake": stake,
        "multiplier": multiplier,
        "idea": idea,
        "roundtable_id": roundtable_id,
        "status": "pending",
        "payout": 0,
    }
    metrics.setdefault("ventures", []).append(venture)
    save_metrics(agent_name, metrics)
    logger.info("%s pitched %s venture '%s' for %d sparks", agent_name, tier, idea[:50], stake)
    return {"agent": agent_name, "venture": venture, "sparks_balance": metrics["sparks"]}


def resolve_venture(agent_name: str, venture_id: str, success: bool) -> dict:
    """Admin resolves a venture — success awards multiplier, failure loses stake."""
    metrics = load_metrics(agent_name)
    ventures = metrics.get("ventures", [])

    target = None
    for v in ventures:
        if v["id"] == venture_id:
            target = v
            break

    if target is None:
        return {"error": f"Venture '{venture_id}' not found for {agent_name}"}
    if target["status"] != "pending":
        return {"error": f"Venture '{venture_id}' already resolved as {target['status']}"}

    if success:
        payout = int(target["stake"] * target["multiplier"])
        target["status"] = "success"
        target["payout"] = payout
        metrics["sparks"] = metrics.get("sparks", 0) + payout
        logger.info("%s venture %s succeeded! +%d sparks", agent_name, venture_id, payout)
    else:
        target["status"] = "failed"
        target["payout"] = 0
        logger.info("%s venture %s failed. -%d sparks lost", agent_name, venture_id, target["stake"])

    save_metrics(agent_name, metrics)
    return {
        "agent": agent_name,
        "venture_id": venture_id,
        "outcome": "success" if success else "failed",
        "payout": target["payout"],
        "sparks_balance": metrics["sparks"],
    }


def award_gate_bonus(agent_name: str, reason: str, roundtable_id: str = "") -> dict:
    """Judge awards a gate bonus for an exceptional contribution.

    Gates reward contributions that redirect the group — paradigm-shifting
    questions, reframes, or insights that changed the discussion trajectory.
    Each gate awards bonus sparks (default 3). Max gates per RT enforced by caller.
    """
    config = load_config()
    gate_config = config.get("competition", {}).get("gate_bonus", {})
    if not gate_config.get("enabled", True):
        return {"error": "Gate bonuses are disabled"}

    sparks_per_gate = gate_config.get("sparks_per_gate", 3)
    metrics = load_metrics(agent_name)
    metrics["sparks"] = metrics.get("sparks", 0) + sparks_per_gate

    # Track gate history
    gate_entry = {
        "roundtable_id": roundtable_id,
        "reason": reason,
        "sparks": sparks_per_gate,
    }
    metrics.setdefault("gates", []).append(gate_entry)
    save_metrics(agent_name, metrics)
    logger.info("GATE BONUS: %s +%d sparks — %s", agent_name, sparks_per_gate, reason[:80])
    return {
        "agent": agent_name,
        "gate_sparks": sparks_per_gate,
        "reason": reason,
        "sparks_balance": metrics["sparks"],
    }


def award_rt_outcome_bonus(agent_names: list[str], roundtable_id: str, description: str = "") -> list[dict]:
    """Award bonus sparks to agents whose RT proposal was implemented by the user."""
    config = load_config()
    bonus = config.get("competition", {}).get("rt_outcome_bonus", {}).get("implemented", 5)
    results = []
    for name in agent_names:
        metrics = load_metrics(name)
        metrics["sparks"] = metrics.get("sparks", 0) + bonus
        metrics.setdefault("outcome_bonuses", []).append({
            "roundtable_id": roundtable_id,
            "sparks": bonus,
            "description": description,
        })
        save_metrics(name, metrics)
        results.append({"agent": name, "bonus": bonus, "sparks_balance": metrics["sparks"]})
        logger.info("RT OUTCOME BONUS: %s +%d sparks for %s", name, bonus, roundtable_id)
    return results


def get_spark_balances() -> list[dict]:
    """Get spark balances and pending ventures for all workers."""
    config = load_config()
    workers = config.get("team", {}).get("workers", {})
    result = []
    for name in workers:
        m = load_metrics(name)
        pending = [v for v in m.get("ventures", []) if v["status"] == "pending"]
        succeeded = [v for v in m.get("ventures", []) if v["status"] == "success"]
        failed = [v for v in m.get("ventures", []) if v["status"] == "failed"]
        result.append({
            "agent": name,
            "sparks": m.get("sparks", 0),
            "pending_ventures": len(pending),
            "succeeded": len(succeeded),
            "failed": len(failed),
            "total_staked": sum(v["stake"] for v in m.get("ventures", [])),
            "total_earned_from_ventures": sum(v["payout"] for v in succeeded),
        })
    result.sort(key=lambda x: x["sparks"], reverse=True)
    return result


def compute_variance_flags(rt_id: str, workers: list[str], round_num: int) -> dict[str, dict]:
    """Detect byzantine scoring patterns — flat low or erratic across axes.

    Returns {agent: {"flagged": bool, "reason": str, "mean": float, "variance": float}}.
    Only fires round 3+ (need n>=3 scores for meaningful variance).
    Rolling recalculation — flags can clear if behavior normalizes.
    """
    if round_num < 3:
        return {}

    results = {}
    try:
        from db import get_db
        with get_db() as conn:
            for agent in workers:
                rows = conn.execute(
                    "SELECT novelty, accuracy, impact, challenge FROM scores "
                    "WHERE roundtable_id=? AND agent_name=?",
                    (rt_id, agent),
                ).fetchall()
                if not rows:
                    continue
                all_vals = []
                for r in rows:
                    all_vals.extend([r["novelty"], r["accuracy"], r["impact"], r["challenge"]])
                if not all_vals:
                    continue
                mean = sum(all_vals) / len(all_vals)
                variance = sum((v - mean) ** 2 for v in all_vals) / len(all_vals)
                flagged = False
                reason = ""
                if mean < 1.5 and variance < 0.3:
                    flagged = True
                    reason = f"flat-low (mean={mean:.2f}, var={variance:.2f})"
                elif variance > 2.0:
                    flagged = True
                    reason = f"erratic (mean={mean:.2f}, var={variance:.2f})"
                results[agent] = {"flagged": flagged, "reason": reason, "mean": round(mean, 2), "variance": round(variance, 2)}
                if flagged:
                    conn.execute(
                        "UPDATE scores SET is_flagged=1, flagged_since_round=? "
                        "WHERE roundtable_id=? AND agent_name=? AND is_flagged=0",
                        (round_num, rt_id, agent),
                    )
                else:
                    conn.execute(
                        "UPDATE scores SET is_flagged=0, flagged_since_round=NULL "
                        "WHERE roundtable_id=? AND agent_name=?",
                        (rt_id, agent),
                    )
            conn.commit()
    except Exception as e:
        logger.warning("Byzantine variance check failed: %s", e)
    return results


def check_underperformers() -> list[str]:
    """Identify agents at risk of relegation (3 consecutive net-negative RTs).

    Net-negative means gross earnings minus entry fee < 0 for that RT.
    Uses rt_net_history from metrics.json, populated by score_agent() and deduct_entry_fee().
    """
    config = load_config()
    workers = config.get("team", {}).get("workers", {})
    relegation = config.get("competition", {}).get("relegation", {})
    threshold = relegation.get("threshold", 3)
    at_risk = []
    for name in workers:
        m = load_metrics(name)
        rt_history = m.get("rt_net_history", [])
        if len(rt_history) < threshold:
            continue
        recent = rt_history[-threshold:]
        all_negative = all(
            entry.get("net", entry.get("gross", 0) - entry.get("entry_fee", 0)) < 0
            for entry in recent
        )
        if all_negative:
            at_risk.append(name)
    return at_risk



if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Claude Suite Competition Scorer")
    sub = parser.add_subparsers(dest="command")

    p_score = sub.add_parser("score", help="Score an agent's roundtable contribution")
    p_score.add_argument("agent", help="Agent name (e.g. elena, marcus)")
    p_score.add_argument("novelty", type=int, help="Novelty score (0-3 or 10)")
    p_score.add_argument("accuracy", type=int, help="Accuracy score (0-3 or 10)")
    p_score.add_argument("impact", type=int, help="Impact score (0-3 or 10)")
    p_score.add_argument("challenge", type=int, help="Challenge score (0-3 or 10)")
    p_score.add_argument("--rt", default="", help="Roundtable ID")

    p_fee = sub.add_parser("deduct-fee", help="Deduct flat RT entry fee from agent's sparks")
    p_fee.add_argument("agent", help="Agent name")
    p_fee.add_argument("fee", type=int, help="Fee amount in sparks")
    p_fee.add_argument("--rt", default="", help="Roundtable ID")

    sub.add_parser("leaderboard", help="Print current leaderboard")
    sub.add_parser("check", help="Check for underperformers at risk of relegation")
    sub.add_parser("balances", help="Print spark balances and venture stats")

    p_promote = sub.add_parser("promote", help="Agent purchases a tier promotion with sparks")
    p_promote.add_argument("agent", help="Agent name")

    p_pitch = sub.add_parser("pitch", help="Agent stakes sparks on an experimental idea")
    p_pitch.add_argument("agent", help="Agent name")
    p_pitch.add_argument("tier", choices=["scout", "venture", "moonshot"], help="Venture tier")
    p_pitch.add_argument("idea", help="Description of the idea")
    p_pitch.add_argument("--rt", default="", help="Roundtable ID")

    p_resolve = sub.add_parser("resolve", help="Admin resolves a venture (success/fail)")
    p_resolve.add_argument("agent", help="Agent name")
    p_resolve.add_argument("venture_id", help="Venture ID (e.g. v-001)")
    p_resolve.add_argument("outcome", choices=["success", "fail"], help="Outcome")

    p_gate = sub.add_parser("gate", help="Judge awards a gate bonus for exceptional contribution")
    p_gate.add_argument("agent", help="Agent name")
    p_gate.add_argument("reason", help="Why this contribution deserves a gate bonus")
    p_gate.add_argument("--rt", default="", help="Roundtable ID")

    p_outcome = sub.add_parser("outcome-bonus", help="Award bonus to agents whose RT proposal was implemented")
    p_outcome.add_argument("agents", help="Comma-separated agent names")
    p_outcome.add_argument("--rt", default="", help="Roundtable ID")
    p_outcome.add_argument("--desc", default="", help="Description of what was implemented")

    p_selfdet = sub.add_parser("self-determined", help="Check if agent qualifies for self-determined evolution")
    p_selfdet.add_argument("agent", help="Agent name")

    args = parser.parse_args()

    if args.command == "score":
        valid = {0, 1, 2, 3, 10}
        for val, name in [(args.novelty, "novelty"), (args.accuracy, "accuracy"),
                          (args.impact, "impact"), (args.challenge, "challenge")]:
            if val not in valid:
                print(json.dumps({"error": f"{name} must be 0, 1, 2, 3, or 10 — got {val}"}))
                sys.exit(1)
        result = score_agent(args.agent, args.novelty, args.accuracy, args.impact, args.challenge, args.rt)
        print(json.dumps(result))
    elif args.command == "deduct-fee":
        result = deduct_entry_fee(args.agent, args.fee, args.rt)
        print(json.dumps(result))
    elif args.command == "leaderboard":
        board = get_leaderboard()
        print(json.dumps(board, indent=2))
    elif args.command == "check":
        at_risk = check_underperformers()
        print(json.dumps({"at_risk": at_risk}))
    elif args.command == "balances":
        balances = get_spark_balances()
        print(json.dumps(balances, indent=2))
    elif args.command == "promote":
        result = promote_tier(args.agent)
        print(json.dumps(result))
    elif args.command == "pitch":
        result = pitch_venture(args.agent, args.tier, args.idea, args.rt)
        print(json.dumps(result))
    elif args.command == "resolve":
        result = resolve_venture(args.agent, args.venture_id, args.outcome == "success")
        print(json.dumps(result))
    elif args.command == "gate":
        result = award_gate_bonus(args.agent, args.reason, args.rt)
        print(json.dumps(result))
    elif args.command == "outcome-bonus":
        agents = [a.strip() for a in args.agents.split(",")]
        results = award_rt_outcome_bonus(agents, args.rt, args.desc)
        print(json.dumps(results, indent=2))
    elif args.command == "self-determined":
        result = check_self_determined(args.agent)
        print(json.dumps(result))
    else:
        parser.print_help()
