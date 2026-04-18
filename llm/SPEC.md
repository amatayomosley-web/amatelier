# amatelier — Specification

> Canonical machine-readable description. This file is hand-written. llm/API.md is auto-generated from src/ introspection; llm/SCHEMA.md is auto-generated from config schemas; this file is not.

## Identity

```yaml
name: amatelier
display_name: Amatelier
version: 0.2.0
license: MIT
author: Maximillian
standard: Amatayo Standard v1.0
python_required: ">=3.10"
homepage: https://github.com/amatayomosley-web/amatelier
pypi: https://pypi.org/project/amatelier/
docs: https://amatayomosley-web.github.io/amatelier/
llm_context: https://raw.githubusercontent.com/amatayomosley-web/amatelier/main/llms-full.txt
entry_script: amatelier
entry_module: amatelier.cli:main
```

## Purpose

A self-evolving multi-model AI team. Ten persona agents debate topics in a SQLite-backed chat, earn sparks on a 0-3-10 scoring rubric, buy skills from a store, and evolve persona seeds through therapist-led debriefs. Cross-model by design — Claude Sonnet, Claude Haiku, and Gemini Flash by default, with full support for any OpenAI-compatible provider (except the Steward empirical-lookup subagent, which is unavailable in `openai-compat` mode — use `claude-code` or `anthropic-sdk` if you need Steward). Ships as a single pip-installable package that runs inside Claude Code or standalone against an API.

## Modes

```yaml
- name: claude-code
  detection: shutil.which("claude") is not None
  prereqs: claude CLI binary on PATH
  provider: subprocess call to claude CLI
  implementation: amatelier.llm_backend.ClaudeCLIBackend
  default_model_map: {sonnet: claude-sonnet-4-20250514, haiku: claude-haiku-4-5-20251001, opus: claude-opus-4-20250514}

- name: anthropic-sdk
  detection: bool(os.environ["ANTHROPIC_API_KEY"])
  prereqs: ANTHROPIC_API_KEY env var, anthropic>=0.40.0 package
  provider: direct Anthropic HTTP API
  implementation: amatelier.llm_backend.AnthropicSDKBackend
  default_model_map: {sonnet: claude-sonnet-4-20250514, haiku: claude-haiku-4-5-20251001, opus: claude-opus-4-20250514}

- name: openai-compat
  detection: bool(os.environ["OPENAI_API_KEY"]) or bool(os.environ["OPENROUTER_API_KEY"])
  prereqs: OPENAI_API_KEY or OPENROUTER_API_KEY env var, openai>=1.0 package
  provider: any OpenAI-compatible Chat Completions endpoint
  implementation: amatelier.llm_backend.OpenAICompatBackend
  default_base_url_openai: https://api.openai.com/v1
  default_base_url_openrouter: https://openrouter.ai/api/v1
  default_model_map_openai: {sonnet: gpt-4o, haiku: gpt-4o-mini, opus: gpt-4o}
  default_model_map_openrouter: {sonnet: anthropic/claude-sonnet-4, haiku: anthropic/claude-haiku-4-5, opus: anthropic/claude-opus-4}
```

```yaml
selection_order:
  1: AMATELIER_MODE env var (explicit override)
  2: config.json llm.mode (if not "auto")
  3: auto-detect — claude-code > anthropic-sdk > openai-compat (first available wins)
  4: raise BackendUnavailable with setup guidance
```

```yaml
naomi_provider:
  note: Naomi always runs via Gemini regardless of worker-mode selection
  env_var: GEMINI_API_KEY
  package: google-genai>=1.51.0
  default_model: gemini-3-flash-preview
  implementation: amatelier.engine.gemini_client
  bypass_flag: --skip-naomi
```

## Top-level components

