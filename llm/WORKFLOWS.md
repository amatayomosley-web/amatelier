# Workflows

> Turn-by-turn orchestration paths. Hand-written. Answers the question: "this command ran — what happened, step by step, and which module.function owns each step?"

## Conventions

- Each workflow is a named section
- Steps are numbered, expressed as YAML
- Each step names the module:function responsible
- Inputs and outputs are explicit
- Failure modes listed at the end of each workflow

## Workflow: amatelier roundtable (happy path)

Trigger: `amatelier roundtable --topic T --briefing B [--workers CSV] [--max-rounds N] [--skip-naomi] [--budget N] [--speaker-timeout S] [--skip-post] [--summary]`

```yaml
- step: 1
  actor: amatelier.cli:main
  action: Reconfigure stdout/stderr to utf-8; dispatch on argv[0]
  inputs: sys.argv[1:]
  outputs: dispatch decision
- step: 2
  actor: amatelier.cli:_run_engine_module
  action: sys.argv = ["roundtable_runner", ...rest]; runpy.run_module("roundtable_runner", run_name="__main__", alter_sys=True)
  note: The engine module ships as a flat-import module because __init__.py inserts src/amatelier/engine into sys.path
- step: 3
  actor: amatelier.engine.roundtable_runner (module __main__ block)
  action: argparse parses flags; calls run_roundtable(topic, briefing_path, workers, max_rounds, skip_naomi, speaker_timeout, budget_per_agent, skip_post)
- step: 4
  actor: amatelier.engine.roundtable_runner:run_roundtable
  action: load_config() reads bundled config.json; resolve default_workers if --workers not given; resolve max_rounds default
- step: 5
  actor: amatelier.engine.roundtable_runner:run_roundtable
  action: Resolve briefing file — first try SUITE_ROOT/roundtable-server/<briefing>, else treat as absolute path; read text; FileNotFoundError if missing
- step: 6
  actor: amatelier.engine.steward_dispatch:load_registered_files
  action: Parse "## Steward-Registered Files" section from briefing markdown; produce list of absolute paths. If empty, steward_enabled flips to False for this RT
- step: 7
  actor: amatelier.engine.store:apply_boosts_for_rt
  action: Read store/ledger.json for each worker; apply consumable effects (e.g. +extra_floor_turns to budget dict)
- step: 8
  actor: amatelier.engine.evolver:sync_skills_owned
  action: Per worker — diff spark_ledger category=purchase entries against MEMORY.json.skills_owned; refresh
- step: 9
  actor: amatelier.engine.agent_memory:generate_session_bridge
  action: Per worker — emit "last time you..." context block from prior session summary; stored for next agent-context assembly
- step: 10
  actor: amatelier.engine.db (via db_client.py subprocess)
  action: db_cmd("open", topic, participants_csv) — INSERT INTO roundtables; returns rt_id (hex). Runner joins as "runner"
- step: 11
  actor: amatelier.engine.db (via db_client.py subprocess)
  action: db_cmd("speak", "runner", "BRIEFING:\n\n<text>") — posts briefing to chat
- step: 12
  actor: amatelier.engine.roundtable_runner:run_roundtable
  action: For each worker — resolve_agent_model() reads config.json team.workers.<name>.model; determines entry-fee tier (haiku/flash/sonnet/opus)
- step: 13
  actor: amatelier.engine.scorer (via subprocess "deduct-fee")
  action: Insert spark_ledger row with negative amount = entry fee; category=fee
- step: 14
  actor: amatelier.engine.roundtable_runner._launch_claude / _launch_gemini
  action: subprocess.Popen per worker — claude_agent.py or gemini_agent.py; cwd=WORKSPACE_ROOT; env includes PYTHONIOENCODING=utf-8 and loaded .env vars. Also launch judge (Claude sonnet). Sleep 5s for connection
- step: 15
  actor: amatelier.engine.roundtable_runner:run_roundtable (Research Window — optional)
  action: If steward_enabled and registered_files — broadcast RESEARCH WINDOW signal; each worker speaks once with up to 3 [[request:]] tags; fire StewardTask per request (free, budget-exempt); await all; inject results via db_cmd("speak", "runner", format_result(...))
- step: 16
  actor: amatelier.engine.roundtable_runner:run_roundtable (speaking-order setup)
  action: random.shuffle(all_workers); _resolve_first_speaker() scans store/ledger.json for pending first-speaker purchases; highest-rank bidder wins; winner inserted at index 0, losers refunded into metrics.json
- step: 17
  actor: amatelier.engine.roundtable_runner:run_roundtable (round loop, 1..max_rounds)
  action: For each round — post "ROUND N: begin\nBUDGET STATUS: <...>"
- step: 18
  actor: amatelier.engine.roundtable_runner (SPEAK PHASE)
  action: Post "--- SPEAK PHASE (Round N) ---". Process queue — for each agent, _call_speaker posts "YOUR TURN: <name> — SPEAK" and wait_for_single_speaker polls DB until that agent writes or speaker_timeout (default 200s). Parse returned message for [[request:]] tags
- step: 19
  actor: amatelier.engine.steward_dispatch (if request tag present)
  action: steward_budget.spend() decrements; StewardTask started in background thread; agent appended to back of speak_queue (deferred). Task result polled before subsequent agents speak; INTERMISSION fires if entire queue is deferred; post-phase all pending tasks drained
- step: 20
  actor: amatelier.engine.roundtable_runner (stability measurement)
  action: If round_num > 1, compute per-agent Jaccard similarity between this round's SPEAK and prior round's SPEAK; log stability_scores[round_num]
- step: 21
  actor: amatelier.engine.roundtable_runner (REBUTTAL PHASE)
  action: Post "--- REBUTTAL PHASE ---"; iterate speaking_order in reverse; _call_speaker each. No [[request:]] deferral in rebuttal phase
- step: 22
  actor: amatelier.engine.roundtable_runner (JUDGE GATE)
  action: Post "--- JUDGE GATE ---" with instruction to emit CONVERGED:<reason> or CONTINUE:<gap>. wait_for_single_speaker("judge"). check_convergence scans for CONVERGED prefix; if found, break round loop
- step: 23
  actor: amatelier.engine.roundtable_runner (FLOOR PHASE)
  action: Gather floor_eligible = workers with budget > 0. Iterate — _call_speaker. is_pass() detects PASS response; contributions decrement budget[agent] by 1 and mark eligible for another floor turn while budget remains. Continue until all pass or all budgets exhausted
- step: 24
  actor: amatelier.engine.roundtable_runner (round health audit)
  action: Count alive agent_procs; count "timed out"/"did not respond" runner messages this round. Majority-dead → abort
- step: 25
  actor: amatelier.engine.roundtable_runner (Gemini refresh, conditional)
  action: At round == gemini_refresh_round (default 5, from config.roundtable.gemini_refresh_round), terminate and relaunch naomi subprocess to reset API rate-limit state
- step: 26
  actor: amatelier.engine.db (via db_client.py subprocess)
  action: After round loop completes — db_cmd("close"); RT status=closed
- step: 27
  actor: amatelier.engine.roundtable_runner:build_digest
  action: Assemble digest dict — topic, rt_id, rounds, total_messages, contributions (count by agent), final_positions (last message by agent), converged, convergence_reason, judge_interventions, budget_usage, stability_scores
- step: 28
  actor: amatelier.engine.judge_scorer:judge_score (invoked by runner)
  action: Judge LLM call with full transcript; effort=max sonnet; emits per-agent scores on 4 axes (0/1/2/3/10). Persist to scores table
- step: 29
  actor: amatelier.engine.roundtable_runner:_process_gate_bonuses
  action: Scan transcript for Judge "GATE: <agent> — <reason>" messages; award 3 sparks each; cap at config.competition.gate_bonus.max_per_rt
- step: 30
  actor: amatelier.engine.scorer:compute_variance_flags
  action: Byzantine detector — flag agents whose scores deviate too far from peer consensus across recent RTs. Updates scores.is_flagged
- step: 31
  actor: amatelier.engine.roundtable_runner:_extract_and_register_ventures
  action: Parse <VENTURE>/<MOONSHOT>/<SCOUT> tags in transcript; register spark-stake contracts
- step: 32
  actor: amatelier.engine.roundtable_runner:_save_leaderboard
  action: Subprocess — scorer.py leaderboard; write benchmarks/leaderboard.json
- step: 33
  actor: amatelier.engine.roundtable_runner:_update_analytics
  action: Subprocess — analytics.py update; compute per-agent growth curves
- step: 34
  actor: amatelier.engine.roundtable_runner:_distill_skills
  action: Sonnet subprocess (claude -p with --no-session-persistence --dangerously-skip-permissions --max-budget-usd 5.00); produces 10-15 skill candidate objects as JSON; each has title, type (CAPTURE|FIX|DERIVE), agent, pattern, when_to_apply, structural_category, trigger_phase, primary_actor, problem_nature, agent_dynamic (DERIVE only), tags, one_liner
- step: 35
  actor: amatelier.engine.roundtable_runner:_append_novel_concepts
  action: Filter DERIVE skills; content-hash dedup; append to user_data_dir()/novel_concepts.json
- step: 36
  actor: amatelier.engine.therapist (subprocess, skipped if --skip-post)
  action: For each worker — run_session(rt_id, agent, digest, max_turns=2); 2-3 turn private interview. See separate therapist workflow
- step: 37
  actor: amatelier.engine.store:consume_boosts_after_rt
  action: Mark consumable purchase entries that fired this RT as consumed; write store/ledger.json
- step: 38
  actor: amatelier.engine.store:age_bulletin_requests
  action: Decrement age counters on open public-request entries; expire stale
- step: 39
  actor: amatelier.engine.agent_memory:age_goals
  action: Per worker — tick active goals forward; expire goals past their horizon
- step: 40
  actor: amatelier.engine.evolver:sync_skills_owned
  action: Per worker — refresh MEMORY.json.skills_owned from spark_ledger purchase entries
- step: 41
  actor: amatelier.engine.roundtable_runner:_notify_completion
  action: Write user_data_dir()/roundtable-server/latest-result.md; fire OS toast notification (best-effort)
- step: 42
  actor: amatelier.engine.roundtable_runner (__main__)
  action: If --summary: print format_digest_summary(digest). Else: print json.dumps(digest, indent=2, ensure_ascii=False)
```

