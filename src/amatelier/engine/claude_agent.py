"""Claude worker agent — responds only when called on by the runner.

Usage:
    python engine/claude_agent.py --agent <worker> --model sonnet
    python engine/claude_agent.py --agent judge --model sonnet

Workers respond to YOUR TURN signals (SPEAK, REBUTTAL, FLOOR).
Judge responds to every new worker message (live moderator).
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

from db import get_active_roundtable, init_read_cursor, is_roundtable_open, listen, speak

logger = logging.getLogger(__name__)

# Windows subprocess-tree hang fix — see claude-suite RT-4 post-mortem.
# subprocess.run(timeout=) with capture_output does not actually time out
# when the claude CLI spawns node.exe grandchildren that inherit the
# captured stdout/stderr pipes. _force_kill_tree walks the tree on Windows
# so the inherited handles close and communicate() can return.
_IS_WINDOWS = sys.platform == "win32"


def _force_kill_tree(pid: int) -> None:
    """Kill a process and every descendant. Windows-first, POSIX fallback."""
    if _IS_WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        except Exception as exc:
            logger.warning("taskkill failed for pid %s: %s", pid, exc)
    else:
        try:
            os.killpg(os.getpgid(pid), 9)
        except Exception as exc:
            logger.warning("killpg failed for pid %s: %s", pid, exc)


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


def _log_call_error(agent_name: str, exc: BaseException, stderr_excerpt: str = "") -> None:
    """Append a per-agent call error line to roundtable-server/logs/<agent>_calls.log.

    The Popen-captured stderr doesn't survive runner shutdown — a dedicated
    log file makes rate-limit / hang / crash modes diagnosable after the fact.
    """
    try:
        log_dir = WRITE_ROOT / "roundtable-server" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{agent_name}_calls.log"
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {type(exc).__name__}: {exc}"
        if stderr_excerpt:
            line += f" | stderr: {stderr_excerpt.strip()[:400]}"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _load_config() -> dict:
    config_path = SUITE_ROOT / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))
    return {}


def load_agent_context(agent_name: str) -> str:
    """Load the agent's full context: CLAUDE.md + MEMORY.md + metrics + skills.

    Also prepends a JIT-selected "Active Heuristics" block when the runner
    has written one for this RT (see roundtable_runner._write_active_heuristics).
    Placed FIRST so it wins attention precedence over stale content in
    CLAUDE.md — the runner's per-RT selection supersedes anything the
    agent may still carry in its learned behaviors section.
    """
    agent_dir = WRITE_ROOT / "agents" / agent_name
    parts = []

    active_heuristics = agent_dir / "active_heuristics_current.md"
    if active_heuristics.exists():
        parts.append(active_heuristics.read_text(encoding="utf-8"))
        parts.append("\n---\n")

    claude_md = agent_dir / "CLAUDE.md"
    if claude_md.exists():
        parts.append(claude_md.read_text(encoding="utf-8"))

    # Structured memory system — replaces raw MEMORY.md with first-person narrative
    try:
        from agent_memory import render_memory
        rendered = render_memory(agent_name)
        if rendered and rendered.strip() != "# My Memory":
            parts.append(f"\n---\n{rendered}")
    except ImportError:
        # Fallback to raw MEMORY.md if agent_memory not available
        memory_md = agent_dir / "MEMORY.md"
        if memory_md.exists():
            parts.append(f"\n---\n# Your Memory\n{memory_md.read_text(encoding='utf-8')}")

    metrics_path = agent_dir / "metrics.json"
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            tier_labels = {0: "Starting", 1: "Expanded Context", 2: "Model Upgrade", 3: "Autonomous"}
            tier = metrics.get("tier", 0)
            parts.append(f"\n---\n# Your Metrics\n- Tier: {tier} ({tier_labels.get(tier, 'Unknown')})")
            parts.append(f"- Assignments: {metrics.get('assignments', 0)}")
            parts.append(f"- Avg Score: {metrics.get('avg_score', 0)}/12")
        except (json.JSONDecodeError, OSError):
            pass

    skills_dir = agent_dir / "skills"
    if skills_dir.exists():
        skill_files = sorted(skills_dir.glob("*.md"))
        if skill_files:
            parts.append("\n---\n# Your Learned Skills")
            for sf in skill_files[:10]:
                parts.append(sf.read_text(encoding="utf-8").strip())

    # Load settled decisions — prevents rehashing resolved debates
    notes_path = SUITE_ROOT / "notes.md"
    if notes_path.exists():
        parts.append(f"\n---\n{notes_path.read_text(encoding='utf-8')}")

    return "\n".join(parts)


def _select_context(conversation: list[dict], call_type: str) -> list[dict]:
    """Select relevant context: briefing + latest round summary + current round messages.

    Agents get a bounded window regardless of how many rounds have passed:
      1. The briefing (always)
      2. The runner's most recent ROUND N SUMMARY (Haiku-generated, covers prior rounds)
      3. All messages from the current round
    """
    briefing = None
    latest_summary = None
    last_round_start = 0

    for i, msg in enumerate(conversation):
        if msg["agent"] == "runner" and msg.get("message", "").startswith("BRIEFING:"):
            briefing = msg
        if msg["agent"] == "runner" and "SUMMARY:" in msg.get("message", ""):
            latest_summary = msg
        # Match "ROUND N: begin" specifically, not any message containing "begin"
        if msg["agent"] == "runner":
            text = msg.get("message", "")
            if text.startswith("ROUND ") and ": begin" in text:
                last_round_start = i

    context: list[dict] = []
    if briefing:
        context.append(briefing)
    if latest_summary:
        context.append({"agent": "runner", "message": f"[DEBATE STATE — all prior rounds]\n{latest_summary['message']}"})
    context.extend(conversation[last_round_start:])

    # Judge gets more raw context since it needs to see patterns across messages
    if call_type == "JUDGE" and len(context) < 8:
        return conversation[-25:] if len(conversation) > 25 else conversation

    return context


def _build_prompt(conversation: list[dict], agent_name: str, call_type: str) -> str:
    """Build the prompt based on debate phase (SPEAK, REBUTTAL, FLOOR, or JUDGE)."""
    context = _select_context(conversation, call_type)
    messages = [f"[{m['agent']}]: {m['message']}" for m in context]
    conversation_text = "\n\n".join(messages)

    base_rules = (
        "- Write ONLY your contribution — the actual words you want posted\n"
        "- Do NOT add meta-commentary like 'I've argued...' or 'My contribution focuses on...'\n"
        "- Do NOT wrap your response in a code block or prefix it with your name\n"
        "- Post ONCE. Do NOT summarize your own contribution after posting it.\n"
        "- Do NOT use any tools (Bash, Read, Write, etc.) — just write your response as plain text"
    )

    focus_rule = (
        "\n\nFOCUS: Stay on the directive. Do NOT expand into tangential topics or broader discussions. "
        "If you think of a related topic worth exploring, add it as a single line at the end: "
        "'SUGGESTED FOLLOW-UP: [topic]' — but do not pursue it yourself."
    )

    if call_type == "SPEAK":
        phase_instruction = (
            f"You've been called to SPEAK. Present your position on the current directive.\n"
            f"Be concise (200-400 words). Address the briefing question directly.\n"
            f"If previous speakers have already spoken this round, engage with their points.\n"
            f"Post evidence (line numbers, method names) not just opinions.\n"
            f"Address at least one other agent by name."
            f"{focus_rule}"
        )
    elif call_type == "REBUTTAL":
        phase_instruction = (
            f"You've been called to REBUTTAL. Respond to what was said in this round's speak phase.\n"
            f"Be concise (150-300 words). You MUST engage with specific arguments from other agents.\n"
            f"Challenge weak points, defend your position with new evidence, or build on others' ideas.\n"
            f"Name the agents you're responding to."
            f"{focus_rule}"
        )
    elif call_type == "FLOOR":
        # Extract budget and round info from conversation
        remaining_budget = "?"
        current_round = "?"
        for msg in reversed(conversation):
            text = msg.get("message", "")
            if msg["agent"] == "runner" and "budget:" in text.lower() and agent_name in text:
                try:
                    remaining_budget = text.split("budget:")[1].split("remaining")[0].strip()
                except (IndexError, ValueError):
                    pass
                break
        for msg in reversed(conversation):
            if msg["agent"] == "runner" and "ROUND" in msg.get("message", "") and "begin" in msg.get("message", ""):
                try:
                    current_round = msg["message"].split("ROUND")[1].split(":")[0].strip()
                except (IndexError, ValueError):
                    pass
                break

        phase_instruction = (
            f"You've been given a FLOOR turn (extra budget turn).\n"
            f"Budget remaining: {remaining_budget} turns. Current round: {current_round}.\n\n"
            f"FLOOR STRATEGY — READ THIS:\n"
            f"- You have a FIXED number of floor turns for the ENTIRE roundtable (all rounds)\n"
            f"- Once you spend them all, you can only speak during SPEAK and REBUTTAL phases\n"
            f"- Later rounds often matter more — that's when synthesis and final positions form\n"
            f"- Spending all floor turns in round 1 means silence on the floor for rounds 2+\n"
            f"- PASS is a strategic move, not a forfeit. Save turns for when you have an edge.\n\n"
            f"If you have nothing NEW to add (not covered in SPEAK or REBUTTAL), say: PASS\n"
            f"If contributing: one focused point, 100-200 words max. Make it count.\n"
            f"Stay on the directive. If you have a tangential idea, add 'SUGGESTED FOLLOW-UP: [topic]' at the end instead of expanding into it."
        )
    else:  # JUDGE
        phase_instruction = (
            f"You are the live moderator. A new message has been posted.\n"
            f"Check if it addresses the current round's directive.\n"
            f"If the agent expanded into tangential topics instead of staying on the directive: post a REDIRECT and note the off-topic expansion.\n"
            f"If off-directive: post a REDIRECT. Off-directive contributions earn a -5 spark penalty.\n"
            f"If quality issues: post feedback.\n"
            f"If clean: respond with exactly: PASS"
        )

    return f"""# Current Roundtable Discussion

