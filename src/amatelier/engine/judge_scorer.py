"""Judge Scorer — Sonnet-based evaluation of roundtable contributions.

Replaces the heuristic _auto_score() with LLM evaluation on the 0-3-10 scale.
Each agent scored independently on 4 axes: Novelty, Accuracy, Impact, Challenge.

Called by roundtable_runner.py after each RT closes. On failure, flags Admin
for manual resolution — no silent fallback to heuristics.

Usage:
    # Called programmatically from roundtable_runner.py:
    from judge_scorer import judge_score
    results = judge_score(briefing_text, transcript, workers, rt_id)

    # CLI for manual scoring / retries:
    python engine/judge_scorer.py --digest path/to/digest.json
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("judge_scorer")

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

VALID_SCORES = {0, 1, 2, 3, 10}

JUDGE_PROMPT = """You are the scoring judge for a structured AI debate roundtable. You have the briefing (what agents were asked to do) and the full transcript.

Score each agent INDEPENDENTLY on 4 axes. Scores are 0, 1, 2, 3, or 10.
There is NO 4-9. The jump from 3 to 10 is intentional — a discontinuity, not a gradient.

A 10 requires a DISCONTINUITY — a specific message that split the discussion into "before" and "after." You must quote the message and explain the before/after shift. If you cannot identify this moment, the maximum score is 3.

NOVELTY (0-3 or 10):
  0 = restated what others said
  1 = one minor original observation
  2 = meaningful new perspective that others built on
  3 = reframe that changed the discussion's direction
  10 = introduced a framework or idea that made the previous discussion obsolete

ACCURACY (0-3 or 10):
  0 = significant errors or unsupported claims
  1 = mostly correct but shallow
  2 = correct with solid reasoning
  3 = precise, edge cases addressed, well-sourced
  10 = identified a hidden constraint that invalidated the group's shared
       assumptions — mechanically proven, not just asserted

IMPACT (0-3 or 10):
  0 = contributions ignored or redundant
  1 = one point acknowledged
  2 = multiple ideas adopted into outcome
  3 = discussion would have gone differently without them
  10 = the RT's final output was restructured around this contribution

CHALLENGE (0-3 or 10):
  0 = agreed with everything
  1 = raised one minor objection
  2 = substantive challenges that improved positions
  3 = identified critical blind spots the group was avoiding
  10 = proved the group's foundational premise was wrong AND
       provided the working replacement

IMPORTANT: Score each agent based on the QUALITY of their contributions, not the QUANTITY. An agent who spoke twice but fundamentally shifted the discussion scores higher than an agent who spoke twelve times with correct but unremarkable observations.

CALIBRATION: A score of 2 means genuinely above-average — not the baseline for showing up. Most contributions should score 1 on most axes. A typical agent in a typical RT should total 4-6 sparks, not 8+. If you find yourself giving 2s across the board, you are scoring too generously. Reserve 2 for work that clearly stands out. Reserve 3 for truly exceptional, rare contributions.

WHY NOT A 2? Before assigning 2 on any axis, state one specific example from the transcript that justifies it. If you cannot point to a concrete moment, the score is 1. This applies to every axis for every agent — no exceptions.

---

BRIEFING:
{briefing}

---

TRANSCRIPT:
{transcript}

---

You MUST respond with ONLY valid JSON. No markdown fences, no backticks, no text before or after the JSON object. Start your response with {{ and end with }}.