Failure modes:

```yaml
- condition: Briefing file not found
  detection: step 5 raises FileNotFoundError
  recovery: runner exits non-zero; caller must fix path

- condition: Steward-registered files reference paths outside WORKSPACE_ROOT
  detection: step 6 warn-logs; steward marked inactive for this RT
  recovery: debate continues without steward; agents cannot ground claims in files

- condition: Entry fee deduction subprocess fails
  detection: step 13 try/except; logger.warning, continue
  recovery: RT proceeds without fee; manual ledger repair via scorer.py deduct-fee

- condition: Worker subprocess crashes
  detection: _check_and_restart polls proc.poll() at each round boundary; restarts with same model/tier
  recovery: Lost messages drop; restart captures new TURN signals. Repeated crashes → logged; RT continues with surviving workers

- condition: Gemini rate limit / API error
  detection: gemini_agent.py logs to user_data_dir()/roundtable-server/logs/gemini_errors.log
  recovery: step 25 scheduled refresh; or add --skip-naomi to bypass

- condition: SQLite busy / lock contention
  detection: db_cmd retries 3 times with 2s backoff; WAL mode + busy_timeout on connection
  recovery: Transient; persistent lock raises RuntimeError and kills RT

- condition: claude CLI missing in claude-code mode
  detection: llm_backend.ClaudeCLIBackend.available() returns False; resolve_mode falls through
  recovery: Auto-falls back to anthropic-sdk if ANTHROPIC_API_KEY set, else openai-compat, else BackendUnavailable at first LLM call

- condition: Judge Gate CONTINUE but max_rounds reached
  detection: Round loop exits without break
  recovery: convergence_reason stays None; digest reports converged=False

- condition: Keyboard interrupt
  detection: except KeyboardInterrupt in __main__ block
  recovery: db_cmd("cut", "keyboard interrupt") tries to close RT; exit 1
```