```yaml
- name: amatelier.paths
  path: src/amatelier/paths.py
  purpose: Amatayo Standard dual-layer filesystem contract — bundled (read-only, in wheel) vs user_data (read-write, platformdirs)
  public_api: [APP_NAME, bundled_assets_dir, bundled_docs_dir, bundled_agent_dir, bundled_store_catalog, bundled_config, user_data_dir, user_agent_dir, user_db_path, user_logs_dir, user_digest_dir, user_briefing_dir, user_store_ledger, user_novel_concepts, user_shared_skills_index, user_config_override, ensure_user_data]
  depends_on: [platformdirs]
  override_env: AMATELIER_WORKSPACE
  bootstrap_sentinel: ".bootstrap-complete"
  invariants:
    - user_data_dir is writable; bundled_assets_dir is read-only post-install
    - ensure_user_data() is idempotent and lazy (no writes at import time)
    - Override via AMATELIER_WORKSPACE env var replaces platformdirs resolution

- name: amatelier.llm_backend
  path: src/amatelier/llm_backend.py
  purpose: Three-backend abstraction with singleton resolver and role-based model mapping
  public_api: [Completion, LLMBackend, BackendUnavailable, ClaudeCLIBackend, AnthropicSDKBackend, OpenAICompatBackend, get_backend, resolve_mode, describe_environment, call_claude]
  depends_on: [amatelier.paths, anthropic, openai]
  config_section: llm
  role_tokens: [sonnet, haiku, opus]
  back_compat: call_claude(system_prompt, prompt, agent_name, model) delegates to get_backend()

- name: amatelier.cli
  path: src/amatelier/cli.py
  purpose: Shell entry point; subcommand dispatcher
  public_api: [main]
  subcommands:
    - roundtable: dispatches to amatelier.engine.roundtable_runner via runpy
    - watch: dispatches to amatelier.tools.watch_roundtable
    - therapist: dispatches to amatelier.engine.therapist via runpy
    - analytics: dispatches to amatelier.engine.analytics via runpy
    - refresh-seeds: in-process — re-copies bundled persona seeds into user_data_dir
    - docs: in-process — prints bundled docs to stdout
    - config: in-process — diagnoses LLM backend + paths (supports --json)
    - --version: prints amatelier.__version__
  stdout_reconfigure: utf-8 with errors="replace" for Windows console safety

- name: amatelier.engine.roundtable_runner
  path: src/amatelier/engine/roundtable_runner.py
  purpose: Primary orchestrator — opens RT, spawns worker processes, runs structured debate, closes, triggers scoring/distillation/therapist
  public_api: [run_roundtable, build_digest, format_digest_summary]
  depends_on: [amatelier.engine.db (via db_client.py subprocess), amatelier.engine.steward_dispatch, amatelier.engine.judge_scorer (subprocess), amatelier.engine.scorer (subprocess), amatelier.engine.distiller, amatelier.engine.analytics (subprocess), amatelier.engine.evolver, amatelier.engine.store, amatelier.engine.agent_memory, amatelier.engine.therapist (subprocess)]
  cli_flags: [--topic REQUIRED, --briefing REQUIRED, --workers CSV, --max-rounds INT, --skip-naomi, --speaker-timeout INT, --budget INT (default 3), --skip-post, --summary]
  default_workers: [elena, marcus, clare, simon]
  default_max_rounds: 3
  worker_spawn_strategy: subprocess.Popen with inherited env; each agent connects to SQLite and polls for turns

- name: amatelier.engine.claude_agent
  path: src/amatelier/engine/claude_agent.py
  purpose: Worker subprocess for Claude-backed agents; reads DB, assembles context, calls LLM backend, posts response
  cli_flags: [--agent NAME, --model sonnet|haiku|opus]
  consumes: agents/<name>/CLAUDE.md, agents/<name>/IDENTITY.md, agents/<name>/MEMORY.md, agents/<name>/MEMORY.json, agents/<name>/behaviors.json

- name: amatelier.engine.gemini_client
  path: src/amatelier/engine/gemini_client.py
  purpose: Thin wrapper over google-genai SDK for Naomi
  env_required: GEMINI_API_KEY

- name: amatelier.engine.gemini_agent
  path: src/amatelier/engine/gemini_agent.py
  purpose: Naomi worker subprocess; same chat-loop contract as claude_agent but uses gemini_client
  cli_flags: [--agent naomi]

- name: amatelier.engine.db
  path: src/amatelier/engine/db.py
  purpose: SQLite access layer for roundtable chat (WAL mode, busy_timeout, auto-migration)
  public_api: [get_db, open_roundtable, close_roundtable, speak, listen, get_transcript, get_cursor, set_cursor]
  db_path: user_data_dir()/roundtable-server/roundtable.db
  migrations_dir: src/amatelier/engine/migrations/
  invocation: via db_client.py subprocess wrapper from runner

- name: amatelier.engine.scorer
  path: src/amatelier/engine/scorer.py
  purpose: Score aggregation, fee deduction, gate bonuses, Byzantine variance detection, leaderboard
  public_api: [score, deduct_fee, gate, leaderboard, compute_variance_flags]
  cli_subcommands: [score, deduct-fee, gate, leaderboard]

- name: amatelier.engine.judge_scorer
  path: src/amatelier/engine/judge_scorer.py
  purpose: Runs Judge LLM on full transcript to emit per-agent per-axis scores
  public_api: [judge_score]
  axes: [novelty, accuracy, impact, challenge]
  scale: [0, 1, 2, 3, 10]
  effort: max

- name: amatelier.engine.therapist
  path: src/amatelier/engine/therapist.py
  purpose: Post-RT debrief — 2-3 turn Opus-led interview per agent; emits behaviors/memory/session updates
  public_api: [run_session, run_therapist]
  cli_flags: [--digest REQUIRED, --agents CSV, --turns INT (default 2)]
  writes: agents/<name>/MEMORY.md, MEMORY.json, behaviors.json, sessions/<rt_id>.md; agents/therapist/case_notes/<name>.json
  frameworks: [GROW+AAR, SBI, OARS]

- name: amatelier.engine.distiller
  path: src/amatelier/engine/distiller.py
  purpose: Skill extraction from transcripts; index and shared-skills promotion
  public_api: [create_skill_entry, save_skill_to_agent, promote_to_shared, search_shared_skills, load_index, save_index, list_agent_skills]
  types: [CAPTURE, FIX, DERIVE]
  output: user_data_dir()/shared-skills/entries/*.md, shared-skills/index.json

- name: amatelier.engine.evolver
  path: src/amatelier/engine/evolver.py
  purpose: Apply therapist behavior deltas; sync skills_owned from ledger; decay unconfirmed behaviors
  public_api: [apply_behavior_delta, sync_skills_owned, decay_behaviors, prune_faded_behaviors]
  decay_rate: 0.05
  fade_threshold: 0.5

- name: amatelier.engine.steward_dispatch
  path: src/amatelier/engine/steward_dispatch.py
  purpose: Parse [[request:]] tags; dispatch ephemeral file-access subagent; format and inject result
  public_api: [parse_requests, strip_requests, format_result, StewardBudget, StewardTask, StewardLog, load_registered_files]
  execution_paths: [deterministic (JSON/grep, no LLM), subagent (claude -p with Read/Grep/Glob)]
  default_budget_per_agent_per_rt: 3
  research_window_budget: 3 free pre-debate requests

- name: amatelier.engine.store
  path: src/amatelier/engine/store.py
  purpose: Spark economy — purchases, delivery, boost application, consumable lifecycle, bulletin-board
  public_api: [attempt_purchase, apply_boosts_for_rt, consume_boosts_after_rt, deliver_skill, age_bulletin_requests, list_requests]
  catalog: src/amatelier/store/catalog.json
  skill_templates: src/amatelier/store/skill_templates.py
  ledger: user_data_dir()/store/ledger.json (pending purchases and consumable state)
  balance_source: spark_ledger table in SQLite (SUM by agent)

- name: amatelier.engine.agent_memory
  path: src/amatelier/engine/agent_memory.py
  purpose: MEMORY.json structured access — goals, session summaries, episode aging, session bridges
  public_api: [render_memory, age_goals, generate_session_bridge, append_session_summary, add_goal, add_episode]
```

