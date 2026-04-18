TASK: implement Steward tool use in anthropic-sdk mode
SCOPE: non-trivial
FILES: src/amatelier/engine/steward_tools.py (new), src/amatelier/llm_backend.py, src/amatelier/engine/steward_dispatch.py
REPLACES: steward_dispatch.py returns {"status": "unavailable"} in open mode — degrades Steward empirical grounding. Implement actual Anthropic SDK tool-use loop (messages API with tools= param) backed by local read_file/grep/glob functions sandboxed to WORKSPACE_ROOT.
MIGRATION: none — claude-code mode path unchanged; anthropic-sdk now succeeds with real lookups instead of returning degradation message; openai-compat still degrades (tool schemas differ across OAI-compat providers, out of scope)
CALLERS:
- steward_dispatch.spawn_steward_subagent() at line ~253 — called from roundtable_runner when agents emit [[request: ...]] tags
- AnthropicSDKBackend.complete_with_tools() (new method) — called only from steward_dispatch, not wired into LLMBackend Protocol (avoids forcing all backends to implement)
- steward_tools.dispatch_tool(name, input) — internal router called by the tool-use loop
USER_PATH: amatelier roundtable (ANTHROPIC_API_KEY set, no claude CLI) → worker emits "[[request: show schema of messages table]]" → runner detects request → steward_dispatch.spawn_steward_subagent() → backend.name == "anthropic-sdk" → call complete_with_tools(system=STEWARD_SYSTEM_PROMPT, user=request, tools=STEWARD_TOOL_SPECS) → Anthropic returns tool_use block for grep/read_file → steward_tools.dispatch_tool() executes locally with path validation → result appended as tool_result → loop until model returns text → return {"status": "success", "result": text} to runner
RED_STATE: steward_dispatch.py:291-310 returns {"status": "unavailable"} when backend.name != "claude-code". In anthropic-sdk mode, [[request]] tags produce degradation messages instead of real data.
RED_TYPE: USER-OBSERVABLE
GREEN_CONDITION:
- steward_tools.py exports STEWARD_TOOL_SPECS (3 tools: read_file, grep, glob) and dispatch_tool(name, input) -> str
- steward_tools._safe_resolve() rejects path-traversal attempts (absolute paths outside WORKSPACE_ROOT, ../../etc)
- AnthropicSDKBackend has a new method complete_with_tools(system, user, tools, max_iterations=10) that loops tool_use → tool_result until final text
- steward_dispatch in anthropic-sdk mode returns real data, same structure as claude-code: {"status": "success", "result": str, "elapsed_s": float}
- Existing claude-code path unchanged (byte-identical flags + subprocess call)
- openai-compat continues to return {"status": "unavailable"} — documented in OMISSIONS
- pytest tests/test_smoke.py passes (13/13), pytest tests/test_db_integration.py passes (11/11)
- ruff clean on new files
OMISSIONS:
- OpenAI-compat tool use NOT implemented. OpenAI and OpenRouter support tools but schemas differ (OpenAI functions vs Anthropic tools). A cross-provider abstraction would double the code for marginal benefit since OAI-compat Steward usage is niche. Users who need Steward in OAI-compat must set AMATELIER_MODE=anthropic-sdk with ANTHROPIC_API_KEY.
- Tool sandbox is path-based only — no syscall sandboxing. Steward can read any file under WORKSPACE_ROOT including .env, secrets, etc. Same security posture as claude-code mode (Read tool with --dangerously-skip-permissions).
- No timeout per tool call (only overall complete_with_tools timeout). A single grep on a huge directory could block.
- No token accounting across tool-use iterations — follows existing judge_scorer pattern.
- No new tests; existing smoke + integration tests cover non-steward paths. Live verification requires ANTHROPIC_API_KEY which is a separate concern.