Format:
{{
  "scores": {{
    "agent_name": {{
      "novelty": N,
      "accuracy": N,
      "impact": N,
      "challenge": N,
      "reasoning": "2-3 sentences justifying the scores with specific transcript references",
      "grand_insight": "if any axis is 10: quote the message and describe the before/after shift, otherwise null"
    }}
  }}
}}"""


def _format_transcript(transcript: list[dict]) -> tuple[str, dict[str, str]]:
    """Format the whole debate for the Judge, blinded.

    Returns (text, anon_to_agent). Each worker is scored under a random
    "Reviewer A/B/..." label and its name is scrubbed from every message
    (agents address each other by name); _parse_scores maps the labels back.
    The judge's own posts are labelled Moderator. A worker's research-window
    post counts only if it makes a [[request:]] — the window is for lookups,
    so debate posted there earns nothing. Every phase is included: the old
    1,200-per-message / 20,000-total caps dropped the floor phase entirely.
    """
    MAX_MSG = 8000      # ceiling per message (a cut is logged)
    MAX_TOTAL = 200000  # ceiling for the whole debate (a cut is logged)

    workers_seen: list[str] = []
    for msg in transcript:
        agent = msg.get("agent", "unknown")
        if agent not in ("runner", "assistant", "judge") and agent not in workers_seen:
            workers_seen.append(agent)
    shuffled = list(workers_seen)
    random.shuffle(shuffled)  # random order, so labels carry no rank
    agent_to_anon = {agent: f"Reviewer {chr(65 + i)}" for i, agent in enumerate(shuffled)}
    anon_to_agent = {v: k for k, v in agent_to_anon.items()}

    lines = []
    total = 0
    in_research_window = False
    for msg in transcript:
        agent = msg.get("agent", "unknown")
        text = msg.get("message", "")
        if agent == "runner":
            if "--- RESEARCH WINDOW ---" in text:
                in_research_window = True
            elif text.lstrip().startswith("ROUND "):
                in_research_window = False
            continue
        if agent == "assistant" or not text.strip():
            continue
        if in_research_window and agent != "judge" and "[[request:" not in text:
            continue
        if len(text) > MAX_MSG:
            logger.warning("Scorer transcript: a %s message cut from %d to %d chars",
                           agent, len(text), MAX_MSG)
            text = text[:MAX_MSG] + "\n[...truncated...]"
        label = "Moderator" if agent == "judge" else agent_to_anon.get(agent, "Reviewer X")
        line = f"[{label}]: {_anonymize_text(text, anon_to_agent)}"
        if total + len(line) > MAX_TOTAL:
            logger.warning("Scorer transcript cut at %d chars (MAX_TOTAL)", total)
            lines.append("[...transcript truncated for length...]")
            break
        lines.append(line)
        total += len(line)
    return "\n\n".join(lines), anon_to_agent


def _anonymize_text(text: str, anon_to_agent: dict[str, str]) -> str:
    """Replace each worker's name (whole word, any case) with its reviewer label."""
    if not anon_to_agent:
        return text
    agent_to_anon = {agent.lower(): anon for anon, agent in anon_to_agent.items()}
    names = sorted(agent_to_anon, key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE)
    return pattern.sub(lambda m: agent_to_anon[m.group(1).lower()], text)


def _get_judge_effort() -> str | None:
    """Read config.judge.effort (e.g. 'max') or None if unset."""
    try:
        from amatelier import paths
        user_cfg = paths.user_config_override()
        bundled_cfg = paths.bundled_config()
        src = user_cfg if user_cfg.exists() else bundled_cfg
        if not src.exists():
            return None
        data = json.loads(src.read_text(encoding="utf-8"))
        effort = data.get("team", {}).get("judge", {}).get("effort")
        return str(effort) if effort else None
    except Exception:
        return None


