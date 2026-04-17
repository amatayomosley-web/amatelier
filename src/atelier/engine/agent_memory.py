"""Agent Memory System — structured persistent memory that makes agents feel continuous.

Replaces the append-only MEMORY.md with a structured document containing:
  - Session bridge: "Last time you..." continuity from previous RT
  - Episodes: First-person vivid memories of key moments
  - Active goals: Multi-RT experiments, savings targets, hypotheses
  - Key lessons: Curated permanent insights (not every RT summary)
  - Recent sessions: Rolling last 3 RT summaries

The Therapist writes to specific sections via update functions.
The runner generates the session bridge pre-RT.
Agents load the full structured memory into their prompt.

Usage:
    python engine/agent_memory.py bridge elena          # Generate session bridge
    python engine/agent_memory.py episodes elena        # Show episodes
    python engine/agent_memory.py migrate elena         # Migrate old MEMORY.md
    python engine/agent_memory.py migrate --all         # Migrate all agents
    python engine/agent_memory.py show elena            # Show full structured memory
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("agent_memory")

SUITE_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = SUITE_ROOT / "agents"

MAX_EPISODES = 12
MAX_RECENT_SESSIONS = 3
MAX_GOALS = 5
MAX_LESSONS = 8
MAX_DIARY_ENTRIES = 20
DIARY_RENDER_LIMIT = 5
DIARY_COMPRESS_THRESHOLD = 10  # Compress oldest 5 into an era summary every 10 entries
DIARY_SUMMARY_LENGTH = 200     # Chars for the summary field (Vela pattern)
DIARY_DEDUP_WINDOW = 2         # Skip if same topic written within last N entries


# ── Memory Loading ──────────────────────────────────────────────────────────

def load_memory(agent_name: str) -> dict:
    """Load structured memory from MEMORY.json. Falls back to empty structure."""
    path = AGENTS_DIR / agent_name / "MEMORY.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return _empty_memory(agent_name)


def save_memory(agent_name: str, memory: dict):
    """Persist structured memory."""
    path = AGENTS_DIR / agent_name / "MEMORY.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory, indent=2), encoding="utf-8")


def _empty_memory(agent_name: str) -> dict:
    return {
        "agent": agent_name,
        "session_bridge": "",
        "episodes": [],
        "active_goals": [],
        "key_lessons": [],
        "recent_sessions": [],
        "beliefs": [],
        "diary": [],
        "diary_eras": [],
    }


# ── Memory Rendering ────────────────────────────────────────────────────────

def render_memory(agent_name: str) -> str:
    """Render structured memory as text for the agent's prompt.

    This replaces the raw MEMORY.md dump. Written in first person so the
    agent experiences it as remembering, not reading a dossier.
    """
    mem = load_memory(agent_name)
    parts = ["# My Memory"]

    # Session bridge — always first, most recent continuity
    if mem.get("session_bridge"):
        parts.append(f"\n## Last Session\n{mem['session_bridge']}")

    # Active goals — what I'm working toward
    if mem.get("active_goals"):
        parts.append("\n## My Active Goals")
        for g in mem["active_goals"][:MAX_GOALS]:
            status = g.get("status", "active")
            progress = g.get("progress", "")
            rt_info = f" (RT {g.get('rt_started', '?')}+)" if g.get("rt_started") else ""
            parts.append(f"- [{status}]{rt_info} {g.get('goal', '')}")
            if progress:
                parts.append(f"  Progress: {progress}")

    # Episodes — vivid first-person memories of key moments
    if mem.get("episodes"):
        parts.append("\n## Key Moments I Remember")
        for ep in mem["episodes"][-MAX_EPISODES:]:
            parts.append(f"- [{ep.get('date', '?')}] {ep.get('memory', '')}")

    # Key lessons — permanent curated insights
    if mem.get("key_lessons"):
        parts.append("\n## Lessons I've Learned")
        for lesson in mem["key_lessons"][-MAX_LESSONS:]:
            parts.append(f"- {lesson.get('lesson', '')}")

    # Beliefs — what I currently think and why
    if mem.get("beliefs"):
        parts.append("\n## What I Currently Believe")
        for b in mem["beliefs"][:5]:
            confidence = b.get("confidence", "medium")
            parts.append(f"- [{confidence}] {b.get('belief', '')}")
            if b.get("evidence"):
                parts.append(f"  Evidence: {b['evidence']}")

    # Personal diary — my private reflections (bounded, most recent rendered)
    diary = mem.get("diary", [])
    eras = mem.get("diary_eras", [])
    if diary or eras:
        parts.append("\n## My Private Journal")
        # Era summaries first — compressed history
        for era in eras[-2:]:
            parts.append(f"- [era: {era.get('period', '?')}] {era.get('summary', '')}")
        # Recent entries — show summaries only to save context
        for entry in diary[-DIARY_RENDER_LIMIT:]:
            date = entry.get("date", "?")
            summary = entry.get("summary", entry.get("text", "")[:DIARY_SUMMARY_LENGTH])
            parts.append(f"- [{date}] {summary}")

    # Recent sessions — rolling summaries
    if mem.get("recent_sessions"):
        parts.append("\n## Recent Roundtables")
        for s in mem["recent_sessions"][-MAX_RECENT_SESSIONS:]:
            parts.append(f"- [{s.get('date', '?')}] RT {s.get('rt_id', '?')}: {s.get('summary', '')}")

    return "\n".join(parts)


# ── Session Bridge ──────────────────────────────────────────────────────────

def generate_session_bridge(agent_name: str) -> str:
    """Generate a 'last time you...' bridge from the most recent session transcript.

    Written in second person so it reads as a reminder, not a report.
    """
    sessions_dir = AGENTS_DIR / agent_name / "sessions"
    if not sessions_dir.exists():
        return ""

    # Find the most recent RT session (not therapist session)
    rt_sessions = sorted(sessions_dir.glob("20*.json"), reverse=True)
    therapist_sessions = sorted(sessions_dir.glob("therapist_*.json"), reverse=True)

    bridge_parts = []

    # From last RT session — what you argued
    if rt_sessions:
        try:
            data = json.loads(rt_sessions[0].read_text(encoding="utf-8"))
            messages = data.get("messages", [])
            my_msgs = [m for m in messages if m.get("agent") == agent_name]

            if my_msgs:
                # Take the core of their first and last contribution
                first_msg = my_msgs[0].get("message", "")[:200]
                last_msg = my_msgs[-1].get("message", "")[:200] if len(my_msgs) > 1 else ""

                rt_id = data.get("roundtable_id", "unknown")
                bridge_parts.append(
                    f"Last roundtable (RT {rt_id[:12]}): I made {len(my_msgs)} contributions."
                )
                if first_msg:
                    bridge_parts.append(f"I opened with: \"{first_msg}...\"")
                if last_msg and last_msg != first_msg:
                    bridge_parts.append(f"I closed with: \"{last_msg}...\"")
        except (json.JSONDecodeError, OSError, KeyError):
            pass

    # From last therapist session — what you committed to
    if therapist_sessions:
        try:
            data = json.loads(therapist_sessions[0].read_text(encoding="utf-8"))
            outcomes = data.get("outcomes", {})
            conv = data.get("conversation", [])

            commitments = []
            if outcomes.get("development_focus"):
                commitments.append(f"Focus: {outcomes['development_focus'][:120]}")
            for b in outcomes.get("add_behaviors", []):
                if b:
                    commitments.append(f"New rule: {b[:100]}")
            for req in outcomes.get("store_requests", []):
                if req:
                    commitments.append(f"Requested: {req[:80]}")

            if commitments:
                bridge_parts.append("After debrief, I committed to:")
                for c in commitments[:3]:
                    bridge_parts.append(f"  - {c}")

            # Extract the agent's own words from the debrief (their self-assessment)
            for msg in conv:
                if msg.get("role") == agent_name:
                    # Take a key sentence from their first response
                    sentences = [s.strip() for s in msg["message"].split(".")
                                 if len(s.strip()) > 30]
                    if sentences:
                        bridge_parts.append(f"I said: \"{sentences[0]}.\"")
                    break

        except (json.JSONDecodeError, OSError, KeyError):
            pass

    bridge = "\n".join(bridge_parts) if bridge_parts else ""

    # Save to memory
    mem = load_memory(agent_name)
    mem["session_bridge"] = bridge
    save_memory(agent_name, mem)

    return bridge


# ── Episode Management ──────────────────────────────────────────────────────

def add_episode(agent_name: str, memory_text: str, date: str = "",
                rt_id: str = "", episode_type: str = "general"):
    """Add a first-person episodic memory.

    episode_type: first, reversal, peak, failure, relationship, insight
    """
    mem = load_memory(agent_name)
    episode = {
        "memory": memory_text,
        "date": date or time.strftime("%Y-%m-%d"),
        "rt_id": rt_id,
        "type": episode_type,
        "added": time.time(),
    }
    mem.setdefault("episodes", []).append(episode)

    # Keep max episodes, but protect "first" type (formative memories)
    if len(mem["episodes"]) > MAX_EPISODES:
        # Sort: formative first, then by recency
        formative = [e for e in mem["episodes"] if e.get("type") == "first"]
        others = [e for e in mem["episodes"] if e.get("type") != "first"]
        others.sort(key=lambda e: e.get("added", 0))
        # Drop oldest non-formative
        while len(formative) + len(others) > MAX_EPISODES and others:
            others.pop(0)
        mem["episodes"] = formative + others

    save_memory(agent_name, mem)
    logger.info("Episode added for %s: %s", agent_name, memory_text[:60])


def extract_episodes_from_therapist(agent_name: str, conversation: list[dict],
                                     outcomes: dict, digest: dict):
    """Extract episodic memories from a therapist session.

    Looks for: score extremes, reversals, first-time events, key self-assessments.
    Writes in first person.
    """
    rt_id = digest.get("roundtable_id", "unknown")
    date = time.strftime("%Y-%m-%d")
    topic = digest.get("topic", "unknown topic")

    # Get this RT's score
    score = 0
    scoring_data = digest.get("scoring", [])
    if isinstance(scoring_data, dict):
        scoring_data = scoring_data.get("scores", [])
    for s in scoring_data:
        if isinstance(s, dict) and s.get("agent") == agent_name:
            score = s.get("total", 0)
            break

    # Load metrics for context
    metrics_path = AGENTS_DIR / agent_name / "metrics.json"
    avg_score = 0
    personal_best = 0
    assignments = 0
    if metrics_path.exists():
        try:
            m = json.loads(metrics_path.read_text(encoding="utf-8"))
            avg_score = m.get("avg_score", 0)
            personal_best = m.get("personal_best", 0)
            assignments = m.get("assignments", 0)
        except (json.JSONDecodeError, OSError):
            pass

    # Peak moment — new personal best or scored 10+
    if score >= 10 or (score > 0 and score >= personal_best):
        add_episode(
            agent_name,
            f"I scored {score}/12 on \"{topic}\" — {'a new personal best' if score >= personal_best else 'one of my strongest rounds'}. "
            f"It felt like everything clicked.",
            date=date, rt_id=rt_id, episode_type="peak",
        )

    # Failure — scored significantly below average
    elif score > 0 and score < avg_score - 2:
        add_episode(
            agent_name,
            f"Rough round on \"{topic}\" — scored {score}/12, well below my {avg_score:.0f} average. "
            f"I need to figure out what went wrong.",
            date=date, rt_id=rt_id, episode_type="failure",
        )

    # First-time events
    if assignments <= 1:
        add_episode(
            agent_name,
            f"My first roundtable. Topic was \"{topic}\". Scored {score}/12. "
            f"This is where it all started.",
            date=date, rt_id=rt_id, episode_type="first",
        )

    # Extract a key self-assessment from the agent's debrief words
    for msg in conversation:
        if msg.get("role") == agent_name:
            text = msg["message"]
            # Look for sentences with self-reflection markers
            for sentence in text.split("."):
                s = sentence.strip()
                if (len(s) > 40 and
                        any(kw in s.lower() for kw in
                            ["i realize", "i think", "i need to", "i was wrong",
                             "my mistake", "i learned", "next time", "i should",
                             "what worked", "i'm starting to"])):
                    add_episode(
                        agent_name,
                        f"After RT on \"{topic}\", I reflected: \"{s}.\"",
                        date=date, rt_id=rt_id, episode_type="insight",
                    )
                    break  # One insight per debrief
            break  # Only check first agent message


# ── Goal Management ─────────────────────────────────────────────────────────

def add_goal(agent_name: str, goal: str, rt_started: str = "",
             duration_rts: int = 3):
    """Add an active goal with a timeline."""
    mem = load_memory(agent_name)
    mem.setdefault("active_goals", []).append({
        "goal": goal,
        "status": "active",
        "rt_started": rt_started or time.strftime("%Y-%m-%d"),
        "duration_rts": duration_rts,
        "rts_elapsed": 0,
        "progress": "",
        "added": time.time(),
    })
    # Cap at MAX_GOALS — complete oldest if over
    if len(mem["active_goals"]) > MAX_GOALS:
        mem["active_goals"] = mem["active_goals"][-MAX_GOALS:]
    save_memory(agent_name, mem)
    logger.info("Goal added for %s: %s", agent_name, goal[:60])


def update_goal_progress(agent_name: str, goal_fragment: str, progress: str,
                          status: str = "active"):
    """Update progress on a goal by fuzzy matching the goal text."""
    mem = load_memory(agent_name)
    fragment_lower = goal_fragment.lower()
    for g in mem.get("active_goals", []):
        if fragment_lower in g.get("goal", "").lower():
            g["progress"] = progress
            g["status"] = status
            g["rts_elapsed"] = g.get("rts_elapsed", 0) + 1
            if status in ("completed", "confirmed", "abandoned"):
                # Move to a lesson if completed/confirmed
                if status in ("completed", "confirmed"):
                    mem.setdefault("key_lessons", []).append({
                        "lesson": f"Goal achieved: {g['goal'][:100]}. {progress}",
                        "date": time.strftime("%Y-%m-%d"),
                        "source": "goal",
                    })
            save_memory(agent_name, mem)
            logger.info("Goal updated for %s: %s -> %s", agent_name, goal_fragment[:40], status)
            return True
    return False


def age_goals(agent_name: str):
    """Increment rts_elapsed on all active goals. Called after each RT."""
    mem = load_memory(agent_name)
    for g in mem.get("active_goals", []):
        if g.get("status") == "active":
            g["rts_elapsed"] = g.get("rts_elapsed", 0) + 1
            # Flag goals past their duration
            if g["rts_elapsed"] >= g.get("duration_rts", 3):
                g["status"] = "evaluate"
    save_memory(agent_name, mem)


# ── Lesson Management ───────────────────────────────────────────────────────

def add_lesson(agent_name: str, lesson: str, source: str = "therapist"):
    """Add a permanent curated lesson."""
    mem = load_memory(agent_name)
    mem.setdefault("key_lessons", []).append({
        "lesson": lesson,
        "date": time.strftime("%Y-%m-%d"),
        "source": source,
    })
    # Keep max lessons — drop oldest
    if len(mem["key_lessons"]) > MAX_LESSONS:
        mem["key_lessons"] = mem["key_lessons"][-MAX_LESSONS:]
    save_memory(agent_name, mem)


# ── Belief Management ───────────────────────────────────────────────────────

def update_belief(agent_name: str, belief: str, confidence: str = "medium",
                   evidence: str = ""):
    """Add or update a belief. If a similar belief exists, update it."""
    mem = load_memory(agent_name)
    beliefs = mem.setdefault("beliefs", [])
    belief_lower = belief.lower()

    # Check for existing similar belief
    for b in beliefs:
        if any(word in b.get("belief", "").lower()
               for word in belief_lower.split()[:3] if len(word) > 4):
            b["belief"] = belief
            b["confidence"] = confidence
            b["evidence"] = evidence
            b["updated"] = time.strftime("%Y-%m-%d")
            save_memory(agent_name, mem)
            return

    # New belief
    beliefs.append({
        "belief": belief,
        "confidence": confidence,
        "evidence": evidence,
        "added": time.strftime("%Y-%m-%d"),
    })
    if len(beliefs) > 5:
        beliefs.pop(0)
    save_memory(agent_name, mem)


# ── Session Summary ─────────────────────────────────────────────────────────

def add_session_summary(agent_name: str, rt_id: str, summary: str, date: str = ""):
    """Add a rolling session summary (keeps last MAX_RECENT_SESSIONS)."""
    mem = load_memory(agent_name)
    mem.setdefault("recent_sessions", []).append({
        "rt_id": rt_id,
        "summary": summary,
        "date": date or time.strftime("%Y-%m-%d"),
    })
    mem["recent_sessions"] = mem["recent_sessions"][-MAX_RECENT_SESSIONS:]
    save_memory(agent_name, mem)


# ── Personal Diary ─────────────────────────────────────────────────────
# Borrowed patterns from Vela's SessionMemory:
#   - Turn summarization: full text stored, 200-char summary for rendering
#   - Topic extraction: keyword-based classification for dedup and retrieval
#   - Bounded window: only DIARY_RENDER_LIMIT entries shown in prompt
#   - Compression checkpoints: oldest entries compressed into era summaries
#   - Deduplication: skip if same topic written within DIARY_DEDUP_WINDOW

# Topic keywords — maps keywords to topic labels (like Vela's domain classification)
_TOPIC_KEYWORDS = {
    "score": "performance", "scored": "performance", "sparks": "economy",
    "budget": "economy", "tier": "economy", "upgrade": "economy",
    "skill": "skills", "bought": "skills", "purchased": "skills",
    "strategy": "strategy", "plan": "strategy", "focus": "strategy",
    "elena": "teammate", "marcus": "teammate", "clare": "teammate",
    "simon": "teammate", "naomi": "teammate", "judge": "teammate",
    "therapist": "coaching", "debrief": "coaching", "session": "coaching",
    "mistake": "reflection", "wrong": "reflection", "learned": "reflection",
    "frustrated": "emotion", "confident": "emotion", "worried": "emotion",
    "excited": "emotion", "proud": "emotion", "disappointed": "emotion",
    "challenge": "competition", "disagree": "competition", "debate": "competition",
    "novel": "ideas", "idea": "ideas", "propose": "ideas", "suggest": "ideas",
    "evidence": "method", "analysis": "method", "approach": "method",
}


def _extract_topics(text: str) -> list[str]:
    """Extract topic labels from diary text using keyword matching.

    Borrowed from Vela's topic classification — simple, fast, no LLM needed.
    """
    text_lower = text.lower()
    topics = set()
    for keyword, topic in _TOPIC_KEYWORDS.items():
        if keyword in text_lower:
            topics.add(topic)
    return sorted(topics) if topics else ["general"]


def _is_duplicate(diary: list[dict], topics: list[str]) -> bool:
    """Check if the same topic was written about within the dedup window.

    Borrowed from Vela's overlap detection — prevents redundant entries
    about the same subject within N consecutive entries.
    """
    if not diary:
        return False
    recent = diary[-DIARY_DEDUP_WINDOW:]
    for entry in recent:
        entry_topics = set(entry.get("topics", []))
        overlap = entry_topics & set(topics)
        # If >50% topic overlap with a recent entry, it's a duplicate
        if overlap and len(overlap) / max(len(topics), 1) > 0.5:
            return True
    return False


def _compress_old_entries(mem: dict):
    """Compress oldest diary entries into an era summary when threshold is hit.

    Borrowed from Vela's fact extraction pattern — distill full entries into
    a compact permanent summary. The era summary stays forever; the individual
    entries are dropped.

    Runs every DIARY_COMPRESS_THRESHOLD entries. Takes the oldest 5 entries,
    extracts key themes, and produces a single era summary.
    """
    diary = mem.get("diary", [])
    if len(diary) < DIARY_COMPRESS_THRESHOLD:
        return

    # Take the oldest entries to compress
    to_compress = diary[:5]
    remaining = diary[5:]

    # Build era summary from the compressed entries
    dates = [e.get("date", "?") for e in to_compress]
    period = f"{dates[0]} to {dates[-1]}" if dates else "?"

    # Collect all topics across entries
    all_topics = set()
    for entry in to_compress:
        all_topics.update(entry.get("topics", []))

    # Build compressed text from summaries (not full text)
    summaries = [e.get("summary", e.get("text", "")[:100]) for e in to_compress]
    compressed_text = " | ".join(s[:80] for s in summaries if s)

    era = {
        "period": period,
        "summary": compressed_text[:400],
        "topics": sorted(all_topics),
        "entry_count": len(to_compress),
        "compressed_at": time.strftime("%Y-%m-%d"),
    }

    mem.setdefault("diary_eras", []).append(era)
    mem["diary"] = remaining

    logger.info("Compressed %d diary entries into era: %s", len(to_compress), period)


def write_diary_entry(agent_name: str, text: str, rt_id: str = "",
                      date: str = "") -> dict:
    """Agent writes a personal diary entry — their own private reflection.

    The agent calls this to record thoughts, plans, frustrations, strategies.
    Full text is stored but only a 200-char summary renders in the prompt.
    Automatic dedup, compression, and rotation keep size bounded.

    Returns: {"written": bool, "reason": str}
    """
    mem = load_memory(agent_name)
    diary = mem.setdefault("diary", [])
    date = date or time.strftime("%Y-%m-%d")

    # Extract topics for dedup and retrieval
    topics = _extract_topics(text)

    # Dedup check — borrowed from Vela's overlap detection
    if _is_duplicate(diary, topics):
        logger.info("Diary dedup: %s already wrote about %s recently", agent_name, topics)
        return {"written": False, "reason": f"duplicate topic: {', '.join(topics)}"}

    # Build entry with full text + summary (Vela's turn summarization pattern)
    summary = text[:DIARY_SUMMARY_LENGTH].rstrip()
    if len(text) > DIARY_SUMMARY_LENGTH:
        # Try to break at sentence boundary
        last_period = summary.rfind(".")
        last_question = summary.rfind("?")
        last_break = max(last_period, last_question)
        if last_break > DIARY_SUMMARY_LENGTH // 2:
            summary = summary[:last_break + 1]
        else:
            summary = summary + "..."

    entry = {
        "text": text,
        "summary": summary,
        "topics": topics,
        "date": date,
        "rt_id": rt_id,
        "written_at": time.time(),
    }

    diary.append(entry)

    # Compression checkpoint — borrowed from Vela's fact extraction
    _compress_old_entries(mem)

    # Hard cap — drop oldest if over MAX_DIARY_ENTRIES
    if len(mem["diary"]) > MAX_DIARY_ENTRIES:
        mem["diary"] = mem["diary"][-MAX_DIARY_ENTRIES:]

    save_memory(agent_name, mem)
    logger.info("Diary entry for %s: %d chars, topics=%s", agent_name, len(text), topics)
    return {"written": True, "reason": "ok", "topics": topics}


def read_diary(agent_name: str, topic_filter: str = "",
               limit: int = DIARY_RENDER_LIMIT) -> list[dict]:
    """Read diary entries, optionally filtered by topic.

    For retrieval by the agent or therapist — returns full text, not just summaries.
    Topic filter uses Vela's keyword-to-topic matching.
    """
    mem = load_memory(agent_name)
    diary = mem.get("diary", [])

    if topic_filter:
        filter_topics = _extract_topics(topic_filter)
        diary = [e for e in diary
                 if set(e.get("topics", [])) & set(filter_topics)]

    return diary[-limit:]


def diary_stats(agent_name: str) -> dict:
    """Get diary statistics for the therapist's case notes."""
    mem = load_memory(agent_name)
    diary = mem.get("diary", [])
    eras = mem.get("diary_eras", [])

    # Topic frequency
    topic_counts: dict[str, int] = {}
    for entry in diary:
        for t in entry.get("topics", []):
            topic_counts[t] = topic_counts.get(t, 0) + 1

    return {
        "total_entries": len(diary),
        "total_eras": len(eras),
        "total_compressed": sum(e.get("entry_count", 0) for e in eras),
        "topic_frequency": dict(sorted(topic_counts.items(), key=lambda x: -x[1])),
        "latest_date": diary[-1].get("date", "?") if diary else None,
    }