## Workflow: amatelier therapist (standalone or post-RT)

Trigger: `amatelier therapist --digest <path> [--agents CSV] [--turns N]` (or invoked automatically by roundtable_runner step 36 unless --skip-post).

```yaml
- step: 1
  actor: amatelier.engine.therapist (__main__)
  action: argparse → digest path required; optional agents CSV (default: all workers in digest); default turns=2
- step: 2
  actor: amatelier.engine.therapist:run_therapist
  action: Load digest JSON; iterate agents list
- step: 3
  actor: amatelier.engine.therapist:run_session (per agent)
  action: _load_therapist_context() — assemble therapist persona, case_notes, frameworks (GROW+AAR, SBI, OARS)
- step: 4
  actor: amatelier.engine.therapist:_load_agent_state
  action: Read MEMORY.md, MEMORY.json, behaviors.json, metrics.json, sessions/ for this agent
- step: 5
  actor: amatelier.engine.therapist:_extract_agent_data
  action: Pull this agent's contributions, scores, budget_usage, stability from digest
- step: 6
  actor: amatelier.engine.therapist:_compute_skill_impact
  action: Correlate owned skills with this RT's scores; flag fading or unused skills
- step: 7
  actor: amatelier.engine.therapist:_build_agent_brief
  action: Render combined context block for the agent-side of the interview
- step: 8
  actor: amatelier.engine.therapist:_call_therapist
  action: LLM call — therapist opens the interview (opus or configured model). Uses opening_data from step 5-6 on first turn
- step: 9
  actor: amatelier.engine.therapist:_call_agent
  action: LLM call — agent responds (own model/tier). Loops for max_turns exchanges
- step: 10
  actor: amatelier.engine.therapist:_parse_outcomes
  action: Scan conversation for structured blocks — behavioral_deltas, memory_updates, session_summary, trait adjustments, store_request blocks (JSON fenced)
- step: 11
  actor: amatelier.engine.therapist:_apply_outcomes
  action: Dispatch parsed outcomes:
    - behaviors.json — via evolver.apply_behavior_delta
    - MEMORY.md / MEMORY.json — append update blocks
    - sessions/<rt_id>.md — write interview summary
    - store requests — _process_store_request (attempt_purchase if affordable, else queue)
    - goals — agent_memory.add_goal
- step: 12
  actor: amatelier.engine.therapist:_update_case_notes
  action: Increment sessions_conducted; append to clinical_observations, active_hypotheses, intervention_history
- step: 13
  actor: amatelier.engine.therapist:_save_case_notes
  action: Write user_data_dir()/agents/therapist/case_notes/<name>.json
- step: 14
  actor: amatelier.engine.therapist:_mark_private_requests_addressed
  action: Update status of any private-request entries in store/ledger.json that this session addressed
- step: 15
  actor: amatelier.engine.therapist:_generate_report (post-all-agents)
  action: Aggregate per-agent summaries into user_data_dir()/roundtable-server/therapist-report-<rt_id>.md
```