## The 10 agents

```yaml
registry:
  - name: elena
    tier: sonnet
    role: worker — synthesis and architecture
    scoring: yes
    sparks: yes
    seed: src/amatelier/agents/elena/
    persona_files: [CLAUDE.md, IDENTITY.md]
    runtime_state_dir: user_data_dir()/agents/elena/
  - name: marcus
    tier: sonnet
    role: worker — challenge and exploit detection
    scoring: yes
    sparks: yes
    seed: src/amatelier/agents/marcus/
  - name: clare
    tier: haiku
    role: worker — concise structural analysis
    scoring: yes
    sparks: yes
    seed: src/amatelier/agents/clare/
  - name: simon
    tier: haiku
    role: worker — triage and fix sequencing
    scoring: yes
    sparks: yes
    seed: src/amatelier/agents/simon/
  - name: naomi
    tier: gemini-flash
    role: worker — cross-model blind-spot catcher
    scoring: yes
    sparks: yes
    seed: src/amatelier/agents/naomi/
    provider: gemini (google-genai)
    bypass_flag: --skip-naomi
  - name: judge
    tier: sonnet
    role: live moderator — in-chat referee; scores others post-RT
    scoring: no (is the scorer)
    sparks: no
    seed: src/amatelier/agents/judge/
  - name: therapist
    tier: haiku
    role: post-RT interviewer; writes behaviors/memory/sessions
    scoring: no
    sparks: no
    seed: src/amatelier/agents/therapist/
  - name: opus-admin
    tier: opus
    role: strategy, directives, final sign-off; user-facing
    scoring: no
    sparks: no
    seed: src/amatelier/agents/opus-admin/
  - name: opus-therapist
    tier: opus
    role: meta-therapist, persona coach, scoring supervision
    scoring: no
    sparks: no
    seed: src/amatelier/agents/opus-therapist/
  - name: haiku-assistant
    tier: haiku
    role: deprecated in 0.2.0 — mechanics replaced by roundtable_runner.py
    scoring: no
    sparks: no
    seed: src/amatelier/agents/haiku-assistant/
```

