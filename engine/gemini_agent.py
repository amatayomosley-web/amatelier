"""Naomi's Gemini 3.0 Pro wrapper — responds only when called on by the runner."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from db import get_active_roundtable, init_read_cursor, is_roundtable_open, listen, speak

logger = logging.getLogger(__name__)

SUITE_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = SUITE_ROOT / "roundtable-server" / "logs"


def load_agent_context(agent_name: str) -> str:
    agent_dir = SUITE_ROOT / "agents" / agent_name
    parts = []
    claude_md = agent_dir / "CLAUDE.md"
    memory_md = agent_dir / "MEMORY.md"
    if claude_md.exists():
        parts.append(claude_md.read_text(encoding="utf-8"))
    # Structured memory system — replaces raw MEMORY.md with first-person narrative
    try:
        from agent_memory import render_memory
        rendered = render_memory(agent_name)
        if rendered and rendered.strip() != "# My Memory":
            parts.append(f"\n---\n{rendered}")
            memory_md = None  # Skip raw fallback
    except ImportError:
        pass  # Fall through to raw MEMORY.md
    if memory_md and memory_md.exists():
        parts.append(f"\n---\n# Your Memory\n{memory_md.read_text(encoding='utf-8')}")
    notes_path = SUITE_ROOT / "notes.md"
    if notes_path.exists():
        parts.append(f"\n---\n{notes_path.read_text(encoding='utf-8')}")
    return "\n".join(parts)


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
            return "SPEAK"
    return None


def _select_context(conversation: list[dict]) -> list[dict]:
    """Select: briefing + latest round summary + current round messages."""
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
    return context


def _build_prompt(system_prompt: str, conversation: list[dict], agent_name: str, call_type: str) -> str:
    """Build prompt based on debate phase."""
    context = _select_context(conversation)
    context = _truncate_context(context, MAX_PROMPT_CHARS - len(system_prompt))
    messages = [f"[{m['agent']}]: {m['message']}" for m in context]
    conversation_text = "\n\n".join(messages)

    focus_rule = (
        "\n\nFOCUS: Stay on the directive. Do NOT expand into tangential topics. "
        "If you think of a related topic worth exploring, add 'SUGGESTED FOLLOW-UP: [topic]' at the end."
    )

    if call_type == "SPEAK":
        phase = (
            "You've been called to SPEAK. Present your position on the current directive.\n"
            "Be concise (200-400 words). Engage with previous speakers if any.\n"
            "Address at least one other agent by name."
            f"{focus_rule}"
        )
    elif call_type == "REBUTTAL":
        phase = (
            "You've been called to REBUTTAL. Respond to this round's speak phase.\n"
            "Be concise (150-300 words). Challenge, defend, or build on specific arguments.\n"
            "Name the agents you're responding to."
            f"{focus_rule}"
        )
    else:  # FLOOR
        phase = (
            "You've been given a FLOOR turn (extra budget turn).\n\n"
            "FLOOR STRATEGY:\n"
            "- You have a FIXED number of floor turns for the ENTIRE roundtable (all rounds)\n"
            "- Once spent, you can only speak during SPEAK and REBUTTAL phases\n"
            "- Later rounds often matter more — synthesis and final positions form there\n"
            "- PASS is strategic, not surrender. Save turns for when you have a real edge.\n\n"
            "If you have nothing NEW beyond your SPEAK/REBUTTAL, say: PASS\n"
            "If contributing: one focused point, 100-200 words. Make it count.\n"
            "Stay on the directive. Tangential ideas go to 'SUGGESTED FOLLOW-UP: [topic]' at the end."
        )

    return f"""{system_prompt}

---
# Current Roundtable Discussion

{conversation_text}

---
It's your turn. Respond as {agent_name}.

{phase}

- Write ONLY your contribution
- Do NOT add meta-commentary
- Do NOT prefix with your name"""


# Shared Gemini client — retries, rate limiting, error detail all in one place
from gemini_client import call_gemini  # noqa: E402


MAX_PROMPT_CHARS = 60000  # ~15K tokens — safe for Flash


def _truncate_context(messages: list[dict], max_chars: int) -> list[dict]:
    """Truncate oldest non-briefing messages if context exceeds limit."""
    total = sum(len(m.get("message", "")) for m in messages)
    if total <= max_chars:
        return messages
    # Keep first message (briefing) and trim from the start of the rest
    if not messages:
        return messages
    result = [messages[0]]
    remaining = messages[1:]
    total = len(messages[0].get("message", ""))
    # Walk backwards — keep most recent messages
    kept = []
    for m in reversed(remaining):
        msg_len = len(m.get("message", ""))
        if total + msg_len <= max_chars:
            kept.append(m)
            total += msg_len
        else:
            break
    kept.reverse()
    result.extend(kept)
    logger.warning("Context truncated: %d -> %d messages (%d chars)",
                   len(messages), len(result), total)
    return result


def run_agent(agent_name: str):
    """Wait for call -> respond -> repeat until roundtable closes."""
    # Set up file logging
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"naomi_{time.strftime('%Y%m%d_%H%M%S')}.log"
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.setLevel(logging.DEBUG)

    logger.info("Starting %s (Gemini 3.0 Pro)", agent_name)

    system_prompt = load_agent_context(agent_name)
    logger.info("Loaded context for %s (%d chars)", agent_name, len(system_prompt))

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

    init_read_cursor(agent_name, rt_id)

    all_messages: list[dict] = []
    consecutive_failures = 0
    max_consecutive_failures = 3  # Self-exit after 3 failures so runner can restart fresh

    while True:
        rt_open = is_roundtable_open(rt_id)

        new_msgs = listen(agent_name, rt_id)
        if new_msgs:
            all_messages.extend(new_msgs)

            call_type = _detect_call(new_msgs, agent_name)
            last_is_ours = new_msgs[-1]["agent"] == agent_name

            if call_type and not last_is_ours:
                logger.info("Responding to %s call (%d messages in context)",
                            call_type, len(all_messages))
                try:
                    prompt = _build_prompt(system_prompt, all_messages, agent_name, call_type)
                    logger.debug("Prompt size: %d chars (~%d tokens)",
                                 len(prompt), len(prompt) // 4)
                    response = call_gemini(prompt)
                    speak(agent_name, rt_id, response)
                    all_messages.append({"agent": agent_name, "message": response})
                    logger.info("Posted %s response (%d chars)", call_type, len(response))
                    consecutive_failures = 0
                except Exception as e:
                    consecutive_failures += 1
                    logger.error("Gemini API error (failure %d/%d): %s",
                                 consecutive_failures, max_consecutive_failures, e)
                    if consecutive_failures >= max_consecutive_failures:
                        logger.critical(
                            "Hit %d consecutive failures. Exiting so runner can restart.",
                            max_consecutive_failures)
                        break

        if not rt_open:
            logger.info("Roundtable closed. Exiting.")
            break

        time.sleep(2)

    logger.info("Roundtable %s closed. %s exiting.", rt_id, agent_name)

    session_dir = SUITE_ROOT / "agents" / agent_name / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_file = session_dir / f"{time.strftime('%Y-%m-%d_%H%M%S')}.json"
    session_file.write_text(json.dumps({
        "roundtable_id": rt_id,
        "agent": agent_name,
        "model": "gemini-3-pro-preview",
        "messages": all_messages,
        "timestamp": time.time(),
    }, indent=2), encoding="utf-8")
    logger.info("Session saved to %s", session_file)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Naomi — Gemini 3.0 Pro agent")
    parser.add_argument("--agent", default="naomi", help="Agent name (default: naomi)")
    args = parser.parse_args()
    run_agent(args.agent)
