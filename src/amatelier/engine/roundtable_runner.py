"""Roundtable Runner — autonomous orchestrator with structured debate.

Usage:
    python engine/roundtable_runner.py --topic "Topic here" --briefing briefing-001.md
    python engine/roundtable_runner.py --topic "Topic here" --briefing briefing-001.md --budget 5
    python engine/roundtable_runner.py --topic "Topic here" --briefing briefing-001.md --workers elena,marcus --max-rounds 4

Debate structure per round:
  1. SPEAK PHASE — each worker called sequentially (guaranteed, free)
  2. REBUTTAL PHASE — each worker called in reverse order (guaranteed, free)
  3. FLOOR PHASE — workers with remaining budget can contribute or PASS
  4. Haiku round summary (context anchor for next round)

After all rounds: auto-score -> leaderboard -> Therapist debrief (exit interview).
The Therapist updates each agent's MEMORY.md and learned behaviors automatically.

Budget: each agent gets N extra turns (default 3) for the entire roundtable.
They can burn them all in round 1 or spread them across rounds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from steward_dispatch import (
    parse_requests, strip_requests, format_result,
    StewardBudget, StewardTask, StewardLog,
    load_registered_files,
)

logger = logging.getLogger("runner")

SUITE_ROOT = Path(__file__).resolve().parent.parent

# Amatayo Standard dual-layer paths: bundled assets stay in SUITE_ROOT
# (read-only post-install); mutable runtime state goes to WRITE_ROOT.
try:
    from amatelier import paths as _amatelier_paths
    _amatelier_paths.ensure_user_data()
    WRITE_ROOT = _amatelier_paths.user_data_dir()
except Exception:
    WRITE_ROOT = SUITE_ROOT

# Workspace root = where the user runs commands. Defaults to .../skills/claude-suite
# ancestor at +3 (skill -> skills -> .claude -> project). Override with
# AMATELIER_WORKSPACE env var when the install layout differs.
_env_workspace = os.environ.get("AMATELIER_WORKSPACE", "").strip()
if _env_workspace:
    WORKSPACE_ROOT = Path(_env_workspace).resolve()
else:
    WORKSPACE_ROOT = SUITE_ROOT.parent.parent.parent
DB_CLIENT = SUITE_ROOT / "roundtable-server" / "db_client.py"
CLAUDE_AGENT = SUITE_ROOT / "engine" / "claude_agent.py"
GEMINI_AGENT = SUITE_ROOT / "engine" / "gemini_agent.py"
CONFIG_PATH = SUITE_ROOT / "config.json"


def _load_env() -> dict[str, str]:
    """Load .env files into a dict. Checks suite root and workspace root."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    for env_path in [SUITE_ROOT / ".env", WORKSPACE_ROOT / ".env"]:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                val = val.strip().strip("'\"")
                env.setdefault(key.strip(), val)
    return env


# Default model mapping — overridden at runtime by tier from metrics.json
DEFAULT_MODELS = {
    "elena": "sonnet",
    "marcus": "sonnet",
    "clare": "haiku",
    "simon": "haiku",
}

# Model upgrades are request-based — no automatic tier overrides

DEFAULT_WORKERS = ["elena", "marcus", "clare", "simon"]
AGENTS_DIR = WRITE_ROOT / "agents"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_agent_model(agent_name: str) -> str:
    """Read agent's model from config. Upgrades are request-based, not automatic."""
    config = load_config()
    workers = config.get("team", {}).get("workers", {})
    agent_cfg = workers.get(agent_name, {})
    model_str = agent_cfg.get("model", "")
    if "opus" in model_str:
        return "opus"
    elif "sonnet" in model_str:
        return "sonnet"
    elif "haiku" in model_str:
        return "haiku"
    return DEFAULT_MODELS.get(agent_name, "sonnet")


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Word-set Jaccard similarity between two texts."""
    import string
    trans = str.maketrans("", "", string.punctuation)
    words_a = set(text_a.lower().translate(trans).split())
    words_b = set(text_b.lower().translate(trans).split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union) if union else 0.0


def db_cmd(*args: str, retries: int = 3, retry_delay: float = 2.0) -> dict:
    """Run a db_client.py command and return parsed JSON.

    Retries on transient failures (SQLite locks, Windows file contention).
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(
                [sys.executable, str(DB_CLIENT), *args],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            if result.returncode != 0:
                last_err = RuntimeError(
                    f"db_client {args[0]} failed (exit {result.returncode}): "
                    f"stderr={result.stderr!r} stdout={result.stdout[:200]!r}"
                )
                if attempt < retries:
                    logger.warning("db_cmd %s attempt %d/%d failed, retrying in %.1fs: %s",
                                   args[0], attempt, retries, retry_delay, last_err)
                    time.sleep(retry_delay)
                    continue
                raise last_err
            return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            last_err = RuntimeError(f"db_client {args[0]} timed out (attempt {attempt})")
            if attempt < retries:
                logger.warning("db_cmd %s timed out (attempt %d/%d), retrying...",
                               args[0], attempt, retries)
                time.sleep(retry_delay)
                continue
            raise last_err
    raise last_err  # Should not reach here


def get_latest_messages(agent_name: str = "runner") -> list[dict]:
    """Listen as the runner to get new messages.

    Returns empty list on transient failure instead of crashing the RT.
    """
    try:
        result = db_cmd("listen", agent_name)
        return result.get("messages", [])
    except RuntimeError as e:
        logger.warning("get_latest_messages failed (non-fatal, returning empty): %s", e)
        return []


def wait_for_single_speaker(
    speaker: str,
    timeout_seconds: int = 200,
    poll_interval: int = 3,
) -> tuple[bool, list[dict]]:
    """Wait for a single agent to post. Returns (spoke, all_new_messages)."""
    start = time.time()
    all_messages: list[dict] = []

    while time.time() - start < timeout_seconds:
        new = get_latest_messages()
        if new:
            all_messages.extend(new)
            for msg in new:
                if msg["agent"] == speaker:
                    return True, all_messages
        time.sleep(poll_interval)

    logger.warning("Timeout waiting for %s (%ds)", speaker, timeout_seconds)
    return False, all_messages


def is_pass(messages: list[dict], speaker: str) -> bool:
    """Check if the speaker's MOST RECENT message is a PASS.

    Iterates backwards so we check the latest message, not a stale PASS
    from a prior round.
    """
    for msg in reversed(messages):
        if msg["agent"] == speaker:
            text = msg.get("message", "").strip()
            return text.upper() == "PASS" or (len(text) < 30 and text.upper().startswith("PASS"))
    return False


def check_convergence(messages: list[dict]) -> str | None:
    """Check if Judge posted a CONVERGED signal."""
    for msg in messages:
        if msg["agent"] == "judge" and "CONVERGED:" in msg.get("message", ""):
            return msg["message"]
    return None


def build_digest(
    topic: str,
    rt_id: str,
    rounds_completed: int,
    transcript: list[dict],
    convergence_reason: str | None,
    budget_usage: dict[str, dict] | None = None,
) -> dict:
    """Build a structured digest from the transcript."""
    agent_counts: dict[str, int] = {}
    for msg in transcript:
        agent = msg["agent"]
        agent_counts[agent] = agent_counts.get(agent, 0) + 1

    judge_msgs = [m["message"] for m in transcript if m["agent"] == "judge"]

    last_worker_msgs: dict[str, str] = {}
    for msg in transcript:
        if msg["agent"] not in ("assistant", "runner", "judge"):
            last_worker_msgs[msg["agent"]] = msg["message"]

    digest = {
        "roundtable_id": rt_id,
        "topic": topic,
        "rounds": rounds_completed,
        "total_messages": len(transcript),
        "timestamp": time.time(),
        "contributions": agent_counts,
        "converged": convergence_reason is not None,
        "convergence_reason": convergence_reason,
        "judge_interventions": len(judge_msgs),
        "judge_messages": judge_msgs,
        "final_positions": last_worker_msgs,
        "transcript": transcript,
    }
    if budget_usage:
        digest["budget_usage"] = budget_usage
    return digest


def _summarize_round(round_num: int, round_messages: list[dict],
                     prior_state: str = "") -> str:
    """Call Haiku to produce a cumulative debate state, not just a round summary.

    Instead of a standalone round summary (lossy, stateless), this builds a
    running STATE OF THE DEBATE that carries forward across rounds. Each call
    receives the prior state and updates it with new round data.

    Structure:
      ESTABLISHED: Things the group has settled (with attribution)
      LIVE POSITIONS: Who holds what position right now (updated, not appended)
      OPEN QUESTIONS: What's unresolved (removed once answered)
      SHIFTS: What changed THIS round (reversals, concessions, new evidence)

    This means agents in round 3 still know what was established in round 1,
    not just what happened in round 2.
    """
    # Filter to substantive messages (skip runner signals)
    substantive = [m for m in round_messages
                   if m["agent"] not in ("runner", "assistant")
                   and not m.get("message", "").strip().upper() == "PASS"]

    if not substantive:
        return prior_state or f"Round {round_num}: No substantive contributions."

    transcript_text = "\n\n".join(
        f"[{m['agent']}]: {m['message']}" for m in substantive
    )

    if prior_state:
        state_context = f"""CURRENT DEBATE STATE (from rounds 1-{round_num - 1}):
{prior_state}

---
UPDATE the state above with this round's new information. Don't repeat — update in place.
Move resolved questions from OPEN QUESTIONS to ESTABLISHED.
Update LIVE POSITIONS if anyone changed their stance.
Remove OPEN QUESTIONS that were answered.
Only add to SHIFTS what actually changed this round."""
    else:
        state_context = "This is round 1 — create the initial debate state from scratch."

    prompt = f"""You are building a cumulative STATE OF THE DEBATE for a multi-round discussion. Participants will ONLY see your output — not the original messages. Accuracy matters: attribute every claim to a specific agent by name.

{state_context}

Produce the updated state using EXACTLY this structure:

**ESTABLISHED:** (claims the group accepts — who proved what, with evidence cited)
**LIVE POSITIONS:** (each agent's current stance — 1-2 sentences each, update if they moved)
**OPEN QUESTIONS:** (unresolved disputes — who disagrees with whom about what)
**SHIFTS THIS ROUND:** (what changed: reversals, concessions, new evidence, new challenges)

Rules:
- Under 400 words total
- Every claim attributed to a named agent
- If an agent reversed position, note it explicitly ("X conceded Y's point about Z")
- If a question from a prior round was answered, move it to ESTABLISHED
- LIVE POSITIONS must reflect each agent's CURRENT stance, not their original one

---
ROUND {round_num} TRANSCRIPT:

{transcript_text}"""

    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku",
             "--no-session-persistence", "--output-format", "text",
             "--disable-slash-commands", "--dangerously-skip-permissions",
             "--max-budget-usd", "5.00"],
            input=prompt, capture_output=True, text=True, timeout=120,
            cwd=str(WORKSPACE_ROOT), encoding="utf-8", errors="replace", env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        logger.warning("Haiku summarizer failed (exit %d), using fallback", result.returncode)
    except Exception as e:
        logger.warning("Haiku summarizer error: %s, using fallback", e)

    # Fallback: just list who spoke about what
    agents = sorted(set(m["agent"] for m in substantive))
    return f"Round {round_num}: {', '.join(agents)} contributed. See transcript for details."