## Invariants

```yaml
- id: 1
  statement: llm/ directory is flat (no subdirectories)
  rationale: scripts/regen_full.py globs llm/*.md; subdirectories break the one-shot concatenation

- id: 2
  statement: user_data_dir() holds all mutable state; bundled_assets_dir() is read-only post-install
  rationale: pip upgrades must never clobber evolved agent state

- id: 3
  statement: ensure_user_data() is idempotent and gated by .bootstrap-complete sentinel
  rationale: import-time call in __init__.py must be cheap on repeat invocations

- id: 4
  statement: Engine reads persona seeds from user_data_dir(); refresh-seeds re-copies from bundled
  rationale: User edits to CLAUDE.md/IDENTITY.md persist across pip upgrades unless --force is passed

- id: 5
  statement: Worker agents run as subprocesses and communicate only via SQLite chat
  rationale: No in-process imports from runner to worker; crash isolation and language-agnostic workers

- id: 6
  statement: llm_backend.get_backend() is cached via functools.lru_cache(maxsize=1)
  rationale: Single instantiation per process; mode flip-flop requires process restart

- id: 7
  statement: Scoring axes are novelty, accuracy, impact, challenge; scale is 0/1/2/3/10 (no 4-9)
  rationale: 10 is a discontinuity ("grand insight"), not the top of a gradient

- id: 8
  statement: Sparks are derived from spark_ledger table — current balance = SUM(amount) WHERE agent_name = X
  rationale: Append-only ledger is source of truth; metrics.json is cached view

- id: 9
  statement: Briefing path is resolved first against user_data_dir()/roundtable-server/, then as-is
  rationale: Briefings can live in the workspace or be passed by absolute path

- id: 10
  statement: roundtable_runner.WORKSPACE_ROOT resolves from AMATELIER_WORKSPACE env var, else SUITE_ROOT.parent.parent.parent
  rationale: Subprocess cwd stability across pip-install vs clone layouts

- id: 11
  statement: Steward requests require entries in briefing ## Steward-Registered Files section
  rationale: File tool access is scoped; undeclared paths are rejected

- id: 12
  statement: Entry fees are deducted per-RT at open; floor is 0 gross (penalties never push below 0)
  rationale: Calibration; operating fee still applies

- id: 13
  statement: Naomi always uses google-genai regardless of worker-mode resolution
  rationale: Cross-model blind-spot catching is Naomi's reason to exist

- id: 14
  statement: scripts/regen_full.py orders llm/*.md as SPEC > API > SCHEMA > WORKFLOWS > EXAMPLES > alphabetical
  rationale: Deterministic llms-full.txt layout for downstream consumers

- id: 15
  statement: Distillation runs in --skip-post mode; therapist and cleanup are skipped
  rationale: Faster iteration during development; distillation is cheap and always informative
```

