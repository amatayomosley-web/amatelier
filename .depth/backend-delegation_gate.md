TASK: delegate remaining subprocess claude calls to llm_backend
SCOPE: non-trivial
FILES: src/amatelier/engine/classify_concepts.py, src/amatelier/engine/backfill_distill.py, src/amatelier/engine/roundtable_runner.py, src/amatelier/engine/therapist.py, src/amatelier/engine/steward_dispatch.py
REPLACES: 6 direct subprocess.run(["claude", ...]) call sites that hardcode the Claude CLI — broken for users without `claude` on PATH even when ANTHROPIC_API_KEY is set
MIGRATION: none — each site keeps its existing subprocess call as the claude-code-mode fallback; only adds a backend-first check for open-mode users
CALLERS:
- classify_concepts._call_sonnet_classifier() — batch concept classification
- backfill_distill._distill_skills_sonnet() — retroactive skill extraction from old digests
- roundtable_runner._summarize_round_haiku() — per-round summaries via haiku
- roundtable_runner._distill_skills() — post-RT skill extraction via sonnet (called from run_roundtable)
- therapist._call_llm(prompt, model) — shared helper for _call_therapist, _call_gemini (gemini via its own path)
- steward_dispatch.run_steward_subagent() — tool-using research agent (cannot delegate — requires agent spawning)
USER_PATH: amatelier roundtable → roundtable_runner.run_roundtable() → [Round N] → _summarize_round_haiku() | → [post-RT] _distill_skills() | → classify_concepts() | → therapist() | → steward tagged requests → each site calls backend.complete() when backend.name != "claude-code", else falls through to existing subprocess.run(["claude", ...])
RED_STATE: 6 sites in engine/ directly call subprocess.run(["claude", "-p", "--model", ...]). User in anthropic-sdk or openai-compat mode hits FileNotFoundError('claude') at every site after Judge scoring succeeds (since Judge is the only site already delegating).
RED_TYPE: USER-OBSERVABLE
GREEN_CONDITION:
- When AMATELIER_MODE=anthropic-sdk (or auto-detected via ANTHROPIC_API_KEY with no claude binary): all 5 simple sites (classify_concepts, backfill_distill, 2 roundtable_runner sites, therapist) succeed via Anthropic SDK. Steward returns a degradation message explaining claude-code requirement.
- When claude-code mode: all sites continue using their existing subprocess.run() path with zero observable difference (same flags, same timeouts, same error handling).
- pytest tests/test_smoke.py passes (13/13)
- pytest tests/test_db_integration.py passes (11/11)
- ruff check src/ passes on the edited files
OMISSIONS:
- steward_dispatch in non-claude-code mode returns {"status": "unavailable", "result": "Steward requires claude-code mode..."} instead of spawning a tool-using agent. Proper tool-use delegation (Anthropic SDK messages API with tools param) is out of scope — multi-hour refactor.
- No new tests added; existing smoke + integration tests cover the non-delegation path. Live verification of open-mode requires ANTHROPIC_API_KEY in CI, which is a separate secrets/keys task.
- gemini_client and naomi (Naomi worker) unchanged — already use their own google-genai path
- engine/claude_agent.py line 264 — NOT in scope (this is the legacy shim; newer sites should use llm_backend.call_claude instead, but claude_agent.py still works for back-compat and is out of scope)