# ── Migration ───────────────────────────────────────────────────────────────

def migrate_from_memory_md(agent_name: str):
    """Migrate existing MEMORY.md content into the structured memory system.

    Parses the old format and distributes content into appropriate sections.
    """
    memory_md_path = AGENTS_DIR / agent_name / "MEMORY.md"
    if not memory_md_path.exists():
        logger.info("No MEMORY.md to migrate for %s", agent_name)
        return

    content = memory_md_path.read_text(encoding="utf-8")
    mem = load_memory(agent_name)

    # Parse sections from old MEMORY.md
    current_section = ""
    for line in content.split("\n"):
        stripped = line.strip()

        if stripped.startswith("## "):
            current_section = stripped[3:].strip().lower()
            continue

        if not stripped or stripped.startswith("#"):
            continue

        # Route content to appropriate structured sections
        if current_section in ("experience", "recent roundtables"):
            # These become recent session summaries
            if stripped.startswith("- "):
                text = stripped[2:].strip()
                # Extract RT ID if present
                rt_id = ""
                if "RT-" in text:
                    rt_id = text.split("RT-")[1].split(":")[0].split(".")[0].split(" ")[0]
                mem.setdefault("recent_sessions", []).append({
                    "rt_id": rt_id,
                    "summary": text[:200],
                    "date": "",
                })

        elif current_section in ("strengths discovered", "strengths"):
            # These become lessons
            if stripped.startswith("- "):
                mem.setdefault("key_lessons", []).append({
                    "lesson": stripped[2:].strip(),
                    "date": "",
                    "source": "migration",
                })

        elif current_section in ("lessons learned", "lessons"):
            if stripped.startswith("- "):
                mem.setdefault("key_lessons", []).append({
                    "lesson": stripped[2:].strip(),
                    "date": "",
                    "source": "migration",
                })

        elif current_section.startswith("trait"):
            # Trait observations become episodes
            if stripped.startswith("- **") or len(stripped) > 50:
                mem.setdefault("episodes", []).append({
                    "memory": f"Early observation about me: {stripped[:200]}",
                    "date": "",
                    "rt_id": "",
                    "type": "insight",
                    "added": time.time(),
                })

        elif current_section.startswith("20"):
            # Dated entries — these are full session summaries from the Therapist
            # Convert to a session summary and extract any goals/lessons
            if len(stripped) > 30:
                # Check for focus/goal content
                if "focus:" in stripped.lower():
                    focus_start = stripped.lower().index("focus:")
                    focus_text = stripped[focus_start + 6:].strip()[:150]
                    mem.setdefault("active_goals", []).append({
                        "goal": focus_text,
                        "status": "active",
                        "rt_started": current_section[:10],
                        "duration_rts": 3,
                        "rts_elapsed": 0,
                        "progress": "",
                        "added": time.time(),
                    })

    # Trim to limits
    mem["recent_sessions"] = mem["recent_sessions"][-MAX_RECENT_SESSIONS:]
    mem["key_lessons"] = mem["key_lessons"][-MAX_LESSONS:]
    mem["episodes"] = mem["episodes"][-MAX_EPISODES:]
    mem["active_goals"] = mem["active_goals"][-MAX_GOALS:]

    save_memory(agent_name, mem)

    # Also regenerate the MEMORY.md as the rendered structured version
    rendered = render_memory(agent_name)
    memory_md_path.write_text(rendered, encoding="utf-8")

    logger.info("Migrated %s: %d episodes, %d lessons, %d goals, %d sessions",
                agent_name, len(mem.get("episodes", [])),
                len(mem.get("key_lessons", [])),
                len(mem.get("active_goals", [])),
                len(mem.get("recent_sessions", [])))


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import io
    import sys

    # Fix Windows cp1252 encoding for Unicode output (→, etc.)
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Agent Memory System")
    sub = parser.add_subparsers(dest="command")

    p_show = sub.add_parser("show", help="Show agent's rendered memory")
    p_show.add_argument("agent", help="Agent name")

    p_bridge = sub.add_parser("bridge", help="Generate session bridge")
    p_bridge.add_argument("agent", help="Agent name")

    p_episodes = sub.add_parser("episodes", help="Show episodes")
    p_episodes.add_argument("agent", help="Agent name")

    p_goals = sub.add_parser("goals", help="Show active goals")
    p_goals.add_argument("agent", help="Agent name")

    p_add_ep = sub.add_parser("add-episode", help="Add an episode")
    p_add_ep.add_argument("agent", help="Agent name")
    p_add_ep.add_argument("text", help="Episode text (first person)")
    p_add_ep.add_argument("--type", default="general", help="Episode type")

    p_add_goal = sub.add_parser("add-goal", help="Add a goal")
    p_add_goal.add_argument("agent", help="Agent name")
    p_add_goal.add_argument("text", help="Goal description")

    p_migrate = sub.add_parser("migrate", help="Migrate from old MEMORY.md")
    p_migrate.add_argument("agent", nargs="?", help="Agent name (or --all)")
    p_migrate.add_argument("--all", action="store_true", help="Migrate all agents")

    p_diary_write = sub.add_parser("diary-write", help="Write a diary entry")
    p_diary_write.add_argument("agent", help="Agent name")
    p_diary_write.add_argument("text", help="Diary entry text")
    p_diary_write.add_argument("--rt", default="", help="RT ID")

    p_diary_read = sub.add_parser("diary-read", help="Read diary entries")
    p_diary_read.add_argument("agent", help="Agent name")
    p_diary_read.add_argument("--topic", default="", help="Topic filter")
    p_diary_read.add_argument("--limit", type=int, default=5, help="Max entries")

    p_diary_stats = sub.add_parser("diary-stats", help="Diary statistics")
    p_diary_stats.add_argument("agent", help="Agent name")

    args = parser.parse_args()

    if args.command == "show":
        print(render_memory(args.agent))
    elif args.command == "bridge":
        bridge = generate_session_bridge(args.agent)
        print(bridge or "(no session data)")
    elif args.command == "episodes":
        mem = load_memory(args.agent)
        print(json.dumps(mem.get("episodes", []), indent=2))
    elif args.command == "goals":
        mem = load_memory(args.agent)
        print(json.dumps(mem.get("active_goals", []), indent=2))
    elif args.command == "add-episode":
        add_episode(args.agent, args.text, episode_type=args.type)
        print(json.dumps({"added": True}))
    elif args.command == "add-goal":
        add_goal(args.agent, args.text)
        print(json.dumps({"added": True}))
    elif args.command == "migrate":
        agents = ["elena", "marcus", "clare", "simon", "naomi"]
        if args.all:
            for a in agents:
                migrate_from_memory_md(a)
        elif args.agent:
            migrate_from_memory_md(args.agent)
        else:
            print("Specify agent name or --all")
    elif args.command == "diary-write":
        result = write_diary_entry(args.agent, args.text, rt_id=args.rt)
        print(json.dumps(result))
    elif args.command == "diary-read":
        entries = read_diary(args.agent, topic_filter=args.topic, limit=args.limit)
        for e in entries:
            print(f"[{e.get('date', '?')}] ({', '.join(e.get('topics', []))}) {e.get('text', '')}")
    elif args.command == "diary-stats":
        print(json.dumps(diary_stats(args.agent), indent=2))
    else:
        parser.print_help()