Failure modes:

```yaml
- condition: Digest JSON malformed
  detection: json.load raises
  recovery: Exit non-zero with path in error

- condition: Agent state files missing
  detection: step 4 — paths.user_agent_dir(name) empty
  recovery: ensure_user_data() re-seeds from bundled (first-run path); subsequent failures abort this agent only

- condition: LLM timeout during interview
  detection: _call_llm timeout raises
  recovery: Session marked incomplete; outcomes partially applied; no case notes increment

- condition: Parsed outcomes include purchase for insufficient sparks
  detection: _process_store_request — attempt_purchase returns insufficient_funds
  recovery: Request queued to bulletin board instead; logged
```

## Workflow: steward research request (mid-debate)

Trigger: worker emits `[[request: <natural language query>]]` in a speak/rebuttal/floor turn.

```yaml
- step: 1
  actor: amatelier.engine.roundtable_runner:run_roundtable (post-speaker scan)
  action: After _call_speaker returns, scan last_msg_text with steward_dispatch.parse_requests; regex extracts [[request:...]] payload
- step: 2
  actor: amatelier.engine.steward_dispatch:StewardBudget.spend
  action: Decrement remaining count for this agent; if 0, request denied (no budget)
- step: 3
  actor: amatelier.engine.steward_dispatch:StewardTask (constructor)
  action: Spawn background thread; task.done = threading.Event
- step: 4
  actor: amatelier.engine.roundtable_runner:run_roundtable
  action: Append agent to back of speak_queue (deferred); record in pending_steward dict
- step: 5
  actor: amatelier.engine.steward_dispatch:StewardTask._run (thread)
  action: Try deterministic path first — JSON filter, grep, extract. If successful, skip subagent
- step: 6
  actor: amatelier.engine.steward_dispatch (subagent fallback)
  action: subprocess — claude -p with --allowedTools Read,Grep,Glob --max-budget-usd from config.steward. Registered files appear in prompt context. Model = haiku_model (default) or sonnet_model for complex queries
- step: 7
  actor: amatelier.engine.steward_dispatch:StewardTask._run (completion)
  action: task.done.set(); result stored on task with status, elapsed_s, output
- step: 8
  actor: amatelier.engine.roundtable_runner:run_roundtable
  action: Before next speaker or at INTERMISSION, poll pending_steward tasks; if done.is_set(), call format_result(agent, request, result) and db_cmd("speak", "runner", inject_msg)
- step: 9
  actor: amatelier.engine.steward_dispatch:StewardLog.record
  action: Append to in-memory log (agent, request, result, round_num); exposed in digest for audit
- step: 10
  actor: amatelier.engine.roundtable_runner:run_roundtable
  action: Before REBUTTAL phase starts, drain all remaining pending_steward; inject all results
- step: 11
  actor: deferred agent (on next turn)
  action: When agent is popped from back of queue, they see injected [Research result for <agent>] message in their listen context; can cite in their speak
```

