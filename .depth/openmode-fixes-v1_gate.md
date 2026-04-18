TASK: apply Open-mode RT fixes (text accumulation, exception guard, response_format)
SCOPE: non-trivial
FILES: src/amatelier/llm_backend.py, src/amatelier/engine/judge_scorer.py, src/amatelier/engine/classify_concepts.py, src/amatelier/engine/backfill_distill.py, src/amatelier/engine/roundtable_runner.py
REPLACES:
  1. AnthropicSDKBackend.complete_with_tools at llm_backend.py:319-321 `final_text = "".join(text_chunks)` — only captures the LAST iteration's text. All intermediate-turn narration is discarded when the model stops calling tools.
  2. AnthropicSDKBackend.complete_with_tools at llm_backend.py:298 `msg = client.messages.create(...)` — no try/except. SDK RateLimitError / APIError / network failures crash the loop with the partial `messages` state inaccessible to callers for retry.
  3. OpenAICompatBackend.complete at llm_backend.py:~305 `client.chat.completions.create(...)` — no `response_format`. GPT-4o and most OpenAI-compat models often emit markdown-fenced JSON or conversational filler when engine prompts require strict JSON (judge scoring, skill classification, skill distillation). Causes JSON parse crash for first openai-compat user.
MIGRATION: None — all three fixes are additive or strictly-more-robust behavior. Existing claude-code and anthropic-sdk callers see no behavior change. openai-compat callers now get valid JSON where engine prompts request it; callers that pass text prompts continue to work (json_mode defaults to False).
CALLERS:
  - complete_with_tools: only called from steward_dispatch.spawn_steward_subagent() — this is the Steward tool-use path in anthropic-sdk mode.
  - complete (with new json_mode kwarg): called from 5 engine sites currently, 4 of which request JSON-shaped output (judge_scorer, classify_concepts, backfill_distill, roundtable_runner._distill_skills). Haiku summarizer + therapist call it for text, no json_mode change needed.
USER_PATH:
  Fix 1: user in anthropic-sdk mode runs amatelier roundtable with [[request: ...]] tags → Steward invokes complete_with_tools → model narrates "Let me check X" in iteration 1, calls read_file, synthesizes "Based on X, the answer is Y" in iteration 2 → BEFORE: only "Based on X..." returned. AFTER: both iterations' text concatenated.
  Fix 2: user in anthropic-sdk mode hits a transient 429 rate-limit during iteration 3 of a Steward loop → BEFORE: RateLimitError propagates unhandled, partial message state lost, Steward returns status=error. AFTER: exception caught, accumulated messages visible in log, tool_use_id round-trip preserved, Steward returns status=error with full diagnostic context.
  Fix 3: user with OPENAI_API_KEY or OPENROUTER_API_KEY set, runs first roundtable → judge_scorer._call_sonnet() calls backend.complete(..., json_mode=True) → OpenAICompatBackend adds response_format={"type":"json_object"} → GPT-4o returns clean JSON → engine parses successfully. BEFORE: GPT-4o returns `` ```json\n{...}\n``` ``, parser crashes with JSONDecodeError.
RED_STATE:
  - llm_backend.py:320 `final_text = "".join(text_chunks)` — text_chunks is the current iteration's blocks only; prior iterations' text already discarded at the top of each loop iteration
  - llm_backend.py:298-305 client.messages.create is not inside a try/except; only the tool_executor call later in the loop is protected
  - llm_backend.py:~305 OpenAICompatBackend.complete client.chat.completions.create has no response_format param and no json_mode detection
  - judge_scorer.py:~155 backend.complete(system=..., prompt=..., model="sonnet", max_tokens=8000, timeout=360, effort=effort) — passes no json_mode; JSON-requiring prompt hits openai-compat without response_format
  - classify_concepts.py, backfill_distill.py, roundtable_runner.py:_distill_skills: same pattern — backend.complete without json_mode, all 3 request JSON output
RED_TYPE: USER-OBSERVABLE
GREEN_CONDITION:
  1. complete_with_tools accumulates text from all iterations (final_text = existing_text + "".join(current_chunks)) — unit test: mock 3 iterations, assert iteration-2 text in returned Completion.text
  2. complete_with_tools wraps the `msg = client.messages.create(...)` call in try/except; on exception, returns a Completion with text=accumulated_text_so_far, model, backend, latency_ms, and logs a warning with the accumulated messages length
  3. LLMBackend.complete accepts optional `json_mode: bool = False`. OpenAICompatBackend translates json_mode=True → response_format={"type":"json_object"}. ClaudeCLIBackend and AnthropicSDKBackend accept and ignore (Claude handles JSON without hint).
  4. Four engine call sites pass json_mode=True where they expect JSON: judge_scorer._call_sonnet, classify_concepts._call_sonnet_classifier, backfill_distill.distill_one, roundtable_runner._distill_skills
  5. Local CI passes: ruff, pytest smoke 13/13, pytest integration 11/11, mkdocs build
OMISSIONS:
  - Marcus's 5 mock tests are NOT added in this commit. They're good engineering but not ship-blockers; add in a follow-up commit (tests/test_llm_backend.py).
  - Extended-thinking cost/quality assertion remains uncovered (requires live key; documented as known gap in tests/README.md follow-up).
  - roundtable_runner._summarize_round_haiku and therapist._call_llm pass text prompts — no json_mode change, intentionally left at default False.
  - gemini_agent uses its own path, unchanged.
  - The RT infrastructure collapse (14 worker timeouts in rounds 2-3) is not addressed by these code fixes — it's a concurrency/rate-limit product behavior to document separately, not a code bug.