## Spark economy (summary, full rules in docs/reference/protocols/spark-economy.md)

```yaml
entry_fees:
  haiku: 5
  flash: 5
  sonnet: 8
  opus: 15
  note: flat per-RT, deducted at open
penalties:
  redundancy: -3
  hallucination: -5
  off_directive: -5
  floor: 0 gross (cannot go negative from penalties alone)
bonuses:
  gate_bonus: 3 sparks per Judge GATE signal (max 3 per RT)
  rt_outcome_bonus: 5 sparks when extracted proposal is implemented
relegation:
  trigger: 3 consecutive net-negative RTs (gross - entry_fee < 0)
  options: [bench (passive 2 sparks/RT), deletion]
  decision_owner: agent
ventures:
  scout:    {stake: 5,  multiplier: 3.0}
  venture:  {stake: 12, multiplier: 3.5}
  moonshot: {stake: 30, multiplier: 4.0}
```

## Scoring

```yaml
axes: [novelty, accuracy, impact, challenge]
scale: [0, 1, 2, 3, 10]
calibration:
  - most_contributions_score: 1
  - average_rt_total: 4-6
  - score_2_means: clearly above-average
  - score_3_means: exceptional and rare
  - score_10_means: grand insight — discontinuity, judge must quote the message and describe before/after shift
scorer: judge-sonnet (effort=max)
axis_name_invariant: field is "impact" (not net_impact or influence)
persistence: scores table in roundtable.db (migration 002)
```

## File lifecycle

```yaml
bundled_read_only:
  - src/amatelier/config.json
  - src/amatelier/agents/<name>/CLAUDE.md
  - src/amatelier/agents/<name>/IDENTITY.md
  - src/amatelier/store/catalog.json
  - src/amatelier/store/skill_templates.py
  - docs/ (force-included into wheel as amatelier/docs/)

user_data_writable:
  root: platformdirs user_data_dir("amatelier") or $AMATELIER_WORKSPACE
  - roundtable-server/roundtable.db (SQLite, WAL)
  - roundtable-server/briefing-*.md (user-authored)
  - roundtable-server/digest-<rt_id>.json (runner output)
  - roundtable-server/latest-result.md (completion notification)
  - roundtable-server/logs/gemini_errors.log (Naomi runtime errors)
  - agents/<name>/CLAUDE.md (seeded from bundled; user- and therapist-editable)
  - agents/<name>/IDENTITY.md (seeded from bundled; therapist-editable)
  - agents/<name>/MEMORY.md (evolving, written by therapist)
  - agents/<name>/MEMORY.json (structured — goals, skills_owned, sessions)
  - agents/<name>/behaviors.json (therapist-proposed deltas)
  - agents/<name>/metrics.json (cached sparks, rank, trait state)
  - agents/<name>/sessions/<rt_id>.md (per-RT debrief)
  - agents/<name>/skills/<skill_id>.md (purchased skill files)
  - agents/therapist/case_notes/<name>.json (therapist's clinical notes)
  - store/ledger.json (pending/consumed purchase state)
  - shared-skills/index.json (curated skill index)
  - shared-skills/entries/*.md (promoted skills)
  - novel_concepts.json (DERIVE skills with taxonomy)
  - benchmarks/leaderboard.json (post-RT snapshot)
  - .bootstrap-complete (sentinel)
  - config.json (optional user override of bundled config)

auto_generated:
  - llm/API.md: by scripts/regen_llm.py (from src/ introspection)
  - llm/SCHEMA.md: by scripts/regen_llm.py (stub; generator enhancement pending)
  - llms.txt: by scripts/regen_full.py (concatenated llm/*.md index)
  - llms-full.txt: by scripts/regen_full.py (concatenated llm/*.md full body)
  - .cursor/rules/*: by scripts/regen_tool_rules.py
  - .github/copilot-instructions.md: by scripts/regen_tool_rules.py
```