def format_budget_status(budget: dict[str, int]) -> str:
    """Format budget as a readable string."""
    return ", ".join(f"{name}={remaining}" for name, remaining in budget.items())


def run_roundtable(
    topic: str,
    briefing_path: str,
    workers: list[str] | None = None,
    max_rounds: int | None = None,
    skip_naomi: bool = False,
    speaker_timeout: int = 200,
    budget_per_agent: int = 3,
    skip_post: bool = False,
) -> dict:
    """Run a complete roundtable with structured debate and return the digest."""
    config = load_config()
    workers = workers or DEFAULT_WORKERS
    max_rounds = max_rounds or config.get("roundtable", {}).get("max_rounds", 3)

    # Resolve briefing
    briefing_file = SUITE_ROOT / "roundtable-server" / briefing_path
    if not briefing_file.exists():
        briefing_file = Path(briefing_path)
    if not briefing_file.exists():
        raise FileNotFoundError(f"Briefing not found: {briefing_path}")

    briefing_text = briefing_file.read_text(encoding="utf-8")

    # Initialize Steward if briefing has registered files
    steward_cfg = config.get("steward", {})
    steward_enabled = steward_cfg.get("enabled", False)
    registered_files = load_registered_files(str(briefing_file)) if steward_enabled else []
    steward_log = StewardLog()
    if steward_enabled and registered_files:
        logger.info("Steward enabled: %d registered files", len(registered_files))
    elif steward_enabled:
        logger.info("Steward enabled but no registered files in briefing — Steward inactive this RT")
        steward_enabled = False

    # Build participant list
    all_workers = list(workers)
    if not skip_naomi and "naomi" not in workers:
        all_workers.append("naomi")
    participants = all_workers + ["judge"]

    # Initialize budget
    budget: dict[str, int] = {agent: budget_per_agent for agent in all_workers}
    budget_spent: dict[str, int] = {agent: 0 for agent in all_workers}

    # Initialize Steward budget (separate from floor budget)
    steward_budget = StewardBudget(
        all_workers,
        budget_per_agent=steward_cfg.get("budget_per_agent", 3),
    ) if steward_enabled else None

    # Apply purchased boosts and sync skill inventories
    try:
        from store import apply_boosts_for_rt
        boost_effects = apply_boosts_for_rt(all_workers)
        for agent, effects in boost_effects.items():
            if "extra_floor_turns" in effects:
                budget[agent] += effects["extra_floor_turns"]
                logger.info("Boost: %s gets +%d floor turns (total: %d)",
                            agent, effects["extra_floor_turns"], budget[agent])
    except Exception as e:
        boost_effects = {}
        logger.warning("Boost application failed (non-fatal): %s", e)

    try:
        from evolver import sync_skills_owned
        for agent in all_workers:
            sync_skills_owned(agent)
    except Exception as e:
        logger.warning("Skills sync failed (non-fatal): %s", e)

    # Generate session bridges — "last time you..." continuity for each agent
    try:
        from agent_memory import generate_session_bridge
        for agent in all_workers:
            bridge = generate_session_bridge(agent)
            if bridge:
                logger.info("Session bridge generated for %s (%d chars)", agent, len(bridge))
    except Exception as e:
        logger.warning("Session bridge generation failed (non-fatal): %s", e)

    logger.info("Opening roundtable: %s", topic)
    logger.info("Participants: %s", ", ".join(participants))
    logger.info("Budget per agent: %d extra turns", budget_per_agent)
    logger.info("Max rounds: %d", max_rounds)

    # 1. Open roundtable
    result = db_cmd("open", topic, ",".join(participants + ["runner"]))
    rt_id = result["roundtable_id"]
    logger.info("Roundtable opened: %s", rt_id)

    # 2. Join as runner
    db_cmd("join", "runner")

    # 3. Post briefing
    db_cmd("speak", "runner", f"BRIEFING:\n\n{briefing_text}")
    logger.info("Briefing posted (%d chars)", len(briefing_text))

    # 4. Launch agent processes
    agent_procs: dict[str, subprocess.Popen] = {}
    env = _load_env()

    def _launch_claude(agent_name: str, model: str) -> subprocess.Popen:
        logger.info("Launching %s (Claude %s)", agent_name, model)
        return subprocess.Popen(
            [sys.executable, str(CLAUDE_AGENT), "--agent", agent_name, "--model", model],
            cwd=str(WORKSPACE_ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def _launch_gemini(agent_name: str) -> subprocess.Popen:
        logger.info("Launching %s (Gemini Flash)", agent_name)
        return subprocess.Popen(
            [sys.executable, str(GEMINI_AGENT), "--agent", agent_name],
            cwd=str(WORKSPACE_ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def _check_and_restart(agent_name: str) -> bool:
        proc = agent_procs.get(agent_name)
        if proc is None or proc.poll() is None:
            return False
        exit_code = proc.returncode
        stderr_out = ""
        try:
            stderr_out = proc.stderr.read().decode("utf-8", errors="replace")[:500] if proc.stderr else ""
        except Exception:
            pass
        logger.error("Agent %s crashed (exit %d): %s", agent_name, exit_code, stderr_out)
        # Point to the detailed error log for Gemini issues
        if agent_name == "naomi":
            gemini_log = WRITE_ROOT / "roundtable-server" / "logs" / "gemini_errors.log"
            if gemini_log.exists():
                logger.error("Gemini error details: %s", gemini_log)
            agent_procs[agent_name] = _launch_gemini(agent_name)
        elif agent_name == "judge":
            agent_procs[agent_name] = _launch_claude(agent_name, "sonnet")
        else:
            model = resolved_models.get(agent_name, resolve_agent_model(agent_name))
            agent_procs[agent_name] = _launch_claude(agent_name, model)
        logger.info("Restarted %s", agent_name)
        return True

    # Resolve models from tier
    resolved_models: dict[str, str] = {}
    for worker in workers:
        if worker == "naomi":
            continue
        resolved_models[worker] = resolve_agent_model(worker)
    logger.info("Resolved models: %s", ", ".join(f"{k}={v}" for k, v in resolved_models.items()))

    # Deduct entry fees (flat per-RT cost based on model class)
    entry_fees = config.get("competition", {}).get("entry_fees", {})
    entry_fee_paid: dict[str, int] = {}
    for agent in all_workers:
        if agent == "naomi":
            naomi_model = config.get("gemini", {}).get("model", "")
            if "pro" in naomi_model:
                model = "opus"
            elif "flash" in naomi_model and "3" in naomi_model:
                model = "sonnet"
            elif "flash" in naomi_model:
                model = "flash"
            else:
                model = "flash"
        else:
            model = resolved_models.get(agent, "haiku")
        fee = entry_fees.get(model, entry_fees.get("haiku", 3))
        entry_fee_paid[agent] = fee
        try:
            subprocess.run(
                [sys.executable, str(SUITE_ROOT / "engine" / "scorer.py"),
                 "deduct-fee", agent, str(fee), "--rt", rt_id],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            logger.info("Entry fee: %s pays %d sparks (%s)", agent, fee, model)
        except Exception as e:
            logger.warning("Fee deduction failed for %s: %s (continuing)", agent, e)

    try:
        # Launch all workers
        for worker in workers:
            if worker == "naomi":
                continue
            model = resolved_models.get(worker, "sonnet")
            agent_procs[worker] = _launch_claude(worker, model)

        # Launch Judge (persistent live moderator)
        agent_procs["judge"] = _launch_claude("judge", "sonnet")

        # Launch Naomi (Gemini)
        if not skip_naomi:
            agent_procs["naomi"] = _launch_gemini("naomi")

        # Give agents time to connect and initialize
        time.sleep(5)

        all_messages_so_far: list[dict] = []  # Track all messages for summarization

        def _call_speaker(agent: str, signal: str) -> bool:
            """Post signal, wait for agent, collect messages. Returns True if agent spoke."""
            _check_and_restart(agent)
            _check_and_restart("judge")  # Keep Judge alive between speakers
            db_cmd("speak", "runner", signal)
            all_messages_so_far.append({"agent": "runner", "message": signal})
            spoke, msgs = wait_for_single_speaker(agent, timeout_seconds=speaker_timeout)
            all_messages_so_far.extend(msgs)
            if not spoke:
                _check_and_restart(agent)
            return spoke

        # 4b. Research Window (Round 0) — agents submit pre-debate lookup requests
        # Research window requests are FREE (do not deduct from RT budget).
        # Each agent may submit up to 3 concurrent requests.
        if steward_enabled and registered_files:
            logger.info("=== RESEARCH WINDOW (Round 0) ===")
            db_cmd("speak", "runner",
                   "--- RESEARCH WINDOW ---\n"
                   "Before debate begins, you may submit up to 3 research requests to ground your opening.\n"
                   "These are FREE — they do not count against your Steward budget.\n"
                   f"Registered files: {', '.join(f[-40:] for f in registered_files[:10])}\n"
                   f"Syntax: [[request: your question here]]\n"
                   f"RT budget (for debate rounds): {steward_budget.status() if steward_budget else 'N/A'}\n"
                   "Respond with your request(s), or PASS to skip.")
            all_messages_so_far.append({"agent": "runner", "message": "--- RESEARCH WINDOW ---"})

            # Collect up to 3 requests from each agent (all fire in parallel)
            research_tasks: dict[str, list[StewardTask]] = {}
            for agent in all_workers:
                spoke = _call_speaker(agent, f"YOUR TURN: {agent} — RESEARCH WINDOW (pre-debate, free)")
                if spoke:
                    agent_msgs = [m for m in all_messages_so_far if m["agent"] == agent]
                    last_text = agent_msgs[-1].get("message", "") if agent_msgs else ""
                    reqs = parse_requests(last_text)
                    if reqs:
                        # Cap at 3 concurrent requests per agent in research window
                        capped = reqs[:3]
                        tasks = []
                        for req in capped:
                            # No budget spend — research window is free
                            tasks.append(StewardTask(agent, req, registered_files, config))
                            logger.info("Research window: %s requested: %s", agent, req[:80])
                        research_tasks[agent] = tasks

            # Wait for all research tasks to complete
            total_tasks = sum(len(ts) for ts in research_tasks.values())
            if total_tasks > 0:
                logger.info("Research window: waiting for %d tasks across %d agents",
                            total_tasks, len(research_tasks))
                for agent, tasks in research_tasks.items():
                    for task in tasks:
                        result = task.wait(timeout=steward_cfg.get("timeout_seconds", 120) + 10)
                        steward_log.record(agent, task.request, result, round_num=0)
                        inject_msg = format_result(agent, task.request, result)
                        db_cmd("speak", "runner", inject_msg)
                        all_messages_so_far.append({"agent": "runner", "message": inject_msg})
                        logger.info("Research window: %s result injected (%s, %.1fs)",
                                    agent, result.get("status"), result.get("elapsed_s", 0))
                logger.info("Research window complete: %d results injected", total_tasks)
            else:
                logger.info("Research window: no requests submitted")

        # 5. Run structured debate rounds — randomize speaking order (with slot priority)
        speaking_order = list(all_workers)
        random.shuffle(speaking_order)
        # Check for first-speaker slot purchases (race condition: highest rank wins)
        first_speaker = _resolve_first_speaker(speaking_order)
        if first_speaker and first_speaker in speaking_order:
            speaking_order.remove(first_speaker)
            speaking_order.insert(0, first_speaker)
            logger.info("First speaker slot won by: %s", first_speaker)
        convergence_reason = None
        rounds_completed = 0
        # all_messages_so_far initialized before research window (line 535)
        debate_state: str = ""  # Cumulative debate state — builds across rounds
        speak_posts_by_round: dict[int, dict[str, str]] = {}  # S1: stability tracking
        stability_scores: dict[int, dict[str, float]] = {}  # S1: per-round Jaccard

        gemini_refresh_round = config.get("roundtable", {}).get("gemini_refresh_round", 5)

        for round_num in range(1, max_rounds + 1):
            logger.info("=== ROUND %d ===", round_num)

            # Check for crashed agents
            for agent_name in all_workers + ["judge"]:
                _check_and_restart(agent_name)

            # Hard-refresh Gemini agent at configured round to reset rate limit state
            if round_num == gemini_refresh_round and "naomi" in agent_procs:
                proc = agent_procs["naomi"]
                if proc.poll() is None:
                    logger.info("Hard-refreshing naomi (Gemini) at round %d", round_num)
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except Exception:
                        proc.kill()
                    time.sleep(2)  # Brief pause before relaunch
                    agent_procs["naomi"] = _launch_gemini("naomi")
                    logger.info("Relaunched naomi (fresh API connection)")

            # Post round start with budget status
            budget_str = format_budget_status(budget)
            round_begin_msg = f"ROUND {round_num}: begin\nBUDGET STATUS: {budget_str}"
            db_cmd("speak", "runner", round_begin_msg)
            all_messages_so_far.append({"agent": "runner", "message": round_begin_msg})

            # === SPEAK PHASE (with Steward defer-to-back) ===
            logger.info("--- SPEAK PHASE (Round %d) ---", round_num)
            db_cmd("speak", "runner", f"--- SPEAK PHASE (Round {round_num}) ---")

            # Dynamic queue: agents who request data go to the back
            speak_queue = list(speaking_order)
            spoke_set: set[str] = set()  # Agents who have completed their speak
            deferred_set: set[str] = set()  # Agents currently waiting on Steward
            pending_steward: dict[str, StewardTask] = {}  # agent -> active task
            speaker_num = 0

            while speak_queue:
                agent = speak_queue.pop(0)

                # Inject any completed Steward results before this agent's turn
                for ag in list(pending_steward):
                    task = pending_steward[ag]
                    if task.done.is_set():
                        result = task.wait(timeout=0)
                        steward_log.record(ag, task.request, result, round_num)
                        inject_msg = format_result(ag, task.request, result)
                        db_cmd("speak", "runner", inject_msg)
                        all_messages_so_far.append({"agent": "runner", "message": inject_msg})
                        logger.info("Steward result injected for %s (%s, %.1fs)",
                                    ag, result.get("status"), result.get("elapsed_s", 0))
                        del pending_steward[ag]
                        deferred_set.discard(ag)

                # If this agent already spoke (came back from deferral), skip
                if agent in spoke_set:
                    continue

                speaker_num += 1
                spoke = _call_speaker(
                    agent,
                    f"YOUR TURN: {agent} — SPEAK (Round {round_num}, speaker {speaker_num}/{len(speaking_order)})")

                if not spoke:
                    logger.warning("Round %d SPEAK: %s did not respond", round_num, agent)
                    spoke_set.add(agent)
                    continue

                # Check for [[request:]] tags in the agent's response
                agent_msgs = [m for m in all_messages_so_far if m["agent"] == agent]
                last_msg_text = agent_msgs[-1].get("message", "") if agent_msgs else ""
                requests = parse_requests(last_msg_text) if steward_enabled and steward_budget else []

                if requests and steward_budget and steward_budget.remaining(agent) > 0:
                    # Agent requested data — fire Steward async, defer to back
                    req_text = requests[0]  # One request at a time
                    steward_budget.spend(agent, req_text)
                    task = StewardTask(agent, req_text, registered_files, config)
                    pending_steward[agent] = task
                    deferred_set.add(agent)
                    # Agent's message (with request tag) stays in transcript
                    # They go to back of queue to speak again with data
                    speak_queue.append(agent)
                    logger.info("Round %d SPEAK: %s deferred (request: %s, budget: %d remaining)",
                                round_num, agent, req_text[:60],
                                steward_budget.remaining(agent))
                else:
                    spoke_set.add(agent)

                # INTERMISSION check: if queue is all deferred agents waiting on Steward
                remaining_speakers = [a for a in speak_queue if a not in spoke_set and a not in deferred_set]
                if not remaining_speakers and pending_steward:
                    logger.info("INTERMISSION: all speakers deferred, waiting for %d Steward tasks",
                                len(pending_steward))
                    for ag, task in pending_steward.items():
                        result = task.wait(timeout=steward_cfg.get("timeout_seconds", 120) + 10)
                        steward_log.record(ag, task.request, result, round_num)
                        inject_msg = format_result(ag, task.request, result)
                        db_cmd("speak", "runner", inject_msg)
                        all_messages_so_far.append({"agent": "runner", "message": inject_msg})
                        logger.info("Steward result injected for %s (intermission)", ag)
                        deferred_set.discard(ag)
                    pending_steward.clear()
                    logger.info("INTERMISSION complete, resuming speak phase")

            # Final: ensure all pending Steward tasks complete before rebuttal
            if pending_steward:
                logger.info("Waiting for %d remaining Steward tasks before rebuttal", len(pending_steward))
                for ag, task in pending_steward.items():
                    result = task.wait(timeout=steward_cfg.get("timeout_seconds", 120) + 10)
                    steward_log.record(ag, task.request, result, round_num)
                    inject_msg = format_result(ag, task.request, result)
                    db_cmd("speak", "runner", inject_msg)
                    all_messages_so_far.append({"agent": "runner", "message": inject_msg})
                pending_steward.clear()

            # === S1: STABILITY MEASUREMENT (Jaccard on SPEAK posts) ===
            round_speaks: dict[str, str] = {}
            for msg in all_messages_so_far:
                if msg["agent"] in all_workers and msg["agent"] != "runner":
                    round_speaks[msg["agent"]] = msg.get("message", "")
            speak_posts_by_round[round_num] = round_speaks
            if round_num > 1 and (round_num - 1) in speak_posts_by_round:
                prev = speak_posts_by_round[round_num - 1]
                round_jaccard: dict[str, float] = {}
                for agent in all_workers:
                    if agent in round_speaks and agent in prev:
                        round_jaccard[agent] = round(_jaccard_similarity(prev[agent], round_speaks[agent]), 3)
                if round_jaccard:
                    stability_scores[round_num] = round_jaccard
                    jaccard_msg = " | ".join(f"{a}={s}" for a, s in round_jaccard.items())
                    logger.info("Stability R%d: %s", round_num, jaccard_msg)

            # === REBUTTAL PHASE ===
            rebuttal_order = list(reversed(speaking_order))
            logger.info("--- REBUTTAL PHASE (Round %d) ---", round_num)
            db_cmd("speak", "runner", f"--- REBUTTAL PHASE (Round {round_num}) ---")

            for agent in rebuttal_order:
                spoke = _call_speaker(agent, f"YOUR TURN: {agent} — REBUTTAL (Round {round_num})")
                if not spoke:
                    logger.warning("Round %d REBUTTAL: %s did not respond", round_num, agent)

            # === JUDGE GATE ===
            # After all agents have spoken and rebutted, the Judge evaluates
            # whether the question is answered or debate should continue.
            logger.info("--- JUDGE GATE (Round %d) ---", round_num)
            db_cmd("speak", "runner",
                   f"--- JUDGE GATE (Round {round_num}) ---\n"
                   f"EVALUATE: Judge, all agents have spoken and rebutted. "
                   f"Has this roundtable produced a sufficient answer? "
                   f"Say CONVERGED: <reason> to end, or CONTINUE: <what's missing> "
                   f"to proceed to floor phase and further rounds.")
            _check_and_restart("judge")
            judge_spoke, judge_msgs = wait_for_single_speaker("judge", timeout_seconds=speaker_timeout)
            all_messages_so_far.extend(judge_msgs)

            if judge_spoke:
                convergence_reason = check_convergence(judge_msgs)
                if convergence_reason:
                    logger.info("Judge Gate: CONVERGED after round %d — %s", round_num, convergence_reason)
                    rounds_completed = round_num
                    break
                else:
                    logger.info("Judge Gate: CONTINUE — proceeding to floor phase")

            # === FLOOR PHASE ===
            floor_eligible = [a for a in speaking_order if budget[a] > 0]
            if floor_eligible:
                logger.info("--- FLOOR PHASE (Round %d) ---", round_num)
                db_cmd("speak", "runner", f"--- FLOOR PHASE (Round {round_num}) ---")

                while floor_eligible:
                    next_round_eligible = []
                    for agent in floor_eligible:
                        signal = (f"YOUR TURN: {agent} — FLOOR (Round {round_num}, budget: {budget[agent]} remaining). "
                                  f"Contribute or say PASS.")
                        spoke = _call_speaker(agent, signal)

                        if not spoke:
                            logger.warning("Round %d FLOOR: %s timed out (treated as PASS)", round_num, agent)
                        elif is_pass(all_messages_so_far, agent):
                            logger.info("Round %d FLOOR: %s passed", round_num, agent)
                        else:
                            budget[agent] -= 1
                            budget_spent[agent] += 1
                            logger.info("Round %d FLOOR: %s contributed (budget: %d remaining)",
                                        round_num, agent, budget[agent])
                            if budget[agent] > 0:
                                next_round_eligible.append(agent)

                    floor_eligible = next_round_eligible

            rounds_completed = round_num

            # === ROUND HEALTH AUDIT ===
            # Check process health, count timeouts, detect unrecoverable states
            alive_count = 0
            dead_agents = []
            for agent_name_check in all_workers + ["judge"]:
                proc = agent_procs.get(agent_name_check)
                if proc and proc.poll() is None:
                    alive_count += 1
                else:
                    dead_agents.append(agent_name_check)

            # Count timeouts this round by scanning runner messages for timeout warnings
            round_start_marker = f"ROUND {round_num}: begin"
            round_timeouts = 0
            in_round = False
            for msg in all_messages_so_far:
                if msg["agent"] == "runner" and round_start_marker in msg.get("message", ""):
                    in_round = True
                    continue
                if in_round and msg["agent"] == "runner":
                    text = msg.get("message", "")
                    if "timed out" in text or "did not respond" in text:
                        round_timeouts += 1

            # Check if Judge responded at the gate this round
            judge_responded_this_round = any(
                msg["agent"] == "judge" and in_round
                for msg in all_messages_so_far
                if msg.get("agent") == "judge"
            )
            # More precise: check if judge posted after the JUDGE GATE marker
            judge_gate_marker = f"JUDGE GATE (Round {round_num})"
            judge_at_gate = False
            past_gate = False
            for msg in all_messages_so_far:
                if msg["agent"] == "runner" and judge_gate_marker in msg.get("message", ""):
                    past_gate = True
                if past_gate and msg["agent"] == "judge":
                    judge_at_gate = True
                    break

            # Log health report
            total_agents = len(all_workers) + 1  # workers + judge
            logger.info(
                "HEALTH AUDIT (Round %d): alive=%d/%d, dead=%s, timeouts=%d, judge_at_gate=%s",
                round_num, alive_count, total_agents,
                dead_agents if dead_agents else "none",
                round_timeouts, judge_at_gate,
            )

            # Restart dead agents
            restarted = []
            for dead in dead_agents:
                if _check_and_restart(dead):
                    restarted.append(dead)
            if restarted:
                logger.info("HEALTH AUDIT: Restarted %s", restarted)
                time.sleep(3)  # Give restarted agents time to connect

            # Abort if unrecoverable — kill RT and report failure
            judge_alive = "judge" not in dead_agents or "judge" in restarted
            dead_workers = [a for a in dead_agents if a != "judge" and a not in restarted]
            worker_majority_dead = len(dead_workers) >= len(all_workers) / 2
            abort_reason = None

            if not judge_alive:
                abort_reason = (
                    f"Judge is dead and could not be restarted. "
                    f"Dead agents: {dead_agents}. Timeouts this round: {round_timeouts}."
                )
            elif worker_majority_dead:
                abort_reason = (
                    f"Majority of workers dead: {dead_workers}. "
                    f"Alive: {alive_count}/{total_agents}. Timeouts: {round_timeouts}."
                )
            elif round_timeouts >= total_agents:
                abort_reason = (
                    f"Every agent timed out this round. "
                    f"Timeouts: {round_timeouts}/{total_agents}. Dead: {dead_agents}."
                )

            if abort_reason:
                logger.error("HEALTH AUDIT ABORT (Round %d): %s", round_num, abort_reason)
                # Write failure report to latest-result.md
                failure_report = (
                    f"# RT ABORTED — Health Audit Failure\n\n"
                    f"**RT ID**: {rt_id}\n"
                    f"**Round**: {round_num}/{max_rounds}\n"
                    f"**Reason**: {abort_reason}\n\n"
                    f"## Audit Details\n"
                    f"- Alive: {alive_count}/{total_agents}\n"
                    f"- Dead agents: {dead_agents}\n"
                    f"- Restarted: {restarted}\n"
                    f"- Timeouts this round: {round_timeouts}\n"
                    f"- Judge at gate: {judge_at_gate}\n\n"
                    f"## Process State at Abort\n"
                )
                for agent_name_report in all_workers + ["judge"]:
                    proc = agent_procs.get(agent_name_report)
                    if proc:
                        status = "alive" if proc.poll() is None else f"dead (exit {proc.returncode})"
                        stderr_peek = ""
                        try:
                            if proc.poll() is not None and proc.stderr:
                                stderr_peek = proc.stderr.read().decode("utf-8", errors="replace")[:200]
                        except Exception:
                            pass
                        failure_report += f"- {agent_name_report}: {status}"
                        if stderr_peek:
                            failure_report += f" — {stderr_peek}"
                        failure_report += "\n"

                result_path = WRITE_ROOT / "roundtable-server" / f"latest-result.md"
                result_path.write_text(failure_report, encoding="utf-8")
                logger.error("Failure report written to %s", result_path)

                # Close the RT as failed
                db_cmd("speak", "runner",
                       f"RT ABORTED by health audit: {abort_reason}")
                db_cmd("close")

                # Kill all agent processes
                for name, proc in agent_procs.items():
                    if proc.poll() is None:
                        try:
                            proc.terminate()
                            proc.wait(timeout=10)
                        except Exception:
                            proc.kill()
                        logger.info("Terminated %s", name)

                raise RuntimeError(f"RT aborted by health audit (round {round_num}): {abort_reason}")

            # === BETWEEN ROUNDS: Cumulative debate state + convergence check ===
            if round_num < max_rounds:
                # Collect this round's messages for summary
                round_start_marker = f"ROUND {round_num}: begin"
                round_msgs_for_summary: list[dict] = []
                capturing = False
                for msg in all_messages_so_far:
                    if msg["agent"] == "runner" and round_start_marker in msg.get("message", ""):
                        capturing = True
                        continue
                    if capturing:
                        round_msgs_for_summary.append(msg)

                # Haiku builds cumulative debate state (not just a round summary)
                logger.info("Updating debate state after round %d (Haiku)", round_num)
                debate_state = _summarize_round(round_num, round_msgs_for_summary,
                                                prior_state=debate_state)

                # Build transcript index so agents know what's available to recall
                try:
                    from db import build_transcript_index
                    index = build_transcript_index(rt_id)
                    index_block = f"\n\nTRANSCRIPT INDEX (use `recall --agent X` or `recall --keyword Y` to read full text):\n{index}" if index else ""
                except Exception:
                    index_block = ""

                db_cmd("speak", "runner",
                       f"ROUND {round_num} SUMMARY:\n{debate_state}{index_block}")
                logger.info("Debate state + index posted (%d chars)", len(debate_state) + len(index_block))

                # Check if Judge signaled convergence during the round
                for msg in round_msgs_for_summary:
                    convergence_reason = check_convergence([msg])
                    if convergence_reason:
                        logger.info("Judge signaled convergence: %s", convergence_reason)
                        break
                if convergence_reason:
                    break

            # Rotate speaking order: first speaker goes to the back
            speaking_order = speaking_order[1:] + speaking_order[:1]

            logger.info("Round %d complete. Budget: %s", round_num, format_budget_status(budget))

        # 6. Close roundtable and collect transcript
        logger.info("Closing roundtable after %d rounds", rounds_completed)
        close_result = db_cmd("close")
        transcript = close_result.get("transcript", [])

        if not transcript:
            logger.warning("Close returned empty transcript — fetching directly")
            tx_result = db_cmd("transcript")
            transcript = tx_result.get("transcript", [])

    finally:
        # Kill all agent processes — verify they're actually dead
        for name, proc in agent_procs.items():
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                # Force kill if still alive
                if proc.poll() is None:
                    try:
                        proc.kill()
                        proc.wait(timeout=5)
                    except Exception:
                        pass
                if proc.poll() is None:
                    logger.error("CLEANUP: Failed to kill %s (PID %s) — process may be orphaned",
                                 name, proc.pid)
                else:
                    logger.info("Terminated %s (exit %s)", name, proc.returncode)

    # 7. Build digest with budget usage
    budget_usage = {
        agent: {"starting_budget": budget_per_agent, "spent": budget_spent[agent], "remaining": budget[agent]}
        for agent in all_workers
    }

    digest = build_digest(
        topic=topic,
        rt_id=rt_id,
        rounds_completed=rounds_completed,
        transcript=transcript,
        convergence_reason=convergence_reason,
        budget_usage=budget_usage,
    )

    # Save digest
    digest_path = WRITE_ROOT / "roundtable-server" / f"digest-{rt_id}.json"
    digest_path.write_text(json.dumps(digest, indent=2), encoding="utf-8")
    logger.info("Digest saved to %s", digest_path)

    # Save Steward log (if any requests were made)
    if steward_log.entries:
        steward_log_path = WRITE_ROOT / "roundtable-server" / f"steward-log-{rt_id}.json"
        steward_log.save(str(steward_log_path))
        digest["steward_requests"] = len(steward_log.entries)
        logger.info("Steward log saved: %d requests (%s)", len(steward_log.entries), steward_log_path)

    # 8. Judge scoring (Sonnet) + process Judge gate bonuses
    gate_results = _process_gate_bonuses(rt_id, transcript)

    from judge_scorer import judge_score
    scoring_result = judge_score(briefing_text, transcript, all_workers, rt_id)
    digest["scoring"] = scoring_result

    if scoring_result.get("status") == "failed":
        # No silent fallback — flag Admin for resolution
        error_msg = scoring_result.get("error", "Unknown scoring failure")
        logger.error("SCORING FAILED — Admin must resolve: %s", error_msg)
        db_cmd("speak", "runner",
               f"ADMIN-SIGNAL: SCORING_FAILED for RT {rt_id}. "
               f"Error: {error_msg}. Manual scoring required or retry via: "
               f"python engine/judge_scorer.py --digest digest-{rt_id}.json")
        digest["scoring_status"] = "pending"
    else:
        digest["scoring_status"] = "complete"

    if gate_results:
        digest["gate_bonuses"] = gate_results

    # S0: Byzantine variance detection (post-scoring)
    try:
        from scorer import compute_variance_flags
        byz_flags = compute_variance_flags(rt_id, all_workers, rounds_completed)
        if byz_flags:
            flagged_agents = {a: f for a, f in byz_flags.items() if f.get("flagged")}
            if flagged_agents:
                flag_msg = ", ".join(f"{a}: {f['reason']}" for a, f in flagged_agents.items())
                logger.warning("Byzantine flags: %s", flag_msg)
            digest["byzantine_flags"] = byz_flags
    except Exception as e:
        logger.warning("Byzantine variance check skipped: %s", e)

    # S1: Include stability scores in digest
    if stability_scores:
        digest["stability_jaccard"] = stability_scores

    # Record entry fees in digest
    digest["entry_fees"] = entry_fee_paid

    # 8b. Extract and register ventures from <VENTURE>/<MOONSHOT>/<SCOUT> tags
    venture_results = _extract_and_register_ventures(rt_id, transcript)
    if venture_results:
        digest["ventures"] = venture_results

    # 8c. Venture resolution — handled by Admin agent post-RT (not automated in pipeline).
    # Admin reads digest["ventures"], evaluates viability, calls scorer.resolve_venture()
    # directly. See agents/opus-admin/CLAUDE.md for instructions.

    # 9. Save leaderboard
    _save_leaderboard()

    # 10. Update analytics for all agents (pre-therapist — feeds into session context)
    _update_analytics()

    # 10b. Skill distillation — always runs (moved out of skip_post gate)
    distill_results = _distill_skills(rt_id, transcript, all_workers)
    digest["distilled_skills"] = distill_results

    # 10c. Append DERIVE skills to novel concepts database
    _append_novel_concepts(distill_results.get("skills", []), rt_id, topic)

    # Re-save digest with scoring + distillation results (always, regardless of skip_post)
    digest_path.write_text(json.dumps(digest, indent=2, ensure_ascii=False), encoding="utf-8")

    if not skip_post:
        # 11. Therapist debrief — automatic exit interview for every worker
        therapist_results = _run_therapist(digest_path, all_workers)
        digest["therapist"] = therapist_results

        # 13. Consume boosts used in this RT + age bulletin board requests
        # Note: Request fulfillment is handled by Admin during post-RT curation, not automated here.
        try:
            from store import consume_boosts_after_rt, age_bulletin_requests
            consume_boosts_after_rt(all_workers, rt_id)
            expired = age_bulletin_requests()
            if expired:
                digest["expired_requests"] = [
                    {"agent": r.get("agent"), "description": r.get("description", "")[:80]}
                    for r in expired
                ]
                logger.info("Bulletin: %d requests expired (3+ RTs) — flagged for Admin", len(expired))
        except Exception as e:
            logger.warning("Post-RT store cleanup failed (non-fatal): %s", e)

        # 14. Age active goals and add session summaries to structured memory
        try:
            from agent_memory import age_goals, add_session_summary
            for agent in all_workers:
                age_goals(agent)
                # Add a concise session summary from the digest
                summary = f"Topic: {topic}. "
                scoring_data = digest.get("scoring", [])
                if isinstance(scoring_data, dict):
                    scoring_data = scoring_data.get("scores", [])
                for s in scoring_data:
                    if isinstance(s, dict) and s.get("agent") == agent:
                        summary += f"Scored {s.get('total', s.get('score', '?'))}/12."
                        break
                add_session_summary(agent, rt_id, summary)
            logger.info("Agent goals aged and session summaries added for %d agents", len(all_workers))
        except Exception as e:
            logger.warning("Agent memory post-RT update failed (non-fatal): %s", e)

        # 16. Sync skills owned for all agents (therapist may have processed purchases)
        try:
            from evolver import sync_skills_owned
            for agent in all_workers:
                sync_skills_owned(agent)
        except Exception as e:
            logger.warning("Post-RT skills sync failed (non-fatal): %s", e)

        # 17. Re-save digest with therapist + distillation results included
        digest_path.write_text(json.dumps(digest, indent=2), encoding="utf-8")
    else:
        logger.info("--skip-post: skipping therapist and cleanup (steps 11-17). Distillation already ran.")

    # 18. Write summary to known location + desktop notification
    _notify_completion(topic, rt_id, rounds_completed, digest_path)

    return digest



def _notify_completion(topic: str, rt_id: str, rounds: int, digest_path: Path) -> None:
    """Write summary to known file and fire a Windows toast notification."""
    summary_path = WRITE_ROOT / "roundtable-server" / f"latest-result.md"
    summary_path.write_text(
        f"# RT Complete: {rt_id}\n\n"
        f"**Topic:** {topic}\n"
        f"**Rounds:** {rounds}\n"
        f"**Digest:** {digest_path.name}\n"
        f"**Time:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"Say `show me` or `suite results` to see the findings.\n",
        encoding="utf-8",
    )
    logger.info("Summary written to %s", summary_path)

    # Windows toast notification
    if sys.platform == "win32":
        try:
            ps_cmd = (
                f'[Windows.UI.Notifications.ToastNotificationManager, '
                f'Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; '
                f'$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(0); '
                f'$text = $xml.GetElementsByTagName("text"); '
                f'$text[0].AppendChild($xml.CreateTextNode("Claude Suite RT Complete")) | Out-Null; '
                f'$text[1].AppendChild($xml.CreateTextNode("{topic[:80]}")) | Out-Null; '
                f'$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); '
                f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Claude Suite").Show($toast)'
            )
            subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, timeout=10,
            )
            logger.info("Desktop notification sent")
        except Exception as e:
            logger.warning("Desktop notification failed (non-fatal): %s", e)


def _extract_and_register_ventures(rt_id: str, transcript: list[dict]) -> list[dict]:
    """Parse <VENTURE>, <MOONSHOT>, <SCOUT> tags from RT messages and register via scorer."""
    TAG_TO_TIER = {"VENTURE": "venture", "MOONSHOT": "moonshot", "SCOUT": "scout"}
    pattern = re.compile(
        r"<(VENTURE|MOONSHOT|SCOUT)>\s*(.*?)(?:</\1>|$)",
        re.DOTALL | re.IGNORECASE,
    )
    results = []
    for msg in transcript:
        agent = msg.get("agent_name", msg.get("agent", ""))
        if agent in ("runner", "judge", "assistant"):
            continue
        text = msg.get("message", "")
        for match in pattern.finditer(text):
            tag = match.group(1).upper()
            idea = match.group(2).strip()
            tier = TAG_TO_TIER.get(tag, "scout")
            # Truncate idea to first sentence or 200 chars for the record
            short_idea = idea.split("\n")[0][:200]
            try:
                from scorer import pitch_venture
                result = pitch_venture(agent, tier, short_idea, rt_id)
                if "error" in result:
                    logger.warning("Venture registration failed for %s: %s", agent, result["error"])
                else:
                    logger.info("VENTURE REGISTERED: %s pitched %s '%s' (%d sparks staked)",
                                agent, tier, short_idea[:50], result["venture"]["stake"])
                results.append({"agent": agent, "tier": tier, "idea": short_idea, "result": result})
            except Exception as e:
                logger.error("Venture extraction error for %s: %s", agent, e)
    if results:
        logger.info("=== VENTURES: %d registered from RT %s ===", len(results), rt_id)
    return results


def _run_therapist(digest_path: Path, participants: list[str]) -> dict:
    """Run interactive Therapist sessions for all workers. Returns per-agent results."""
    logger.info("=== THERAPIST SESSIONS (Opus 1-on-1) ===")
    try:
        result = subprocess.run(
            [sys.executable, str(SUITE_ROOT / "engine" / "therapist.py"),
             "--digest", str(digest_path),
             "--agents", ",".join(participants),
             "--turns", "2"],
            capture_output=True, text=True, timeout=900,  # 15 min — Opus sessions take time
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            therapist_results = json.loads(result.stdout)
            for agent, info in therapist_results.items():
                if "error" in info:
                    logger.error("Therapist failed for %s: %s", agent, info["error"])
                else:
                    logger.info("Therapist debriefed %s: memory=%s, +%d behaviors, trait=%s",
                                agent, info.get("memory_updated"),
                                info.get("behaviors_added", 0),
                                (info.get("trait", "")[:60]))
            return therapist_results
        else:
            logger.error("Therapist process failed: %s", result.stderr[:300])
            return {"error": result.stderr[:300]}
    except Exception as e:
        logger.error("Therapist exception: %s", e)
        return {"error": str(e)}


def _append_novel_concepts(skills: list[dict], rt_id: str, topic: str) -> int:
    """Append DERIVE-type skills to the novel concepts database.

    Returns count of new concepts added (skips duplicates by content hash).
    """
    derives = [s for s in skills if s.get("type") == "DERIVE"]
    if not derives:
        return 0

    db_path = SUITE_ROOT / "novel_concepts.json"
    if db_path.exists():
        db = json.loads(db_path.read_text(encoding="utf-8"))
    else:
        db = {"version": 1, "count": 0, "domains": {}, "concepts": []}

    existing_ids = {c["id"] for c in db["concepts"]}

    code_kw = {"function", "file", "code", "test", "bug", "fix", "import", "class",
               "method", "refactor", "api", "hook", "detector", "parser", "pipeline",
               "schema", "query", "threshold", "grep", "caller", "dependency", "migration"}
    lit_kw = {"character", "narrator", "scene", "reader", "prose", "chapter", "dialogue",
              "tension", "sacrifice", "grief", "narrative"}
    econ_kw = {"spark", "economy", "exploit", "royalt", "governance", "incentive", "boost", "market"}

    def _classify(title: str, pattern: str) -> str:
        text = (title + " " + pattern).lower()
        words = set(text.split())
        if words & lit_kw:
            return "literary"
        if words & econ_kw:
            return "economic"
        if words & code_kw:
            return "engineering"
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
            "id": concept_id,
            "title": title,
            "domain": _classify(title, pattern),
            "pattern": pattern,
            "when_to_apply": s.get("when_to_apply", ""),
            "structural_category": s.get("structural_category", ""),
            "trigger_phase": s.get("trigger_phase", ""),
            "primary_actor": s.get("primary_actor", ""),
            "problem_nature": s.get("problem_nature", ""),
            "agent_dynamic": s.get("agent_dynamic", ""),
            "tags": s.get("tags", []),
            "one_liner": s.get("one_liner", ""),
            "source_agent": s.get("agent", ""),
            "source_rt": rt_id,
            "source_topic": topic,
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


def _distill_skills(rt_id: str, transcript: list[dict], workers: list[str]) -> dict:
    """Extract skills from transcript via Sonnet LLM call.

    Produces raw skill candidates for the Admin to curate during post-RT.
    Admin picks the best 3-5, deduplicates against the store, and lists them.
    """
    # Build transcript text for extraction
    substantive = [m for m in transcript if m.get("agent") in workers or m.get("agent") == "judge"]
    if not substantive:
        logger.warning("No substantive messages for skill extraction")
        return {"skills": [], "error": "no messages"}

    transcript_text = "\n\n".join(
        f"[{m['agent'].upper()}]: {m['message']}" for m in substantive
    )

    # Cap transcript to avoid excessive cost (~50K chars max)
    if len(transcript_text) > 50000:
        transcript_text = transcript_text[:50000] + "\n\n[TRANSCRIPT TRUNCATED]"

    prompt = f"""Extract concrete, reusable skills from this roundtable transcript.

For each skill, provide:
- **title**: Short descriptive name
- **type**: CAPTURE (observed technique), FIX (anti-pattern correction), or DERIVE (synthesized from multiple contributions)
- **agent**: Who originated it (or multiple agents if collaborative)
- **pattern**: The specific technique — what was done, with file/line references where available
- **when_to_apply**: Concrete conditions where this skill is useful beyond this specific discussion
- **structural_category**: One of: state-boundary | signal-integrity | compound-failure | mechanism-policy | affordance-capacity | process-workflow | data-pipeline | testing-verification
- **trigger_phase**: One of: system-design | code-review | debugging | policy-governance | implementation
- **primary_actor**: One of: individual-contributor | reviewer | architect | system-prompter
- **problem_nature**: One of: state-lifecycle | calibration-metric | dependency-sequencing | cognitive-framing | interface-contract | data-integrity
- **agent_dynamic**: One of: convergence (multiple agents independently agreed) | synthesis (opposing views resolved into new idea) | reframing (agent shifted the debate to the right level)
- **tags**: Array of 3-5 searchable keywords
- **one_liner**: One plain-English sentence summarizing the concept

Rules:
- Only extract skills that are REUSABLE in future discussions/work — skip topic-specific observations
- Each skill must have ALL fields filled — no empty fields
- Cite specific files, functions, or line numbers from the transcript where possible
- For DERIVE type, agent_dynamic is required and must reflect how the synthesis actually happened
- Target 10-15 skills. Quality over quantity.

Output as JSON array:
[{{"title": "...", "type": "CAPTURE|FIX|DERIVE", "agent": "...", "pattern": "...", "when_to_apply": "...", "structural_category": "...", "trigger_phase": "...", "primary_actor": "...", "problem_nature": "...", "agent_dynamic": "...", "tags": ["...", "..."], "one_liner": "..."}}]

TRANSCRIPT:
{transcript_text}"""

    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            ["claude", "-p", "--model", "sonnet",
             "--no-session-persistence", "--output-format", "text",
             "--disable-slash-commands", "--dangerously-skip-permissions",
             "--max-budget-usd", "5.00"],
            input=prompt, capture_output=True, text=True, timeout=180,
            cwd=str(WORKSPACE_ROOT), encoding="utf-8", errors="replace", env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            raw = result.stdout.strip()
            # Try to parse JSON from the response (may be wrapped in markdown)
            json_start = raw.find("[")
            json_end = raw.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                skills = json.loads(raw[json_start:json_end])
                logger.info("Sonnet extracted %d raw skill candidates for RT %s", len(skills), rt_id)
                return {"skills": skills, "count": len(skills), "model": "sonnet"}
            else:
                logger.warning("Sonnet skill extraction returned non-JSON output")
                return {"skills": [], "raw_output": raw[:500], "error": "non-json"}
        logger.warning("Sonnet skill extraction failed (exit %d)", result.returncode)
        return {"skills": [], "error": f"exit code {result.returncode}"}
    except subprocess.TimeoutExpired:
        logger.error("Sonnet skill extraction timed out (180s) for RT %s", rt_id)
        return {"skills": [], "error": "timeout"}
    except Exception as e:
        logger.error("Sonnet skill extraction error: %s", e)
        return {"skills": [], "error": str(e)}


def _process_gate_bonuses(rt_id: str, transcript: list[dict]) -> list[dict]:
    """Scan transcript for Judge GATE signals and award bonus sparks."""
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    gate_config = config.get("competition", {}).get("gate_bonus", {})
    if not gate_config.get("enabled", True):
        return []

    max_gates = gate_config.get("max_per_rt", 3)
    results = []

    for msg in transcript:
        if msg.get("agent") != "judge":
            continue
        text = msg.get("message", "")
        # Parse GATE: [agent] — [reason] format
        if "GATE:" not in text:
            continue
        # Extract agent name and reason
        gate_part = text[text.index("GATE:") + 5:].strip()
        if " — " in gate_part:
            agent_name, reason = gate_part.split(" — ", 1)
        elif " - " in gate_part:
            agent_name, reason = gate_part.split(" - ", 1)
        else:
            continue
        agent_name = agent_name.strip().lower()
        reason = reason.strip()

        if len(results) >= max_gates:
            logger.warning("Max gate bonuses (%d) reached for RT %s", max_gates, rt_id)
            break

        try:
            result = subprocess.run(
                [sys.executable, str(SUITE_ROOT / "engine" / "scorer.py"),
                 "gate", agent_name, reason, "--rt", rt_id],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                gate_data = json.loads(result.stdout)
                results.append(gate_data)
                logger.info("Gate bonus awarded: %s — %s", agent_name, reason[:60])
        except Exception as e:
            logger.error("Gate bonus error for %s: %s", agent_name, e)

    return results


def _resolve_first_speaker(workers: list[str]) -> str | None:
    """Check if any agent purchased a first-speaker slot. Race condition: highest rank wins."""
    # Check each worker's inventory for a first-speaker consumable
    # For now, check store/ledger.json for pending first-speaker purchases
    ledger_path = WRITE_ROOT / "store" / "ledger.json"
    if not ledger_path.exists():
        return None

    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # Find unresolved first-speaker purchases
    bidders: list[tuple[str, int]] = []  # (agent, rank)
    for entry in ledger:
        if entry.get("item_id") == "first-speaker" and entry.get("status") == "pending":
            agent = entry["agent"]
            # Get leaderboard rank
            metrics_path = AGENTS_DIR / agent / "metrics.json"
            rank = 999
            if metrics_path.exists():
                try:
                    m = json.loads(metrics_path.read_text(encoding="utf-8"))
                    rank = m.get("leaderboard_rank", 999)
                except (json.JSONDecodeError, OSError):
                    pass
            bidders.append((agent, rank))

    if not bidders:
        return None

    # Highest rank (lowest number) wins
    bidders.sort(key=lambda x: x[1])
    winner = bidders[0][0]

    # Mark winner as consumed, refund losers (they keep sparks — race condition)
    for entry in ledger:
        if entry.get("item_id") == "first-speaker" and entry.get("status") == "pending":
            if entry["agent"] == winner:
                entry["status"] = "consumed"
            else:
                entry["status"] = "refunded"
                # Refund sparks
                metrics_path = AGENTS_DIR / entry["agent"] / "metrics.json"
                if metrics_path.exists():
                    try:
                        m = json.loads(metrics_path.read_text(encoding="utf-8"))
                        m["sparks"] = m.get("sparks", 0) + entry.get("cost", 6)
                        metrics_path.write_text(json.dumps(m, indent=2), encoding="utf-8")
                    except (json.JSONDecodeError, OSError):
                        pass

    ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    logger.info("First-speaker race: %d bidders, winner=%s", len(bidders), winner)
    return winner


def _update_analytics():
    """Update growth analytics for all agents and save leaderboard snapshot."""
    try:
        result = subprocess.run(
            [sys.executable, str(SUITE_ROOT / "engine" / "analytics.py"), "update"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            logger.info("Analytics updated for all agents")
        else:
            logger.error("Analytics update failed: %s", result.stderr[:300])
    except Exception as e:
        logger.error("Analytics exception: %s", e)


def _save_leaderboard():
    """Persist leaderboard to benchmarks/leaderboard.json."""
    try:
        result = subprocess.run(
            [sys.executable, str(SUITE_ROOT / "engine" / "scorer.py"), "leaderboard"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            lb_dir = SUITE_ROOT / "benchmarks"
            lb_dir.mkdir(parents=True, exist_ok=True)
            lb_path = lb_dir / "leaderboard.json"
            lb_path.write_text(result.stdout, encoding="utf-8")
            logger.info("Leaderboard saved to %s", lb_path)
    except Exception as e:
        logger.error("Leaderboard save failed: %s", e)


def format_digest_summary(digest: dict) -> str:
    """Format digest as human-readable summary for Admin."""
    lines = [
        f"TOPIC: {digest['topic']}",
        f"ROUNDS: {digest['rounds']}",
        f"MESSAGES: {digest['total_messages']}",
        f"CONVERGED: {'Yes' if digest['converged'] else 'No'}",
    ]
    if digest["convergence_reason"]:
        lines.append(f"REASON: {digest['convergence_reason']}")

    lines.append(f"JUDGE INTERVENTIONS: {digest['judge_interventions']}")

    if digest.get("budget_usage"):
        lines.append("\nBUDGET USAGE:")
        for agent, usage in digest["budget_usage"].items():
            lines.append(f"  {agent}: spent {usage['spent']}/{usage['starting_budget']}")

    lines.append("\nCONTRIBUTIONS:")
    for agent, count in sorted(digest["contributions"].items()):
        if agent not in ("runner", "assistant"):
            lines.append(f"  {agent}: {count} messages")

    lines.append("\nFINAL POSITIONS:")
    for agent, msg in digest["final_positions"].items():
        preview = msg[:200] + "..." if len(msg) > 200 else msg
        lines.append(f"  [{agent}]: {preview}")

    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Run a structured debate roundtable"
    )
    parser.add_argument("--topic", required=True, help="Discussion topic")
    parser.add_argument("--briefing", required=True, help="Briefing file path")
    parser.add_argument("--workers", default=None, help="Comma-separated worker names")
    parser.add_argument("--max-rounds", type=int, default=None, help="Max rounds")
    parser.add_argument("--skip-naomi", action="store_true", help="Skip Gemini/Naomi")
    parser.add_argument("--speaker-timeout", type=int, default=200,
                        help="Seconds to wait for each speaker (default: 200)")
    parser.add_argument("--budget", type=int, default=3,
                        help="Extra floor turns per agent (default: 3)")
    parser.add_argument("--skip-post", action="store_true",
                        help="Stop after scoring/analytics — skip therapist, distiller, cleanup")
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary")

    args = parser.parse_args()
    workers = args.workers.split(",") if args.workers else None

    try:
        digest = run_roundtable(
            topic=args.topic,
            briefing_path=args.briefing,
            workers=workers,
            max_rounds=args.max_rounds,
            skip_naomi=args.skip_naomi,
            speaker_timeout=args.speaker_timeout,
            budget_per_agent=args.budget,
            skip_post=args.skip_post,
        )

        if args.summary:
            print(format_digest_summary(digest))
        else:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            print(json.dumps(digest, indent=2, ensure_ascii=False))

    except KeyboardInterrupt:
        logger.info("Interrupted — closing roundtable")
        try:
            db_cmd("cut", "keyboard interrupt")
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        logger.error("Runner failed: %s", e)
        try:
            db_cmd("cut", f"runner error: {e}")
        except Exception:
            pass
        sys.exit(1)
