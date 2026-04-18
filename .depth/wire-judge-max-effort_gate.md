TASK: wire judge max-effort via extended thinking
SCOPE: non-trivial
FILES: src/amatelier/llm_backend.py, src/amatelier/engine/judge_scorer.py
REPLACES: AnthropicSDKBackend.complete() at llm_backend.py:207 currently ignores thinking; _call_sonnet() at judge_scorer.py:144 passes max_tokens=8000 with no thinking budget; config.json has "effort": "max" under judge but code ignores it
MIGRATION: none — new optional `effort` param on LLMBackend.complete() defaults to None, preserves all existing call sites
CALLERS: judge_scorer._call_sonnet() will pass effort=<config.judge.effort> to backend.complete(). All other callers (call_claude shim at llm_backend.py:427, other engine sites) continue passing no effort and get identical behavior to today.
USER_PATH: amatelier roundtable → engine/roundtable_runner.py triggers scoring phase → engine/judge_scorer.py:score_contributions() → _call_sonnet(prompt) → reads config.judge.effort via _get_judge_effort() → backend.complete(effort="max") → AnthropicSDKBackend.complete() adds thinking={"type":"enabled","budget_tokens":16000} to client.messages.create() → Anthropic API returns with extended reasoning → higher-quality scoring
RED_STATE: llm_backend.py:219 `client.messages.create(model=, max_tokens=, system=, messages=, timeout=)` — no thinking kwarg. judge_scorer.py:156-159 `backend.complete(system="", prompt=prompt, model="sonnet", max_tokens=8000, timeout=360)` — no effort param exists. config.json line 37 `"effort": "max"` reads but never flows to API call.
RED_TYPE: INFRASTRUCTURE
GREEN_CONDITION: When config.judge.effort == "max" AND backend.name == "anthropic-sdk", the Anthropic messages.create() call receives thinking={"type": "enabled", "budget_tokens": 16000} and max_tokens is bumped to ≥20000. Other backends (claude-code, openai-compat) accept the effort kwarg without erroring and ignore it (log debug). judge_scorer continues to work when config has no effort field (effort=None, no thinking block).
OMISSIONS:
- OpenAICompatBackend.complete() at llm_backend.py:284 has no extended-thinking equivalent; OpenRouter/OpenAI users ignore effort (platform-level limitation)
- Only judge reads effort from config; agent LLM calls at engine/roundtable_runner.py do not propagate effort (out of scope)
- budget_tokens is hardcoded to 16000 for effort="max"; not exposed as config.judge.budget_tokens (follow-up)
- No new tests added; tests/test_smoke.py already covers backend.complete() without effort and will continue to pass
