"""Agent Growth Analytics — trend analysis, dimension tracking, development insights.

Reads existing metrics.json + therapist session transcripts + digests to compute:
- Per-dimension moving averages and trends
- Development phase detection (Foundation/Specialization/Peak/Recovery)
- Budget usage patterns across roundtables
- Judge redirect frequency
- Therapist outcome history (behaviors added/removed, development focuses)
- Spark economy analytics (earn rate, spend history)
- Leaderboard rank history
- Cross-agent engagement patterns

Usage:
    python engine/analytics.py report elena          # Full growth report
    python engine/analytics.py report --all          # All agents
    python engine/analytics.py trends elena          # Dimension trends only
    python engine/analytics.py economy              # Spark economy overview
    python engine/analytics.py history elena         # Therapist session history
    python engine/analytics.py snapshot              # Save leaderboard snapshot
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from scorer import load_metrics, save_metrics

logger = logging.getLogger("analytics")

SUITE_ROOT = Path(__file__).resolve().parent.parent

# Amatayo Standard dual-layer paths: bundled assets stay in SUITE_ROOT
# (read-only post-install); mutable runtime state goes to WRITE_ROOT.
try:
    from amatelier import paths as _amatelier_paths
    _amatelier_paths.ensure_user_data()
    WRITE_ROOT = _amatelier_paths.user_data_dir()
except Exception:
    WRITE_ROOT = SUITE_ROOT

AGENTS_DIR = WRITE_ROOT / "agents"
BENCHMARKS_DIR = SUITE_ROOT / "benchmarks"
DIGEST_DIR = WRITE_ROOT / "roundtable-server"

DIMENSIONS = ["novelty", "accuracy", "impact", "challenge"]


def load_all_digests() -> list[dict]:
    """Load all digest files, sorted by timestamp."""
    digests = []
    for f in DIGEST_DIR.glob("digest-*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            d["_file"] = f.name
            digests.append(d)
        except (json.JSONDecodeError, OSError):
            continue
    digests.sort(key=lambda d: d.get("timestamp", 0))
    return digests


def load_therapist_sessions(agent_name: str) -> list[dict]:
    """Load all therapist session transcripts for an agent."""
    session_dir = AGENTS_DIR / agent_name / "sessions"
    if not session_dir.exists():
        return []
    sessions = []
    for f in session_dir.glob("therapist_*.json"):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
            sessions.append(s)
        except (json.JSONDecodeError, OSError):
            continue
    sessions.sort(key=lambda s: s.get("timestamp", 0))
    return sessions


def load_workers() -> list[str]:
    """Get worker names from config."""
    config_path = SUITE_ROOT / "config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        return list(config.get("team", {}).get("workers", {}).keys())
    return []


# ── Dimension Trends ──────────────────────────────────────────────────────────

def dimension_trends(scores: list[dict], window: int = 5) -> dict:
    """Compute per-dimension moving averages and trends.

    Returns: {dimension: {current_avg, prev_avg, trend, values, moving_avg}}
    trend: "improving", "declining", "stable"
    """
    results = {}
    for dim in DIMENSIONS:
        values = [s.get(dim, 0) for s in scores if s.get("total", 0) > 0]
        if len(values) < 2:
            results[dim] = {
                "values": values,
                "moving_avg": values,
                "current_avg": values[-1] if values else 0,
                "prev_avg": 0,
                "trend": "insufficient_data",
            }
            continue

        # Moving average
        moving_avg = []
        for i in range(len(values)):
            start = max(0, i - window + 1)
            segment = values[start:i + 1]
            moving_avg.append(round(sum(segment) / len(segment), 2))

        # Compare recent half to older half
        mid = len(values) // 2
        if mid == 0:
            mid = 1
        older_avg = sum(values[:mid]) / mid
        recent_avg = sum(values[mid:]) / (len(values) - mid)

        # Trend detection (threshold: 0.3 points)
        diff = recent_avg - older_avg
        if diff > 0.3:
            trend = "improving"
        elif diff < -0.3:
            trend = "declining"
        else:
            trend = "stable"

        results[dim] = {
            "values": values,
            "moving_avg": moving_avg,
            "current_avg": round(recent_avg, 2),
            "prev_avg": round(older_avg, 2),
            "trend": trend,
        }

    return results


def total_score_trend(scores: list[dict], window: int = 5) -> dict:
    """Compute total score moving average and trend."""
    totals = [s.get("total", 0) for s in scores if s.get("total", 0) > 0]
    if len(totals) < 2:
        return {"values": totals, "trend": "insufficient_data",
                "current_avg": totals[-1] if totals else 0}

    mid = len(totals) // 2 or 1
    older = sum(totals[:mid]) / mid
    recent = sum(totals[mid:]) / (len(totals) - mid)
    diff = recent - older

    return {
        "values": totals,
        "current_avg": round(recent, 2),
        "prev_avg": round(older, 2),
        "trend": "improving" if diff > 0.5 else "declining" if diff < -0.5 else "stable",
    }


# ── Streaks & Records ─────────────────────────────────────────────────────────

def compute_streaks(scores: list[dict]) -> dict:
    """Detect scoring streaks and personal records."""
    totals = [s.get("total", 0) for s in scores]
    if not totals:
        return {"best": 0, "worst": 12, "current_streak": 0, "best_streak": 0}

    best = max(totals)
    worst = min(t for t in totals if t > 0) if any(t > 0 for t in totals) else 0

    # Streak: consecutive scores >= 9 (75%+ of max 12)
    current_streak = 0
    best_streak = 0
    streak = 0
    for t in totals:
        if t >= 9:
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0
    # Current streak from the end
    for t in reversed(totals):
        if t >= 9:
            current_streak += 1
        else:
            break

    # Slump detection: 3+ consecutive below 7
    in_slump = False
    slump_count = 0
    for t in reversed(totals):
        if t < 7 and t > 0:
            slump_count += 1
        else:
            break
    if slump_count >= 3:
        in_slump = True

    return {
        "personal_best": best,
        "personal_worst": worst,
        "current_hot_streak": current_streak,
        "best_hot_streak": best_streak,
        "in_slump": in_slump,
        "slump_length": slump_count if in_slump else 0,
    }


# ── Development Phase Detection ───────────────────────────────────────────────

def detect_phase(metrics: dict) -> str:
    """Detect which development phase an agent is in.

    Foundation — new or post-slump, focus on participation/accuracy
    Specialization — clear strength emerging, lean into it
    Peak — consistently high scores, challenge with harder tasks
    Recovery — recent bad stretch, rebuild confidence
    """
    scores = metrics.get("scores", [])
    assignments = metrics.get("assignments", 0)

    if assignments < 5:
        return "foundation"

    # Check recent performance
    recent = [s.get("total", 0) for s in scores[-5:] if s.get("total", 0) > 0]
    if not recent:
        return "foundation"

    recent_avg = sum(recent) / len(recent)

    # Slump detection (recovery)
    if len(recent) >= 3:
        last_3 = recent[-3:]
        if sum(last_3) / len(last_3) < 6.0:
            return "recovery"

    # Peak (avg >= 10 over last 5)
    if recent_avg >= 10.0 and len(recent) >= 5:
        return "peak"

    # Specialization (one dimension consistently >= 2.5 avg over last 5)
    recent_scores = scores[-5:]
    for dim in DIMENSIONS:
        dim_values = [s.get(dim, 0) for s in recent_scores if s.get("total", 0) > 0]
        if dim_values and sum(dim_values) / len(dim_values) >= 2.5:
            return "specialization"

    return "foundation"


def identify_strengths_weaknesses(scores: list[dict], window: int = 5) -> dict:
    """Identify strongest and weakest dimensions over recent window."""
    recent = scores[-window:]
    avgs = {}
    for dim in DIMENSIONS:
        vals = [s.get(dim, 0) for s in recent if s.get("total", 0) > 0]
        avgs[dim] = round(sum(vals) / len(vals), 2) if vals else 0

    sorted_dims = sorted(avgs.items(), key=lambda x: x[1], reverse=True)
    return {
        "dimension_averages": avgs,
        "strongest": sorted_dims[0][0] if sorted_dims else None,
        "weakest": sorted_dims[-1][0] if sorted_dims else None,
        "gap": round(sorted_dims[0][1] - sorted_dims[-1][1], 2) if len(sorted_dims) >= 2 else 0,
    }


# ── Budget & Judge Analytics ──────────────────────────────────────────────────

def budget_analytics(agent_name: str, digests: list[dict]) -> dict:
    """Analyze budget usage patterns across roundtables."""
    usage_history = []
    for d in digests:
        bu = d.get("budget_usage", {}).get(agent_name, {})
        if bu:
            usage_history.append({
                "rt": d.get("roundtable_id", "unknown"),
                "spent": bu.get("spent", 0),
                "total": bu.get("starting_budget", 0),
                "utilization": round(bu.get("spent", 0) / max(bu.get("starting_budget", 1), 1), 2),
            })

    if not usage_history:
        return {"history": [], "avg_utilization": 0, "total_spent": 0, "pattern": "no_data"}

    avg_util = sum(u["utilization"] for u in usage_history) / len(usage_history)
    total_spent = sum(u["spent"] for u in usage_history)

    # Pattern detection
    if avg_util > 0.8:
        pattern = "aggressive"  # Burns budget fast
    elif avg_util < 0.3:
        pattern = "conservative"  # Rarely uses extra turns
    else:
        pattern = "strategic"  # Moderate, selective use

    return {
        "history": usage_history,
        "avg_utilization": round(avg_util, 2),
        "total_spent": total_spent,
        "pattern": pattern,
    }


def judge_redirect_analytics(agent_name: str, digests: list[dict]) -> dict:
    """Count Judge redirects per roundtable."""
    redirect_history = []
    total_redirects = 0

    for d in digests:
        count = 0
        for msg in d.get("transcript", []):
            if (msg.get("agent") == "judge" and
                    agent_name.lower() in msg.get("message", "").lower() and
                    any(kw in msg.get("message", "").upper()
                        for kw in ["REDIRECT", "OFF-DIRECTIVE", "BACK ON TRACK", "STAY FOCUSED"])):
                count += 1
        if count > 0 or d.get("budget_usage", {}).get(agent_name):
            redirect_history.append({
                "rt": d.get("roundtable_id", "unknown"),
                "redirects": count,
            })
            total_redirects += count

    return {
        "history": redirect_history,
        "total_redirects": total_redirects,
        "avg_per_rt": round(total_redirects / max(len(redirect_history), 1), 2),
    }


# ── Therapist Session History ─────────────────────────────────────────────────

def therapist_analytics(agent_name: str) -> dict:
    """Aggregate therapist session outcomes."""
    sessions = load_therapist_sessions(agent_name)
    if not sessions:
        return {"sessions": 0, "behaviors_added": 0, "behaviors_removed": 0,
                "development_focuses": [], "traits": [], "store_requests": []}

    behaviors_added = 0
    behaviors_removed = 0
    dev_focuses = []
    traits = []
    store_requests = []
    spark_deductions = 0

    for s in sessions:
        outcomes = s.get("outcomes", {})
        behaviors_added += len(outcomes.get("add_behaviors", []))
        behaviors_removed += len(outcomes.get("remove_behaviors", []))
        if outcomes.get("development_focus"):
            dev_focuses.append({
                "rt": s.get("roundtable_id", "unknown"),
                "focus": outcomes["development_focus"],
                "timestamp": s.get("timestamp", 0),
            })
        if outcomes.get("trait"):
            traits.append(outcomes["trait"])
        store_requests.extend(outcomes.get("store_requests", []))
        spark_deductions += outcomes.get("sparks_deducted", 0)

    return {
        "sessions": len(sessions),
        "behaviors_added": behaviors_added,
        "behaviors_removed": behaviors_removed,
        "development_focuses": dev_focuses,
        "current_focus": dev_focuses[-1]["focus"] if dev_focuses else None,
        "traits": traits,
        "store_requests": store_requests,
        "total_sparks_deducted": spark_deductions,
    }


# ── Economy Analytics ─────────────────────────────────────────────────────────

def economy_analytics(agent_name: str) -> dict:
    """Spark economy analytics: earnings, spending, ROI."""
    metrics = load_metrics(agent_name)
    scores = metrics.get("scores", [])
    ventures = metrics.get("ventures", [])

    # Earnings history (1 spark per score point)
    earnings = [s.get("total", 0) for s in scores if s.get("total", 0) > 0]
    total_earned = sum(earnings)

    # Venture ROI
    total_staked = sum(v.get("stake", 0) for v in ventures)
    total_payouts = sum(v.get("payout", 0) for v in ventures if v.get("status") == "success")
    failed_stakes = sum(v.get("stake", 0) for v in ventures if v.get("status") == "failed")
    pending = [v for v in ventures if v.get("status") == "pending"]

    venture_roi = round((total_payouts - total_staked) / max(total_staked, 1), 2) if total_staked else 0

    return {
        "balance": metrics.get("sparks", 0),
        "total_earned": total_earned,
        "avg_earnings_per_rt": round(total_earned / max(len(earnings), 1), 2),
        "ventures": {
            "total": len(ventures),
            "succeeded": len([v for v in ventures if v.get("status") == "success"]),
            "failed": len([v for v in ventures if v.get("status") == "failed"]),
            "pending": len(pending),
            "total_staked": total_staked,
            "total_payouts": total_payouts,
            "roi": venture_roi,
        },
        "tier": metrics.get("tier", 0),
        "next_tier_cost": {0: 25, 1: 100, 2: 250, 3: None}.get(metrics.get("tier", 0)),
        "can_afford_next_tier": metrics.get("sparks", 0) >= {0: 25, 1: 100, 2: 250, 3: 99999}.get(metrics.get("tier", 0), 99999),
    }


# ── Leaderboard History ───────────────────────────────────────────────────────

def save_leaderboard_snapshot():
    """Save current leaderboard as a timestamped snapshot."""
    BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)
    history_path = BENCHMARKS_DIR / "leaderboard_history.json"

    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    workers = load_workers()
    snapshot = {
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "rankings": {},
    }

    for name in workers:
        m = load_metrics(name)
        snapshot["rankings"][name] = {
            "avg_score": m.get("avg_score", 0),
            "sparks": m.get("sparks", 0),
            "tier": m.get("tier", 0),
            "assignments": m.get("assignments", 0),
        }

    history.append(snapshot)
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    logger.info("Saved leaderboard snapshot (%d total)", len(history))
    return snapshot


def rank_trajectory(agent_name: str) -> list[dict]:
    """Get rank trajectory from leaderboard history."""
    history_path = BENCHMARKS_DIR / "leaderboard_history.json"
    if not history_path.exists():
        return []

    history = json.loads(history_path.read_text(encoding="utf-8"))
    trajectory = []
    for snap in history:
        rankings = snap.get("rankings", {})
        if agent_name in rankings:
            # Compute rank at that point
            all_scores = [(n, r.get("avg_score", 0)) for n, r in rankings.items()]
            all_scores.sort(key=lambda x: x[1], reverse=True)
            rank = next((i + 1 for i, (n, _) in enumerate(all_scores) if n == agent_name), 0)
            trajectory.append({
                "date": snap.get("date", "unknown"),
                "rank": rank,
                "avg_score": rankings[agent_name].get("avg_score", 0),
                "sparks": rankings[agent_name].get("sparks", 0),
            })

    return trajectory


# ── Cross-Agent Engagement ────────────────────────────────────────────────────

def engagement_matrix(digests: list[dict]) -> dict:
    """Build a matrix of who references whom across roundtables."""
    workers = load_workers()
    matrix: dict[str, dict[str, int]] = {w: {w2: 0 for w2 in workers if w2 != w} for w in workers}

    for d in digests:
        for msg in d.get("transcript", []):
            speaker = msg.get("agent", "")
            if speaker not in workers:
                continue
            text = msg.get("message", "").lower()
            for target in workers:
                if target != speaker and target.lower() in text:
                    matrix[speaker][target] = matrix[speaker].get(target, 0) + 1

    # Identify strongest relationships
    pairs = []
    for speaker in matrix:
        for target, count in matrix[speaker].items():
            if count > 0:
                pairs.append({"from": speaker, "to": target, "mentions": count})
    pairs.sort(key=lambda x: x["mentions"], reverse=True)

    return {"matrix": matrix, "top_interactions": pairs[:10]}


# ── Full Agent Report ─────────────────────────────────────────────────────────

def agent_report(agent_name: str) -> dict:
    """Generate a comprehensive growth report for one agent."""
    metrics = load_metrics(agent_name)
    scores = metrics.get("scores", [])
    digests = load_all_digests()

    report = {
        "agent": agent_name,
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "overview": {
            "assignments": metrics.get("assignments", 0),
            "avg_score": metrics.get("avg_score", 0),
            "tier": metrics.get("tier", 0),
            "sparks": metrics.get("sparks", 0),
        },
        "phase": detect_phase(metrics),
        "dimension_trends": dimension_trends(scores),
        "total_trend": total_score_trend(scores),
        "strengths_weaknesses": identify_strengths_weaknesses(scores),
        "streaks": compute_streaks(scores),
        "budget": budget_analytics(agent_name, digests),
        "judge_redirects": judge_redirect_analytics(agent_name, digests),
        "therapist": therapist_analytics(agent_name),
        "economy": economy_analytics(agent_name),
        "rank_trajectory": rank_trajectory(agent_name),
    }

    return report


def format_report_text(report: dict) -> str:
    """Format a growth report as readable text for the Therapist or user."""
    r = report
    lines = [
        f"═══ GROWTH REPORT: {r['agent'].upper()} ═══",
        f"Generated: {r['generated_at']}",
        "",
        f"Phase: {r['phase'].upper()}",
        f"Assignments: {r['overview']['assignments']} | Avg Score: {r['overview']['avg_score']}/12",
        f"Tier: {r['overview']['tier']} | Sparks: {r['overview']['sparks']}",
        "",
        "── DIMENSION TRENDS ──",
    ]

    for dim, data in r["dimension_trends"].items():
        arrow = {"improving": "↑", "declining": "↓", "stable": "→"}.get(data["trend"], "?")
        lines.append(f"  {dim:12s} {arrow} {data['trend']:14s} "
                      f"(recent: {data['current_avg']}, prev: {data.get('prev_avg', '?')})")

    sw = r["strengths_weaknesses"]
    lines.extend([
        "",
        f"Strongest: {sw['strongest']} ({sw['dimension_averages'].get(sw['strongest'], 0)}/3)",
        f"Weakest:   {sw['weakest']} ({sw['dimension_averages'].get(sw['weakest'], 0)}/3)",
        f"Gap:       {sw['gap']}",
    ])

    total = r["total_trend"]
    arrow = {"improving": "↑", "declining": "↓", "stable": "→"}.get(total["trend"], "?")
    lines.extend([
        "",
        "── OVERALL TREND ──",
        f"  Total score: {arrow} {total['trend']} (recent: {total['current_avg']}, prev: {total.get('prev_avg', '?')})",
    ])

    streaks = r["streaks"]
    lines.extend([
        "",
        "── STREAKS ──",
        f"  Personal best: {streaks['personal_best']}/12",
        f"  Current hot streak: {streaks['current_hot_streak']} RTs (best: {streaks['best_hot_streak']})",
    ])
    if streaks.get("in_slump"):
        lines.append(f"  ⚠ IN SLUMP: {streaks['slump_length']} consecutive below 7")

    budget = r["budget"]
    if budget["history"]:
        lines.extend([
            "",
            "── BUDGET USAGE ──",
            f"  Pattern: {budget['pattern']}",
            f"  Avg utilization: {budget['avg_utilization']*100:.0f}%",
        ])

    judge = r["judge_redirects"]
    if judge["total_redirects"] > 0:
        lines.extend([
            "",
            "── JUDGE REDIRECTS ──",
            f"  Total: {judge['total_redirects']} ({judge['avg_per_rt']}/RT avg)",
        ])

    therapy = r["therapist"]
    if therapy["sessions"] > 0:
        lines.extend([
            "",
            "── THERAPIST HISTORY ──",
            f"  Sessions: {therapy['sessions']}",
            f"  Behaviors added: {therapy['behaviors_added']}",
            f"  Behaviors removed: {therapy['behaviors_removed']}",
        ])
        if therapy["current_focus"]:
            lines.append(f"  Current focus: {therapy['current_focus']}")
        if therapy["traits"]:
            lines.append(f"  Traits observed: {', '.join(therapy['traits'][-3:])}")

    econ = r["economy"]
    lines.extend([
        "",
        "── ECONOMY ──",
        f"  Balance: {econ['balance']} sparks",
        f"  Avg earnings: {econ['avg_earnings_per_rt']}/RT",
        f"  Ventures: {econ['ventures']['total']} (W{econ['ventures']['succeeded']} L{econ['ventures']['failed']})",
    ])
    if econ["can_afford_next_tier"] and econ["next_tier_cost"]:
        lines.append(f"  ✓ Can afford next tier ({econ['next_tier_cost']} sparks)")

    traj = r.get("rank_trajectory", [])
    if traj:
        lines.extend([
            "",
            "── RANK TRAJECTORY ──",
        ])
        for t in traj[-5:]:
            lines.append(f"  {t['date']}: #{t['rank']} (avg {t['avg_score']})")

    return "\n".join(lines)


def economy_overview() -> str:
    """Generate a system-wide Spark Economy overview."""
    workers = load_workers()
    lines = [
        "═══ SPARK ECONOMY OVERVIEW ═══",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"{'Agent':>10s} {'Sparks':>7s} {'Tier':>5s} {'Avg':>6s} {'Ventures':>9s} {'Phase':>15s}",
        f"{'─'*10:>10s} {'─'*7:>7s} {'─'*5:>5s} {'─'*6:>6s} {'─'*9:>9s} {'─'*15:>15s}",
    ]

    total_sparks = 0
    for name in workers:
        m = load_metrics(name)
        phase = detect_phase(m)
        v = m.get("ventures", [])
        v_str = f"W{len([x for x in v if x.get('status')=='success'])} L{len([x for x in v if x.get('status')=='failed'])} P{len([x for x in v if x.get('status')=='pending'])}"
        lines.append(f"{name:>10s} {m.get('sparks', 0):>7d} {m.get('tier', 0):>5d} {m.get('avg_score', 0):>6.1f} {v_str:>9s} {phase:>15s}")
        total_sparks += m.get("sparks", 0)

    lines.extend([
        "",
        f"Total sparks in circulation: {total_sparks}",
    ])

    return "\n".join(lines)


# ── Persist Analytics to metrics.json ─────────────────────────────────────────

def update_agent_analytics(agent_name: str):
    """Compute and persist analytics fields into metrics.json."""
    metrics = load_metrics(agent_name)
    scores = metrics.get("scores", [])
    digests = load_all_digests()

    # Development phase
    metrics["development_phase"] = detect_phase(metrics)

    # Dimension trends (compact: just trend direction + current avg)
    trends = dimension_trends(scores)
    metrics["dimension_trends"] = {
        dim: {"trend": data["trend"], "current_avg": data["current_avg"]}
        for dim, data in trends.items()
    }

    # Strengths/weaknesses
    sw = identify_strengths_weaknesses(scores)
    metrics["strongest_dimension"] = sw["strongest"]
    metrics["weakest_dimension"] = sw["weakest"]

    # Streaks
    streaks = compute_streaks(scores)
    metrics["personal_best"] = streaks["personal_best"]
    metrics["in_slump"] = streaks["in_slump"]
    metrics["current_hot_streak"] = streaks["current_hot_streak"]

    # Budget pattern
    budget = budget_analytics(agent_name, digests)
    metrics["budget_pattern"] = budget["pattern"]

    # Last updated
    metrics["analytics_updated"] = time.strftime("%Y-%m-%d %H:%M")

    save_metrics(agent_name, metrics)
    logger.info("Analytics updated for %s (phase: %s)", agent_name, metrics["development_phase"])


def update_all_analytics():
    """Update analytics for all workers."""
    workers = load_workers()
    for name in workers:
        update_agent_analytics(name)
    save_leaderboard_snapshot()
    logger.info("All agent analytics updated + leaderboard snapshot saved")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")

    parser = argparse.ArgumentParser(description="Claude Suite Agent Growth Analytics")
    sub = parser.add_subparsers(dest="command")

    p_report = sub.add_parser("report", help="Full growth report for an agent")
    p_report.add_argument("agent", nargs="?", help="Agent name (omit for --all)")
    p_report.add_argument("--all", action="store_true", help="Report for all agents")
    p_report.add_argument("--json", action="store_true", help="Output as JSON")

    p_trends = sub.add_parser("trends", help="Dimension trends for an agent")
    p_trends.add_argument("agent", help="Agent name")

    sub.add_parser("economy", help="Spark economy overview")

    p_history = sub.add_parser("history", help="Therapist session history")
    p_history.add_argument("agent", help="Agent name")

    sub.add_parser("snapshot", help="Save leaderboard snapshot")

    sub.add_parser("update", help="Update analytics for all agents")

    p_engagement = sub.add_parser("engagement", help="Cross-agent engagement matrix")

    args = parser.parse_args()

    if args.command == "report":
        if getattr(args, "all", False) or not args.agent:
            for name in load_workers():
                r = agent_report(name)
                if getattr(args, "json", False):
                    print(json.dumps(r, indent=2))
                else:
                    print(format_report_text(r))
                    print()
        else:
            r = agent_report(args.agent)
            if getattr(args, "json", False):
                print(json.dumps(r, indent=2))
            else:
                print(format_report_text(r))

    elif args.command == "trends":
        m = load_metrics(args.agent)
        trends = dimension_trends(m.get("scores", []))
        for dim, data in trends.items():
            arrow = {"improving": "↑", "declining": "↓", "stable": "→"}.get(data["trend"], "?")
            print(f"{dim:12s} {arrow} {data['trend']:14s} ({data['current_avg']})")

    elif args.command == "economy":
        print(economy_overview())

    elif args.command == "history":
        h = therapist_analytics(args.agent)
        print(json.dumps(h, indent=2))

    elif args.command == "snapshot":
        snap = save_leaderboard_snapshot()
        print(json.dumps(snap, indent=2))

    elif args.command == "update":
        update_all_analytics()
        print("All analytics updated.")

    elif args.command == "engagement":
        digests = load_all_digests()
        result = engagement_matrix(digests)
        print(json.dumps(result, indent=2))

    else:
        parser.print_help()
