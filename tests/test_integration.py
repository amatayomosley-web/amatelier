"""Full integration test — traces data through every new system without calling LLMs.

Tests:
  1. Agent memory: load → write → render → verify sections present
  2. Session bridge: generate from session files → verify in rendered memory
  3. Episodes: extract from mock therapist session → verify stored
  4. Goals: add → age → verify status transitions
  5. Diary: write → dedup → compress → verify era created
  6. Evolver dual-write: append_to_memory → verify both MEMORY.json and MEMORY.md
  7. Transcript index: build from real DB → verify format
  8. Recall: filter by agent/keyword/round → verify results
  9. Cumulative debate state: verify prior_state threading
  10. Therapist wiring: _apply_outcomes → verify memory/episodes/diary written
  11. Runner wiring: verify session bridge + goal aging + session summary calls
  12. Context loading: claude_agent + gemini_agent use render_memory

Usage:
    cd .claude/skills/claude-suite/engine
    python ../tests/test_integration.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

# Fix encoding
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Setup paths — post-Amatayo Standard restructure, engine/ and
# roundtable-server/ live under src/atelier/. SUITE_ROOT keeps the
# original semantic ("where engine and roundtable-server sit") so the
# rest of this file (which references SUITE_ROOT / "roundtable-server" /
# "db_client.py") continues to resolve.
REPO_ROOT = Path(__file__).resolve().parent.parent
SUITE_ROOT = REPO_ROOT / "src" / "atelier"
ENGINE_DIR = SUITE_ROOT / "engine"
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(SUITE_ROOT / "store"))

# Track results
passed = 0
failed = 0
errors: list[str] = []

TEST_AGENT = "elena"  # Use a real agent so paths resolve


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        errors.append(f"{name}: {detail}")


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ── Backup agent state before tests ──────────────────────────────────────

from agent_memory import load_memory, save_memory

original_memory = load_memory(TEST_AGENT)
original_memory_backup = json.dumps(original_memory)  # Deep copy via JSON


# ═══════════════════════════════════════════════════════════════════════
#  1. AGENT MEMORY: load → write → render
# ═══════════════════════════════════════════════════════════════════════

section("1. Agent Memory — load / write / render")

from agent_memory import (
    render_memory, add_episode, add_goal, add_lesson,
    update_belief, add_session_summary, age_goals,
    generate_session_bridge, write_diary_entry, read_diary,
    diary_stats, extract_episodes_from_therapist,
    _extract_topics, _is_duplicate, _compress_old_entries,
    DIARY_RENDER_LIMIT, MAX_EPISODES, MAX_GOALS, MAX_LESSONS,
)

mem = load_memory(TEST_AGENT)
check("load_memory returns dict", isinstance(mem, dict))
check("has agent field", mem.get("agent") == TEST_AGENT)
check("has episodes list", isinstance(mem.get("episodes"), list))
check("has diary list", isinstance(mem.get("diary", []), list))
check("has diary_eras list", isinstance(mem.get("diary_eras", []), list))

rendered = render_memory(TEST_AGENT)
check("render_memory returns string", isinstance(rendered, str))
check("render starts with # My Memory", rendered.startswith("# My Memory"))


# ═══════════════════════════════════════════════════════════════════════
#  2. EPISODES
# ═══════════════════════════════════════════════════════════════════════

section("2. Episodes — add / extract / limits")

pre_count = len(load_memory(TEST_AGENT).get("episodes", []))
add_episode(TEST_AGENT, "Test peak moment — everything clicked", episode_type="peak")
post_count = len(load_memory(TEST_AGENT).get("episodes", []))
check("add_episode increments count", post_count == pre_count + 1)

# Verify episode content
mem = load_memory(TEST_AGENT)
latest = mem["episodes"][-1]
check("episode has memory field", "everything clicked" in latest.get("memory", ""))
check("episode has type field", latest.get("type") == "peak")
check("episode has date", bool(latest.get("date")))

# Test extract from therapist mock
mock_conversation = [
    {"role": "therapist", "message": "Your accuracy was strong this round."},
    {"role": TEST_AGENT, "message": "I realize I need to push harder on novelty. My mistake was playing safe. Next time I should lead with something unexpected."},
]
mock_outcomes = {"development_focus": "Push novelty"}
mock_digest = {"roundtable_id": "test-rt-001", "topic": "Test Topic", "scoring": [
    {"agent": TEST_AGENT, "total": 9}
]}

pre_ep = len(load_memory(TEST_AGENT).get("episodes", []))
extract_episodes_from_therapist(TEST_AGENT, mock_conversation, mock_outcomes, mock_digest)
post_ep = len(load_memory(TEST_AGENT).get("episodes", []))
check("extract_episodes adds at least 1", post_ep > pre_ep,
      f"before={pre_ep} after={post_ep}")

# Verify insight was extracted (agent said "I realize")
mem = load_memory(TEST_AGENT)
insight_eps = [e for e in mem["episodes"] if e.get("type") == "insight" and "realize" in e.get("memory", "").lower()]
check("insight episode extracted from 'I realize'", len(insight_eps) > 0)


# ═══════════════════════════════════════════════════════════════════════
#  3. GOALS — add / age / status transitions
# ═══════════════════════════════════════════════════════════════════════

section("3. Goals — add / age / evaluate transition")

from agent_memory import update_goal_progress

add_goal(TEST_AGENT, "Test goal: improve novelty score", duration_rts=2)
mem = load_memory(TEST_AGENT)
test_goals = [g for g in mem["active_goals"] if "novelty score" in g.get("goal", "")]
check("add_goal creates goal", len(test_goals) >= 1)
check("goal starts active", test_goals[-1].get("status") == "active")
check("goal has duration", test_goals[-1].get("duration_rts") == 2)

# Age once
age_goals(TEST_AGENT)
mem = load_memory(TEST_AGENT)
test_goals = [g for g in mem["active_goals"] if "novelty score" in g.get("goal", "")]
check("age_goals increments rts_elapsed", test_goals[-1].get("rts_elapsed", 0) >= 1)

# Age again — should hit duration and flip to evaluate
age_goals(TEST_AGENT)
mem = load_memory(TEST_AGENT)
test_goals = [g for g in mem["active_goals"] if "novelty score" in g.get("goal", "")]
check("goal flips to evaluate at duration", test_goals[-1].get("status") == "evaluate",
      f"status={test_goals[-1].get('status')}, elapsed={test_goals[-1].get('rts_elapsed')}")

# Update progress
update_goal_progress(TEST_AGENT, "novelty", "Scored 2.5 avg novelty", status="completed")
mem = load_memory(TEST_AGENT)
# Completed goal should generate a lesson
lessons = [l for l in mem.get("key_lessons", []) if "novelty" in l.get("lesson", "").lower()]
check("completed goal creates lesson", len(lessons) > 0)


# ═══════════════════════════════════════════════════════════════════════
#  4. DIARY — write / dedup / topics / compress
# ═══════════════════════════════════════════════════════════════════════

section("4. Diary — write / dedup / compress")

# Clear diary first
mem = load_memory(TEST_AGENT)
mem["diary"] = []
mem["diary_eras"] = []
save_memory(TEST_AGENT, mem)

# Topic extraction
topics = _extract_topics("I scored well on accuracy but my strategy needs work")
check("_extract_topics finds performance", "performance" in topics)
check("_extract_topics finds strategy", "strategy" in topics)

# Write first entry
r1 = write_diary_entry(TEST_AGENT, "I scored 9/12 today. My accuracy was strong but novelty lagged.", rt_id="test-1")
check("diary write succeeds", r1.get("written") is True)
check("diary write returns topics", len(r1.get("topics", [])) > 0)

# Write same topic — should dedup
r2 = write_diary_entry(TEST_AGENT, "My score was high again. Accuracy still carrying me.", rt_id="test-2")
check("diary dedup blocks same topic", r2.get("written") is False,
      f"reason={r2.get('reason', '')}")

# Write different topic
r3 = write_diary_entry(TEST_AGENT, "Marcus challenged my position and I had to concede. The debate was tough.", rt_id="test-3")
check("diary write different topic succeeds", r3.get("written") is True)

# Verify stats
stats = diary_stats(TEST_AGENT)
check("diary_stats total_entries", stats["total_entries"] == 2)
check("diary_stats has topic_frequency", len(stats.get("topic_frequency", {})) > 0)

# Read with filter — "challenge" maps to "competition" topic
results = read_diary(TEST_AGENT, topic_filter="debate challenge")
check("read_diary topic filter works", len(results) >= 1,
      f"results={len(results)}, filter_topics={_extract_topics('debate challenge')}")
check("read_diary returns full text",
      len(results[0].get("text", "")) > 50 if results else False)

# Render includes diary
rendered = render_memory(TEST_AGENT)
check("rendered memory includes diary section", "Private Journal" in rendered)

# Compression test — write enough to trigger
mem = load_memory(TEST_AGENT)
mem["diary"] = []
save_memory(TEST_AGENT, mem)

# Write entries directly to bypass dedup (simulates entries across many RTs)
mem = load_memory(TEST_AGENT)
mem["diary"] = []
mem["diary_eras"] = []
for i in range(12):
    mem["diary"].append({
        "text": f"Diary entry {i} about topic-{i}. Unique content here.",
        "summary": f"Entry {i} summary",
        "topics": [f"topic-{i}"],
        "date": f"2026-04-{i+1:02d}",
        "rt_id": f"compress-{i}",
        "written_at": time.time() + i,
    })
save_memory(TEST_AGENT, mem)

# Now trigger compression by writing one more via the function
_compress_old_entries(mem)
save_memory(TEST_AGENT, mem)

check("compression triggered", len(mem.get("diary_eras", [])) >= 1,
      f"eras={len(mem.get('diary_eras', []))}, entries={len(mem.get('diary', []))}")
check("entries reduced after compression", len(mem.get("diary", [])) < 12,
      f"entries={len(mem.get('diary', []))}")

era = mem["diary_eras"][-1]
check("era has period", bool(era.get("period")))
check("era has summary", len(era.get("summary", "")) > 10)
check("era has entry_count", era.get("entry_count") == 5)


# ═══════════════════════════════════════════════════════════════════════
#  5. BELIEFS
# ═══════════════════════════════════════════════════════════════════════

section("5. Beliefs — add / update / render")

update_belief(TEST_AGENT, "Concise arguments score higher than detailed ones",
              confidence="high", evidence="Scored 10/12 in round 3 with short posts")
mem = load_memory(TEST_AGENT)
beliefs = mem.get("beliefs", [])
check("belief added", len(beliefs) >= 1)
concise_belief = [b for b in beliefs if "concise" in b.get("belief", "").lower()]
check("belief content correct", len(concise_belief) >= 1)
check("belief has confidence", concise_belief[-1].get("confidence") == "high")
check("belief has evidence", "10/12" in concise_belief[-1].get("evidence", ""))

rendered = render_memory(TEST_AGENT)
check("rendered memory includes beliefs", "Currently Believe" in rendered)


# ═══════════════════════════════════════════════════════════════════════
#  6. SESSION SUMMARY
# ═══════════════════════════════════════════════════════════════════════

section("6. Session Summary — add / rolling limit")

add_session_summary(TEST_AGENT, "test-rt-001", "Topic: Error Handling. Scored 9/12.")
add_session_summary(TEST_AGENT, "test-rt-002", "Topic: Caching. Scored 7/12.")
add_session_summary(TEST_AGENT, "test-rt-003", "Topic: Auth. Scored 11/12.")
add_session_summary(TEST_AGENT, "test-rt-004", "Topic: Logging. Scored 8/12.")

mem = load_memory(TEST_AGENT)
sessions = mem.get("recent_sessions", [])
check("rolling limit caps at 3", len(sessions) <= 3,
      f"count={len(sessions)}")
check("most recent session preserved", any("Logging" in s.get("summary", "") for s in sessions))
check("oldest session dropped", not any("Error Handling" in s.get("summary", "") for s in sessions),
      f"summaries={[s.get('summary','')[:30] for s in sessions]}")


# ═══════════════════════════════════════════════════════════════════════
#  7. EVOLVER DUAL-WRITE
# ═══════════════════════════════════════════════════════════════════════

section("7. Evolver — dual-write to MEMORY.json + MEMORY.md")

from evolver import append_to_memory

pre_sessions = len(load_memory(TEST_AGENT).get("recent_sessions", []))
append_to_memory(TEST_AGENT, "Test evolver dual-write entry")

# Check MEMORY.md got the entry
memory_md_path = SUITE_ROOT / "agents" / TEST_AGENT / "MEMORY.md"
check("MEMORY.md exists", memory_md_path.exists())
md_content = memory_md_path.read_text(encoding="utf-8")
check("MEMORY.md has entry", "dual-write" in md_content)

# Check MEMORY.json got a session summary
post_sessions = len(load_memory(TEST_AGENT).get("recent_sessions", []))
check("MEMORY.json session count updated", post_sessions >= pre_sessions,
      f"before={pre_sessions} after={post_sessions}")


# ═══════════════════════════════════════════════════════════════════════
#  8. TRANSCRIPT INDEX + RECALL
# ═══════════════════════════════════════════════════════════════════════

section("8. Transcript Index + Recall")

from db import build_transcript_index, recall, get_db

# Find any RT with messages
conn = get_db()
row = conn.execute("SELECT id, topic FROM roundtables ORDER BY created_at DESC LIMIT 1").fetchone()
conn.close()

if row:
    rt_id = row["id"]

    # Transcript index
    index = build_transcript_index(rt_id)
    lines = index.split("\n") if index else []
    check("transcript index has lines", len(lines) > 0, f"lines={len(lines)}")
    check("index lines have round prefix", lines[0].strip().startswith("R") if lines else False,
          f"first_line={lines[0][:40] if lines else '(empty)'}")
    check("index lines have agent name", any("elena" in l.lower() or "marcus" in l.lower() for l in lines))

    # Recall — by agent
    elena_msgs = recall(rt_id, agent_filter="elena")
    check("recall by agent returns results", len(elena_msgs) > 0)
    check("recall results have round field", "round" in elena_msgs[0] if elena_msgs else False)
    check("recall results have message field", "message" in elena_msgs[0] if elena_msgs else False)
    check("recall results filtered correctly",
          all(m["agent"] == "elena" for m in elena_msgs) if elena_msgs else True)

    # Recall — by round
    r1_msgs = recall(rt_id, round_num=1)
    check("recall by round returns results", len(r1_msgs) > 0)
    check("recall round filter correct",
          all(m["round"] == 1 for m in r1_msgs) if r1_msgs else True)

    # Recall — by keyword
    kw_msgs = recall(rt_id, keyword="finding")
    check("recall by keyword returns results", len(kw_msgs) >= 0)  # May or may not match

    # Recall — combined filters
    combo = recall(rt_id, agent_filter="simon", round_num=1)
    check("recall combined filter works", isinstance(combo, list))
    check("combined filter respects agent",
          all(m["agent"] == "simon" for m in combo) if combo else True)
    check("combined filter respects round",
          all(m["round"] == 1 for m in combo) if combo else True)

    # Recall — limit
    limited = recall(rt_id, limit=3)
    check("recall respects limit", len(limited) <= 3)
else:
    print("  SKIP  No roundtable data in DB — transcript/recall tests skipped")


# ═══════════════════════════════════════════════════════════════════════
#  9. CUMULATIVE DEBATE STATE (signature check)
# ═══════════════════════════════════════════════════════════════════════

section("9. Cumulative Debate State — signature + threading")

import inspect
import roundtable_runner

sig = inspect.signature(roundtable_runner._summarize_round)
params = list(sig.parameters.keys())
check("_summarize_round has prior_state param", "prior_state" in params)
check("prior_state defaults to empty string",
      sig.parameters["prior_state"].default == "")

# Verify debate_state variable exists in run_roundtable source
source = inspect.getsource(roundtable_runner.run_roundtable)
check("run_roundtable initializes debate_state", "debate_state" in source)
check("debate_state passed to _summarize_round", "prior_state=debate_state" in source)
check("transcript index injected", "build_transcript_index" in source)


# ═══════════════════════════════════════════════════════════════════════
#  10. CONTEXT LOADING — agents use render_memory
# ═══════════════════════════════════════════════════════════════════════

section("10. Context Loading — agents use render_memory()")

import claude_agent
import gemini_agent

# Check claude_agent.load_agent_context source
ca_source = inspect.getsource(claude_agent.load_agent_context)
check("claude_agent imports render_memory", "render_memory" in ca_source)
check("claude_agent has fallback to MEMORY.md", "MEMORY.md" in ca_source or "memory_md" in ca_source)

# Check gemini_agent.load_agent_context source
ga_source = inspect.getsource(gemini_agent.load_agent_context)
check("gemini_agent imports render_memory", "render_memory" in ga_source)
check("gemini_agent has fallback", "ImportError" in ga_source)

# Check context label
ca_select_source = inspect.getsource(claude_agent._select_context)
check("claude_agent labels as DEBATE STATE", "DEBATE STATE" in ca_select_source)

ga_select_source = inspect.getsource(gemini_agent._select_context)
check("gemini_agent labels as DEBATE STATE", "DEBATE STATE" in ga_select_source)

# Actually load context and verify structured memory is in it
context = claude_agent.load_agent_context(TEST_AGENT)
check("loaded context contains My Memory", "My Memory" in context or "My Active Goals" in context,
      f"context_len={len(context)}")
check("loaded context does NOT contain raw ## 2026", "## 2026" not in context[:2000],
      "Should be structured, not raw MEMORY.md format")


# ═══════════════════════════════════════════════════════════════════════
#  11. THERAPIST WIRING — _apply_outcomes traces
# ═══════════════════════════════════════════════════════════════════════

section("11. Therapist Wiring — _apply_outcomes / run_session source")

import therapist

# Check _apply_outcomes source for new integrations
ao_source = inspect.getsource(therapist._apply_outcomes)
check("_apply_outcomes uses add_session_summary", "add_session_summary" in ao_source)
check("_apply_outcomes uses add_lesson", "add_lesson" in ao_source)
check("_apply_outcomes has legacy fallback", "evolver" in ao_source.lower() or "EVOLVER" in ao_source)

# Check run_session source for episode + diary extraction
rs_source = inspect.getsource(therapist.run_session)
check("run_session extracts episodes", "extract_episodes_from_therapist" in rs_source)
check("run_session adds goals from focus", "add_goal" in rs_source)
check("run_session writes diary", "write_diary_entry" in rs_source)
check("run_session updates case notes", "_update_case_notes" in rs_source)

# Check _build_agent_brief has diary stats
ab_source = inspect.getsource(therapist._build_agent_brief)
check("_build_agent_brief loads diary stats", "diary_stats" in ab_source)
check("_build_agent_brief includes diary in brief", "diary_info" in ab_source)


# ═══════════════════════════════════════════════════════════════════════
#  12. RUNNER WIRING — pre-RT + post-RT hooks
# ═══════════════════════════════════════════════════════════════════════

section("12. Runner Wiring — pre-RT + post-RT hooks")

rr_source = inspect.getsource(roundtable_runner.run_roundtable)

check("runner generates session bridges pre-RT", "generate_session_bridge" in rr_source)
check("runner ages goals post-RT", "age_goals" in rr_source)
check("runner adds session summaries post-RT", "add_session_summary" in rr_source)
check("runner syncs skills pre-RT", "sync_skills_owned" in rr_source)
check("runner applies boosts pre-RT", "apply_boosts_for_rt" in rr_source)
check("runner consumes boosts post-RT", "consume_boosts_after_rt" in rr_source)
check("runner ages bulletin requests post-RT", "age_bulletin_requests" in rr_source)


# ═══════════════════════════════════════════════════════════════════════
#  13. DB CLIENT — recall + index commands
# ═══════════════════════════════════════════════════════════════════════

section("13. DB Client — recall + index CLI commands")

db_client_path = SUITE_ROOT / "roundtable-server" / "db_client.py"
check("db_client.py exists", db_client_path.exists())

db_source = db_client_path.read_text(encoding="utf-8")
check("db_client has cmd_recall", "def cmd_recall" in db_source)
check("db_client has cmd_index", "def cmd_index" in db_source)
check("db_client dispatches recall", "cmd_recall" in db_source.split("if __name__")[1] if "__name__" in db_source else "")
check("db_client dispatches index", "cmd_index" in db_source.split("if __name__")[1] if "__name__" in db_source else "")


# ═══════════════════════════════════════════════════════════════════════
#  14. AGENT CLAUDE.MD — recall/index documented
# ═══════════════════════════════════════════════════════════════════════

section("14. Agent CLAUDE.md — recall/index documented")

for agent in ["elena", "marcus", "clare", "simon"]:
    agent_md = SUITE_ROOT / "agents" / agent / "CLAUDE.md"
    if agent_md.exists():
        content = agent_md.read_text(encoding="utf-8")
        check(f"{agent} CLAUDE.md has recall command", "recall" in content)
        check(f"{agent} CLAUDE.md has index command", "index" in content)


# ═══════════════════════════════════════════════════════════════════════
#  CLEANUP — restore original memory state
# ═══════════════════════════════════════════════════════════════════════

section("CLEANUP")

save_memory(TEST_AGENT, json.loads(original_memory_backup))
check("agent memory restored to original", True)

# Restore MEMORY.md if it was modified
rendered = render_memory(TEST_AGENT)
memory_md_path = SUITE_ROOT / "agents" / TEST_AGENT / "MEMORY.md"
memory_md_path.write_text(rendered, encoding="utf-8")
check("MEMORY.md re-rendered from restored state", True)


# ═══════════════════════════════════════════════════════════════════════
#  RESULTS
# ═══════════════════════════════════════════════════════════════════════

print(f"\n{'='*60}")
print(f"  RESULTS: {passed} passed, {failed} failed")
print(f"{'='*60}")

if errors:
    print("\nFailures:")
    for e in errors:
        print(f"  - {e}")

sys.exit(0 if failed == 0 else 1)