Failure modes:

```yaml
- condition: Subagent timeout (default 120s)
  detection: StewardTask.wait(timeout=timeout_seconds+10) returns with status=timeout
  recovery: Inject "timeout" error message; agent speaks without citation

- condition: Registered file missing on disk
  detection: Subagent Read tool returns error
  recovery: Error captured in result; injected to chat; agent cited anyway or speaks without

- condition: Request outside registered files
  detection: Subagent prompt restricts to listed paths; refuses out-of-scope reads
  recovery: Agent receives "out of scope" result; may retry with different phrasing if budget allows

- condition: All workers deferred simultaneously
  detection: remaining_speakers empty but pending_steward non-empty
  recovery: INTERMISSION — runner blocks on task.wait for each; resumes SPEAK phase after
```

## Workflow: skill distillation (post-RT)

Trigger: end of round loop inside run_roundtable; always runs (even with --skip-post).

```yaml
- step: 1
  actor: amatelier.engine.roundtable_runner:_distill_skills
  action: Build prompt — transcript (capped 50K chars), RT metadata, required JSON schema with 12 fields per skill
- step: 2
  actor: subprocess claude -p (sonnet)
  action: flags — --no-session-persistence --output-format text --disable-slash-commands --dangerously-skip-permissions --max-budget-usd 5.00; timeout 180s; cwd=WORKSPACE_ROOT
- step: 3
  actor: amatelier.engine.roundtable_runner:_distill_skills (parse)
  action: Locate first '[' and last ']' in stdout; json.loads; validate array
- step: 4
  actor: amatelier.engine.roundtable_runner:_append_novel_concepts (DERIVE only)
  action: Filter type=="DERIVE"; compute content hash of title+pattern; dedup against existing novel_concepts.json
- step: 5
  actor: amatelier.engine.distiller:create_skill_entry (via runner or backfill)
  action: For each distilled skill — generate skill_id; attach rt_id, timestamp, originator; prepare entry dict
- step: 6
  actor: amatelier.engine.distiller:_judge_gate
  action: Score extraction worthiness (redundancy, specificity); entries failing the gate are flagged but still included in index with lower priority
- step: 7
  actor: amatelier.engine.distiller:save_index / save_skill_to_agent
  action: Append to user_data_dir()/shared-skills/index.json; write per-agent pending skill markdown
- step: 8
  actor: opus-admin (manual curation step, out-of-band)
  action: Admin reviews candidates; calls distiller.promote_to_shared for the best 3-5; promoted entries move to shared-skills/entries/ and become store-purchasable
```

Failure modes:

```yaml
- condition: Sonnet returns non-JSON output
  detection: json_start/json_end markers missing
  recovery: Log "non-json" error; return empty skills list; digest has no new entries

- condition: Subprocess timeout (180s)
  detection: subprocess.TimeoutExpired
  recovery: Log "timeout" error; return empty skills list

- condition: Subprocess exit non-zero
  detection: result.returncode != 0
  recovery: Log exit code; return empty skills list
```

## Workflow: amatelier refresh-seeds (user opt-in)

Trigger: `amatelier refresh-seeds [--agent NAME] [--force] [--dry-run]`.

```yaml
- step: 1
  actor: amatelier.cli:_run_refresh_seeds
  action: argparse flags; resolve bundled_agents = paths.bundled_assets_dir() / "agents"
- step: 2
  actor: amatelier.cli:_run_refresh_seeds
  action: If --agent given — single-agent list; else — sorted(bundled_agents.iterdir())
- step: 3
  actor: amatelier.cli:_run_refresh_seeds (per agent)
  action: For CLAUDE.md and IDENTITY.md:
    - Read bundled content
    - Compare to user_agent_dir()/<file>
    - If identical — skip (already current)
    - If differs and not --force — skip (user-modified, preserved)
    - If differs and --force or no user copy — write (unless --dry-run)
- step: 4
  actor: amatelier.cli:_run_refresh_seeds
  action: Print Refreshed/Skipped/WRITE counts; footnote reminding that MEMORY/behaviors/metrics are untouched
```

Failure modes:

```yaml
- condition: Bundled agents directory missing (corrupt install)
  detection: step 1 — not bundled_agents.exists()
  recovery: Print error, exit 1; user reinstalls
```

## Workflow: first-run bootstrap

Trigger: first `import amatelier` or first `amatelier <any-command>` on a machine where user_data_dir() has no .bootstrap-complete sentinel.

```yaml
- step: 1
  actor: amatelier/__init__.py (module import)
  action: sys.path prepends src/amatelier/engine and src/amatelier/store for flat-import compat; try: paths.ensure_user_data()
- step: 2
  actor: amatelier.paths:ensure_user_data
  action: Resolve user_data_dir (platformdirs or AMATELIER_WORKSPACE); check for .bootstrap-complete sentinel — if present and not force, return immediately
- step: 3
  actor: amatelier.paths:ensure_user_data
  action: mkdir -p the writable tree — roundtable-server/, roundtable-server/logs/, agents/, store/, shared-skills/
- step: 4
  actor: amatelier.paths:_load_config_for_bootstrap
  action: Read user config override if present, else bundled config; fall back to empty dict on error
- step: 5
  actor: amatelier.paths:ensure_user_data
  action: Union of team.workers keys, admin/judge/therapist names, and subdirs of bundled agents/ — call _copy_agent_seed per name
- step: 6
  actor: amatelier.paths:_copy_agent_seed (per agent)
  action: mkdir user_agent_dir/<name>; copy CLAUDE.md and IDENTITY.md from bundled (shutil.copy2, skip if target exists); mkdir sessions/ and skills/; initialize empty MEMORY.md, MEMORY.json="{}", metrics.json="{}", behaviors.json="{}"
- step: 7
  actor: amatelier.paths:ensure_user_data
  action: _init_json(store/ledger.json, {}); _init_json(novel_concepts.json, []); _init_json(shared-skills/index.json, {"entries": []})
- step: 8
  actor: amatelier.paths:ensure_user_data
  action: Write .bootstrap-complete sentinel with content "1"
```

Failure modes:

```yaml
- condition: AMATELIER_WORKSPACE points at unwritable path
  detection: mkdir or write raises PermissionError
  recovery: __init__.py swallows at import time; first real write (e.g. open RT) surfaces the concrete error

- condition: platformdirs cannot determine user data dir
  detection: unlikely; returns empty string → Path("") which is invalid
  recovery: Same as above — deferred; set AMATELIER_WORKSPACE explicitly

- condition: Bundled agents subdirectory missing (corrupt install)
  detection: bundled_agents.exists() False in step 5
  recovery: Loop skipped; empty user-data tree; refresh-seeds also fails with same symptom
```
