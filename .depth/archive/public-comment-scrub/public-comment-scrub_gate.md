TASK: public-comment-scrub
SCOPE: routine
FILES: src/amatelier/engine/claude_agent.py
REPLACES: `see claude-suite RT-4 post-mortem` — a code comment in claude_agent.py that pointed readers of this public repository at a document outside it; the comment already explains the hang in full, so the pointer is dropped
MIGRATION: none — comment only
CALLERS: src/amatelier/engine/claude_agent.py -> call_claude calls _force_kill_tree (unchanged)
DOC_GROUNDING: none — no governing doc
USER_PATH: src/amatelier/engine/claude_agent.py call_claude -> claude_agent._force_kill_tree
RED_STATE: src/amatelier/engine/claude_agent.py `_force_kill_tree()` is introduced by a comment that cites a post-mortem no reader of this repository can open
RED_TYPE: INFRASTRUCTURE
GREEN_CONDITION: grep of src/ for "claude-suite" returns no match, py_compile of claude_agent.py succeeds, and `make test` passes
OMISSIONS: none — src/amatelier/engine/claude_agent.py is the only file with the reference (git diff main..HEAD scan)
CASE_TRACE:
- case_id: green; finding: the reference is gone and nothing else changed; trace_run: grep -rn claude-suite src/ and python -m pytest; trace_output: src/amatelier/engine/claude_agent.py (no match; 61 passed); reproducibility: confirmed 1 of 1 runs
PREMISE_CHECK: No documented premise.
CORRECTION (same day, after commit 87ef58a): the GREEN_CONDITION's first clause and the green CASE_TRACE were wrong. A search of src/ for "claude-suite" still matches: the name is also the product's own skill folder (.claude/skills/claude-suite) in the persona seeds, BRIEFING_TEMPLATE.md and two engine comments (roundtable_runner.py, steward_dispatch.py). Those are public install paths and were never in scope. The only pointer to a document outside this repository was the removed comment, which is what the commit changed; py_compile and the 61-test suite did pass. The check tool does not run a gate's searches, so the false clause passed it.