def _call_sonnet(prompt: str) -> str | None:
    """Call Claude Sonnet for scoring.

    Tries the open-mode backend first (Anthropic SDK, OpenAI-compat).
    Falls back to the ``claude`` CLI subprocess if backend is unavailable
    or fails — preserving the claude-code mode path.

    When ``config.judge.effort == "max"``, enables Anthropic extended
    thinking via the backend protocol. Other backends ignore the effort
    hint gracefully.
    """
    effort = _get_judge_effort()
    # Try backend first (works without Claude Code CLI)
    try:
        from amatelier.llm_backend import get_backend
        backend = get_backend()
        if backend.name != "claude-code":
            result = backend.complete(
                system="", prompt=prompt, model="sonnet",
                max_tokens=8000, timeout=360,
                effort=effort, json_mode=True,
            )
            return result.text
    except Exception:
        pass  # Fall through to CLI

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        from amatelier.llm_backend import claude_cli_isolation_args
        cmd = ["claude", "-p", "--model", "sonnet", *claude_cli_isolation_args(),
               "--no-session-persistence", "--output-format", "json",
               "--disable-slash-commands", "--dangerously-skip-permissions",
               "--max-budget-usd", "5.00"]
        if effort in ("low", "medium", "high", "max"):
            cmd.extend(["--effort", effort])
        result = subprocess.run(
            cmd,
            input=prompt, capture_output=True, text=True, timeout=360,
            cwd=str(WORKSPACE_ROOT), encoding="utf-8", errors="replace", env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            # --output-format json wraps in {"result": "..."} — extract inner text
            try:
                outer = json.loads(result.stdout)
                return outer.get("result", result.stdout).strip()
            except (json.JSONDecodeError, AttributeError):
                return result.stdout.strip()
        logger.error("Sonnet call failed (exit %d): %s", result.returncode, result.stderr[:300])
        return None
    except subprocess.TimeoutExpired:
        logger.error("Sonnet call timed out (360s)")
        return None
    except Exception as e:
        logger.error("Sonnet call exception: %s", e)
        return None


def _parse_scores(
    raw: str, expected_agents: list[str], anon_to_agent: dict[str, str] | None = None,
) -> dict | None:
    """Parse and validate Judge JSON response. Returns parsed dict or None.

    With ``anon_to_agent``, reviewer labels ("Reviewer A") are mapped back to
    real agent names before validation.
    """
    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("JSON parse failed: %s — raw: %s", e, text[:500])
        return None

    scores = data.get("scores")
    if not isinstance(scores, dict):
        logger.error("Response missing 'scores' dict")
        return None

    if anon_to_agent:
        scores = {anon_to_agent.get(label, label): s for label, s in scores.items()}
        data["scores"] = scores

    # Validate and clamp each agent's scores
    for agent in expected_agents:
        if agent not in scores:
            logger.warning("Agent %s missing from scores — inserting zeros", agent)
            scores[agent] = {
                "novelty": 0, "accuracy": 0, "impact": 0, "challenge": 0,
                "reasoning": "Agent not scored by Judge", "grand_insight": None,
            }
            continue

        agent_scores = scores[agent]
        for axis in ("novelty", "accuracy", "impact", "challenge"):
            val = agent_scores.get(axis, 0)
            if not isinstance(val, int) or val not in VALID_SCORES:
                # Clamp: if between 4-9, round to 3. If > 10, cap at 10. If < 0, floor at 0.
                if isinstance(val, (int, float)):
                    val = int(val)
                    if val < 0:
                        val = 0
                    elif 4 <= val <= 9:
                        val = 3
                    elif val > 10:
                        val = 10
                else:
                    val = 0
                logger.warning("Clamped %s.%s from %s to %d", agent, axis, agent_scores.get(axis), val)
                agent_scores[axis] = val

    return data


def judge_score(
    briefing_text: str,
    transcript: list[dict],
    workers: list[str],
    rt_id: str,
) -> dict:
    """Score all workers using Sonnet Judge. Returns results dict.

    On success: {"status": "scored", "scores": [...], "rt_id": rt_id}
    On failure: {"status": "failed", "error": "...", "rt_id": rt_id}

    Caller (runner) must handle "failed" status by notifying Admin.
    There is no silent fallback.
    """
    formatted_transcript, anon_to_agent = _format_transcript(transcript)

    # The whole briefing, names scrubbed like the transcript (it was cut at
    # 3,000 characters, which dropped most of the canon and any priorities).
    brief_max = 60000
    scored_briefing = _anonymize_text(briefing_text, anon_to_agent)
    if len(scored_briefing) > brief_max:
        logger.warning("Scorer briefing cut from %d to %d chars", len(scored_briefing), brief_max)
        scored_briefing = scored_briefing[:brief_max]
    prompt = JUDGE_PROMPT.format(
        briefing=scored_briefing,
        transcript=formatted_transcript,
    )

    logger.info("Calling Sonnet Judge for RT %s (%d workers, ~%d chars prompt)",
                rt_id, len(workers), len(prompt))

    # S6: log raw output to trace directory
    trace_dir = WRITE_ROOT / "agents" / "judge" / "trace"
    trace_dir.mkdir(parents=True, exist_ok=True)

    # First attempt
    raw = _call_sonnet(prompt)
    if raw:
        # S6: trace log
        trace_file = trace_dir / f"{time.strftime('%Y%m%d_%H%M%S')}_{rt_id}.txt"
        trace_file.write_text(raw, encoding="utf-8")
        logger.info("Judge trace saved: %s", trace_file.name)

        parsed = _parse_scores(raw, workers, anon_to_agent)
        if parsed:
            # S4: adversarial verification on exceptional scores
            parsed = _adversarial_verification(parsed, workers, briefing_text[:1000])
            return _record_scores(parsed, workers, rt_id)

    # Retry once — shorter instructions, same blinded transcript
    logger.warning("First attempt failed, retrying with condensed prompt")
    retry_prompt = (
        f"Score these roundtable debate reviewers: {', '.join(sorted(anon_to_agent))}.\n\n"
        f"Topic: {_anonymize_text(briefing_text[:1000], anon_to_agent)}\n\n"
        f"Transcript:\n{formatted_transcript}\n\n"
        f"Score each on novelty, accuracy, impact, challenge (0/1/2/3/10). "
        f"Respond with ONLY valid JSON: {{\"scores\": {{\"agent\": {{\"novelty\": N, \"accuracy\": N, "
        f"\"impact\": N, \"challenge\": N, \"reasoning\": \"...\", \"grand_insight\": null}}}}}}"
    )
    raw = _call_sonnet(retry_prompt)
    if raw:
        # S6: trace log (retry)
        trace_file = trace_dir / f"{time.strftime('%Y%m%d_%H%M%S')}_{rt_id}_retry.txt"
        trace_file.write_text(raw, encoding="utf-8")

        parsed = _parse_scores(raw, workers, anon_to_agent)
        if parsed:
            parsed = _adversarial_verification(parsed, workers, briefing_text[:1000])
            return _record_scores(parsed, workers, rt_id)

    # Both attempts failed
    error_msg = "Judge scorer failed after 2 attempts. Manual scoring required."
    logger.error(error_msg)
    return {"status": "failed", "error": error_msg, "rt_id": rt_id}


def _adversarial_verification(parsed: dict, workers: list[str], briefing_excerpt: str) -> dict:
    """S4: Challenge any axis==3 score. Strip reasoning to prevent anchoring.

    Revise up allowed if reasoning contains exceptional/discontinuity language at score 2.
    Cross-agent calibration when >=3 agents share axis==3 on same dimension.
    CONFIRM fallback on parse failure — original scores stand.
    """
    import re as _re
    scores = parsed.get("scores", {})
    agents_to_challenge: list[tuple[str, list[str]]] = []  # (agent, [axes at 3])

    for agent in workers:
        s = scores.get(agent, {})
        high_axes = [ax for ax in ("novelty", "accuracy", "impact", "challenge") if s.get(ax) == 3]
        if high_axes:
            agents_to_challenge.append((agent, high_axes))

    if not agents_to_challenge:
        # Check for revise-up candidates: score==2 with exceptional reasoning
        for agent in workers:
            s = scores.get(agent, {})
            reasoning = s.get("reasoning", "").lower()
            if any(kw in reasoning for kw in ("exceptional", "discontinuity", "paradigm", "breakthrough")):
                two_axes = [ax for ax in ("novelty", "accuracy", "impact", "challenge") if s.get(ax) == 2]
                if two_axes:
                    agents_to_challenge.append((agent, two_axes))

    if not agents_to_challenge:
        return parsed

    # Cross-agent calibration: check if >=3 agents share axis==3 on same dim
    dim_counts: dict[str, list[str]] = {}
    for agent in workers:
        s = scores.get(agent, {})
        for ax in ("novelty", "accuracy", "impact", "challenge"):
            if s.get(ax) == 3:
                dim_counts.setdefault(ax, []).append(agent)
    calibration_dims = {dim: agents for dim, agents in dim_counts.items() if len(agents) >= 3}

    # Build adversarial prompt
    challenge_lines = []
    for agent, axes in agents_to_challenge:
        s = scores.get(agent, {})
        # Strip reasoning to prevent anchoring
        score_line = ", ".join(f"{ax}={s.get(ax, 0)}" for ax in ("novelty", "accuracy", "impact", "challenge"))
        challenge_lines.append(
            f"Agent {agent}: {score_line}. "
            f"Note: if your original was 4-9, it was clamped to 3; the correct score may be 2."
        )

    if calibration_dims:
        for dim, agents in calibration_dims.items():
            challenge_lines.append(
                f"CALIBRATION: {len(agents)} agents scored {dim}=3: {', '.join(agents)}. "
                f"Are any of these indistinguishable in quality on {dim}?"
            )

    adversarial_prompt = (
        f"You previously scored these agents. Re-evaluate ONLY the flagged scores below.\n"
        f"Briefing excerpt: {briefing_excerpt[:1000]}\n\n"
        f"{chr(10).join(challenge_lines)}\n\n"
        f"For each agent, respond: CONFIRM or REVISE agent_name axis new_score reason\n"
        f"Respond as plain text, one line per decision."
    )

    raw = _call_sonnet(adversarial_prompt)
    if not raw:
        logger.warning("Adversarial verification failed — keeping original scores (CONFIRM fallback)")
        return parsed

    # Parse adversarial response
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        revise_match = _re.match(
            r"REVISE\s+(\w+)\s+(novelty|accuracy|impact|challenge)\s+(\d+)\s*(.*)",
            line, _re.IGNORECASE,
        )
        if revise_match:
            agent_name = revise_match.group(1)
            axis = revise_match.group(2).lower()
            new_val = int(revise_match.group(3))
            if new_val in VALID_SCORES and agent_name in scores:
                old_val = scores[agent_name].get(axis, 0)
                scores[agent_name][axis] = new_val
                logger.info("Adversarial: REVISE %s.%s %d->%d", agent_name, axis, old_val, new_val)

    return parsed


def _record_scores(parsed: dict, workers: list[str], rt_id: str) -> dict:
    """Record scores via scorer.py and return results."""
    scores_dict = parsed["scores"]
    results = []

    for agent in workers:
        agent_scores = scores_dict.get(agent, {})
        novelty = agent_scores.get("novelty", 0)
        accuracy = agent_scores.get("accuracy", 0)
        impact = agent_scores.get("impact", 0)
        challenge = agent_scores.get("challenge", 0)
        reasoning = agent_scores.get("reasoning", "")
        grand_insight = agent_scores.get("grand_insight")

        total = novelty + accuracy + impact + challenge

        try:
            result = subprocess.run(
                [sys.executable, str(SUITE_ROOT / "engine" / "scorer.py"),
                 "score", agent,
                 str(novelty), str(accuracy), str(impact), str(challenge),
                 "--rt", rt_id],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                score_data = json.loads(result.stdout)
                score_data["reasoning"] = reasoning
                score_data["grand_insight"] = grand_insight
                score_data["scored_by"] = "judge-sonnet"
                results.append(score_data)
                logger.info("Scored %s: N=%d A=%d I=%d C=%d (total=%d)%s",
                            agent, novelty, accuracy, impact, challenge, total,
                            " [GRAND INSIGHT]" if grand_insight else "")
            else:
                logger.error("scorer.py failed for %s: %s", agent, result.stderr[:200])
                results.append({
                    "agent": agent, "error": result.stderr[:200],
                    "novelty": novelty, "accuracy": accuracy,
                    "impact": impact, "challenge": challenge,
                })
        except Exception as e:
            logger.error("Scorer exception for %s: %s", agent, e)
            results.append({"agent": agent, "error": str(e)})

    # Also record to DB if available
    _record_to_db(scores_dict, workers, rt_id)

    return {"status": "scored", "scores": results, "rt_id": rt_id}


def _record_to_db(scores_dict: dict, workers: list[str], rt_id: str):
    """Record scores to the scores table in SQLite."""
    try:
        from db import get_db
        with get_db() as conn:
            for agent in workers:
                s = scores_dict.get(agent, {})
                novelty = s.get("novelty", 0)
                accuracy = s.get("accuracy", 0)
                impact = s.get("impact", 0)
                challenge = s.get("challenge", 0)
                total = novelty + accuracy + impact + challenge
                conn.execute(
                    "INSERT INTO scores (roundtable_id, agent_name, novelty, accuracy, "
                    "impact, challenge, total, reasoning, grand_insight, scored_by, scored_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (rt_id, agent, novelty, accuracy, impact, challenge, total,
                     s.get("reasoning", ""), s.get("grand_insight"),
                     "judge-sonnet", time.time()),
                )
            conn.commit()
            logger.info("Scores recorded to DB for RT %s", rt_id)
    except Exception as e:
        logger.warning("DB score recording failed (non-fatal): %s", e)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Judge Scorer — Sonnet evaluation")
    parser.add_argument("--digest", required=True, help="Path to digest JSON file")
    args = parser.parse_args()

    digest_path = Path(args.digest)
    if not digest_path.exists():
        print(json.dumps({"error": f"Digest not found: {args.digest}"}))
        sys.exit(1)

    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    transcript = digest.get("transcript", [])
    rt_id = digest.get("roundtable_id", "unknown")
    topic = digest.get("topic", "")

    # Extract workers from contributions (exclude runner, judge, assistant)
    workers = [a for a in digest.get("contributions", {}).keys()
               if a not in ("runner", "assistant", "judge")]

    # Try to load briefing from the transcript (first runner message)
    briefing_text = ""
    for msg in transcript:
        if msg.get("agent") == "runner" and "BRIEFING:" in msg.get("message", ""):
            briefing_text = msg["message"].replace("BRIEFING:", "", 1).strip()
            break

    if not briefing_text:
        briefing_text = f"Topic: {topic}"

    result = judge_score(briefing_text, transcript, workers, rt_id)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "scored" else 1)