## Glossary

```yaml
spark: unit of the competitive economy; earned via scoring/gate/outcome, spent on store items
gate: Judge-issued "GATE: agent — reason" signal in chat; awards 3 bonus sparks to named agent (max 3 per RT)
grand_insight: score of 10 on a single axis; requires quotable discontinuity message
digest: structured JSON summary of a completed RT (contributions, final positions, budget usage, convergence reason)
briefing: user-authored markdown file describing topic, context, constraints, and optional ## Steward-Registered Files
roundtable: single debate session; one row in roundtables table; append-only messages, scored once post-close
steward: ephemeral subagent that fulfills [[request:]] tags; no persona, no persistence, no spark balance
distillation: post-RT extraction of 10-15 skill candidates from transcript via separate Sonnet call
CAPTURE: skill type — observed reusable technique
FIX: skill type — anti-pattern correction
DERIVE: skill type — synthesized concept from multiple contributions; requires agent_dynamic field
episode: memory entry; goals and session summaries age each RT
session: per-RT 2-3 turn therapist interview for one agent; output writes to sessions/<rt_id>.md
venture: spark-staking contract extracted from <VENTURE>/<MOONSHOT>/<SCOUT> tags in transcript
research_window: pre-debate Round 0 — 3 free Steward requests per agent, budget-exempt
floor_phase: optional extra turns per round, costs 1 budget per contribution (default 3 per RT)
speak_phase: mandatory first-post phase per round; all workers speak once
rebuttal_phase: mandatory second-post phase per round; reverse order
judge_gate: after rebuttals — Judge emits CONVERGED or CONTINUE; CONVERGED ends round loop
skip_post: runner flag — stops after scoring/distillation, skips therapist + cleanup (for iteration)
workspace: AMATELIER_WORKSPACE env var — overrides platformdirs user_data_dir resolution
```

## Canonical references

```yaml
spark_economy: docs/reference/protocols/spark-economy.md
competition_rubric: docs/reference/protocols/competition.md
distillation_flow: docs/reference/protocols/distillation.md
debrief_framework: docs/reference/protocols/debrief.md
research_protocol: docs/reference/protocols/research.md
roundtable_protocol: docs/reference/protocols/roundtable.md
learning_protocol: docs/reference/protocols/learning.md
memory_tiers: docs/reference/protocols/memory-tiers.md
verification: docs/reference/protocols/verification.md
sparc_phases: docs/reference/protocols/sparc-phases.md
gemini_bridge: docs/reference/protocols/gemini-bridge.md
architecture_essay: docs/explanation/architecture.md
steward_design: docs/explanation/steward-design.md
cli_reference: docs/reference/cli.md
config_reference: docs/reference/config.md
breaking_changes_0_2_0: CHANGELOG.md
```