{conversation_text}

---
It's your turn. Respond as {agent_name}.

{phase_instruction}

{base_rules}"""


def call_claude(system_prompt: str, prompt: str, agent_name: str, model: str) -> str:
    """Call Claude.

    In ``claude-code`` mode: uses the ``claude`` CLI (the way atelier
    originally worked; preserves all agent-specific flags).
    In ``anthropic-sdk`` or ``openai-compat`` mode: routes through the
    SDK backend — no Claude Code installation required.
    """
    # Try open-mode backend first. Returns None if we should fall through
    # to the CLI path (claude-code mode, or backend unavailable).
    try:
        from amatelier.llm_backend import get_backend, BackendUnavailable
        backend = get_backend()
        if backend.name != "claude-code":
            try:
                result = backend.complete(
                    system=system_prompt, prompt=prompt,
                    model=model, max_tokens=8000, timeout=300,
                )
                return result.text
            except BackendUnavailable:
                pass
            except Exception:
                # SDK failure — fall back to CLI if available
                pass
    except ImportError:
        pass

    # Legacy CLI path
    config = _load_config()
    rt_cfg = config.get("roundtable", {})
    context_limit = rt_cfg.get("context_limit", 60000)
    if len(system_prompt) > context_limit:
        logger.warning("Context for %s cut from %d to %d chars (roundtable.context_limit)",
                       agent_name, len(system_prompt), context_limit)
    agent_def = json.dumps({
        agent_name: {
            "description": f"Roundtable agent {agent_name}",
            "prompt": system_prompt[:context_limit],
        }
    })
    # The definition goes in a file, not on the command line: Windows caps a
    # command line at 32,767 characters and an agent's context is larger. In
    # --print mode the CLI reads --agents from a file path. (The inline form,
    # with an 8,000-character cap, cut every agent's identity short.)
    defs_dir = WRITE_ROOT / "agent-defs"
    defs_dir.mkdir(parents=True, exist_ok=True)
    agent_def_path = defs_dir / f"{agent_name}.json"
    agent_def_path.write_text(agent_def, encoding="utf-8")

    from amatelier.llm_backend import claude_cli_isolation_args
    cmd = [
        "claude",
        "-p",
        "--model", model,
        "--agent", agent_name,
        "--agents", str(agent_def_path),
        *claude_cli_isolation_args(),
        "--no-session-persistence",
        "--output-format", "text",
        "--disable-slash-commands",
        "--dangerously-skip-permissions",
        "--max-budget-usd", "5.00",
        "--allowedTools", "",
    ]
    # Judge gets max effort for thorough moderation and citation enforcement
    if agent_name == "judge":
        cmd.extend(["--effort", "max"])

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    # A turn that outlives this is killed with its whole process tree. Long
    # debate turns on a full context legitimately run past two minutes, so the
    # limit is configurable (roundtable.cli_timeout_seconds).
    cli_timeout = rt_cfg.get("cli_timeout_seconds", 600)

    popen_kwargs: dict = dict(
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(WORKSPACE_ROOT), encoding="utf-8", errors="replace", env=env,
    )
    if _IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)
    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=cli_timeout)
    except subprocess.TimeoutExpired:
        _force_kill_tree(proc.pid)
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        raise

    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (exit {proc.returncode}): {(stderr or '')[:500]}"
        )

    return (stdout or "").strip()


def _strip_meta(response: str, agent_name: str) -> str:
    """Strip meta-narration that wraps the actual contribution."""
    lines = response.strip().split("\n")

    meta_prefixes = (
        "contribution posted", "my contribution", "i've posted", "i have posted",
        "posted.", "here's what i", "here is what i", "my response",
        f"{agent_name}'s contribution", f"{agent_name} has posted",
    )
    while lines and lines[0].strip().lower().startswith(meta_prefixes):
        lines.pop(0)

    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "---":
            after = "\n".join(lines[i + 1:]).strip().lower()
            if any(after.startswith(p) for p in meta_prefixes):
                lines = lines[:i]
            break

    result = "\n".join(lines).strip()
    return result if result else response.strip()


def _detect_call(new_msgs: list[dict], agent_name: str) -> str | None:
    """Detect if the runner called this agent. Returns call type or None."""
    for msg in new_msgs:
        if msg["agent"] == "runner" and f"YOUR TURN: {agent_name}" in msg["message"]:
            text = msg["message"]
            if "SPEAK" in text:
                return "SPEAK"
            elif "REBUTTAL" in text:
                return "REBUTTAL"
            elif "FLOOR" in text:
                return "FLOOR"
            return "SPEAK"  # fallback
    return None


def _has_new_worker_message(new_msgs: list[dict], agent_name: str,
                            last_judged: str | None = None) -> tuple[bool, str | None]:
    """Check if there's a new message from a worker (not runner, not self).

    Returns (should_respond, worker_name). Filters out consecutive posts from the
    same worker the Judge already responded to (prevents double-post spiral).
    """
    for msg in new_msgs:
        if msg["agent"] not in ("runner", "judge", "assistant", agent_name):
            if msg["agent"] == last_judged:
                # Same worker posted again — skip (likely self-summary)
                logger.info("Skipping consecutive post from %s (already judged)", msg["agent"])
                continue
            return True, msg["agent"]
    # Check if there's a runner phase signal that resets the tracking
    for msg in new_msgs:
        if msg["agent"] == "runner" and any(
            phase in msg.get("message", "")
            for phase in ("SPEAK PHASE", "REBUTTAL PHASE", "FLOOR PHASE", "JUDGE GATE", "ROUND")
        ):
            return False, None  # Phase change resets — don't carry last_judged across phases
    return False, last_judged


def run_agent(agent_name: str, model: str):
    """Main loop: wait for call → respond → repeat until roundtable closes."""
    is_judge = agent_name == "judge"
    logger.info("Starting %s (Claude %s) [%s]", agent_name, model, "judge" if is_judge else "worker")

    system_prompt = load_agent_context(agent_name)
    logger.info("Loaded context for %s (%d chars)", agent_name, len(system_prompt))

    # Wait for an active roundtable
    rt_id = None
    for _ in range(60):
        rt_id = get_active_roundtable()
        if rt_id:
            break
        time.sleep(1)

    if not rt_id:
        logger.error("No active roundtable found after 60s. Exiting.")
        return

    logger.info("Joined roundtable %s", rt_id)

    # Initialize read cursor
    init_read_cursor(agent_name, rt_id)

    all_messages: list[dict] = []
    responded_signals: set[str] = set()  # Track "YOUR TURN" signals we already responded to
    last_judged_worker: str | None = None  # Track last worker the Judge responded to
    _session_saved = {"done": False}

    def _save_session(tag: str = "clean") -> None:
        """Write session transcript. Called on clean close AND on abort."""
        try:
            session_dir = WRITE_ROOT / "agents" / agent_name / "sessions"
            session_dir.mkdir(parents=True, exist_ok=True)
            session_file = session_dir / f"{time.strftime('%Y-%m-%d_%H%M%S')}_{tag}.json"
            session_file.write_text(json.dumps({
                "roundtable_id": rt_id,
                "agent": agent_name,
                "model": model,
                "messages": all_messages,
                "timestamp": time.time(),
                "exit_tag": tag,
            }, indent=2), encoding="utf-8")
            logger.info("Session saved to %s", session_file)
        except Exception as save_exc:
            logger.warning("Session save failed: %s", save_exc)
        _session_saved["done"] = True

    # Fallback save on abnormal termination (SIGTERM, taskkill from runner).
    import atexit
    atexit.register(lambda: None if _session_saved["done"] else _save_session("abort"))

    while True:
        rt_open = is_roundtable_open(rt_id)

        new_msgs = listen(agent_name, rt_id)
        if new_msgs:
            all_messages.extend(new_msgs)

            should_respond = False
            call_type = None
            signal_text = None

            if is_judge:
                # Judge responds to worker messages and end-of-round signals
                has_worker_msg, worker_name = _has_new_worker_message(
                    new_msgs, agent_name, last_judged=last_judged_worker)
                has_end_signal = any(
                    m["agent"] == "runner" and "end" in m["message"].lower() and "judge" in m["message"].lower()
                    for m in new_msgs
                )
                # Reset tracking on phase changes
                for m in new_msgs:
                    if m["agent"] == "runner" and any(
                        phase in m.get("message", "")
                        for phase in ("SPEAK PHASE", "REBUTTAL PHASE", "FLOOR PHASE", "JUDGE GATE", "ROUND")
                    ):
                        last_judged_worker = None
                if has_worker_msg or has_end_signal:
                    should_respond = True
                    call_type = "JUDGE"
                    if worker_name:
                        last_judged_worker = worker_name
            else:
                # Workers only respond when explicitly called on
                call_type = _detect_call(new_msgs, agent_name)
                if call_type:
                    # Deduplicate: extract the exact signal text and skip if already handled
                    signal_text = None
                    for msg in new_msgs:
                        if msg["agent"] == "runner" and f"YOUR TURN: {agent_name}" in msg["message"]:
                            signal_text = msg["message"]
                            break
                    if signal_text and signal_text not in responded_signals:
                        should_respond = True
                    else:
                        should_respond = False

            last_is_ours = new_msgs[-1]["agent"] == agent_name

            if should_respond and not last_is_ours:
                logger.info("Responding to %s call (%d messages in context)",
                            call_type, len(all_messages))
                try:
                    prompt = _build_prompt(all_messages, agent_name, call_type)
                    response = call_claude(system_prompt, prompt, agent_name, model)
                    response = _strip_meta(response, agent_name)

                    # Judge: don't post if response is just PASS (nothing to moderate)
                    if is_judge and response.strip().upper() == "PASS":
                        logger.info("Judge: nothing to moderate, staying silent")
                    else:
                        speak(agent_name, rt_id, response)
                        all_messages.append({"agent": agent_name, "message": response})
                        logger.info("Posted %s response (%d chars)", call_type, len(response))

                    # Mark this signal as handled so we don't respond to it again
                    if signal_text:
                        responded_signals.add(signal_text)

                    time.sleep(3)
                except Exception as e:
                    stderr_excerpt = getattr(e, "stderr", "") or ""
                    logger.error("Claude CLI error: %s", e)
                    _log_call_error(agent_name, e, str(stderr_excerpt))
                    time.sleep(15)

        if not rt_open:
            logger.info("Roundtable closed. Exiting.")
            break

        time.sleep(2)

    logger.info("Roundtable %s closed. %s exiting.", rt_id, agent_name)
    _save_session("clean")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Claude agent for roundtable debates")
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument("--model", default="sonnet", help="Claude model (default: sonnet)")
    args = parser.parse_args()
    run_agent(args.agent, args.model)
