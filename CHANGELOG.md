# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] — 2026-04-18

### Added
- **Roster-agnostic engine.** Worker list is now read from
  `config.team.workers` at runtime via the new `amatelier.worker_registry`
  module. Add/remove/rename workers without editing engine code.
- **`amatelier team` CLI** with six subcommands:
  - `list` — show current roster with models, backends, roles
  - `new <name> [--model M] [--backend B] [--role R] [--from-template T]`
  - `remove <name> [--delete-folder]`
  - `import <template>` — load a starter roster
  - `templates` — list available starter rosters
  - `validate` — check roster integrity (folders, required files, backends)
- **Backend field in `config.team.workers`** — each worker declares
  `"backend": "claude" | "gemini" | "openai-compat"`. The runner's
  `_launch_claude` vs `_launch_gemini` dispatch now reads this field
  instead of checking `agent_name == "naomi"`. Multiple Gemini-backed
  workers are now supported (the "naomi-as-gemini" conflation is removed).
- **`--skip-agent <name>` CLI flag** (repeatable) to omit any specific
  worker per-RT. `--skip-naomi` remains as a back-compat alias that
  filters all gemini-backed workers.
- **Three starter roster templates** at
  `src/amatelier/agents/templates/`:
  - `curated-five/` — the v0.3 default team (Elena/Marcus/Clare/Simon/Naomi)
  - `minimal/` — 2-agent starter (alpha Sonnet + beta Haiku)
  - `empty/` — admin/judge/therapist only; users build their own workers
- **MockBackend** (`amatelier.llm_backend.MockBackend`) — deterministic
  test backend activated via `AMATELIER_MODE=mock`. Returns canned
  completions + tool-use round-trips without network calls. Enables the
  integration tests Marcus's Open-mode RT asked for and Gemini's code
  review recommended.
- **New docs:** `docs/guides/define-your-team.md` (customization walkthrough),
  `docs/explanation/designing-agents.md` (teaching material behind the 5
  curated archetypes), `DESIGN.md` files per curated agent.

### Changed
- **BREAKING for custom code depending on hardcoded worker constants:**
  `roundtable_runner.DEFAULT_WORKERS` is now `[]` and `DEFAULT_MODELS` is
  now `{}`. Code that imported these and expected the v0.3 curated-five
  names must migrate to `worker_registry.list_workers()`.
- Engine files (`roundtable_runner`, `evolver`, `therapist`,
  `backfill_distill`, `agent_memory`) no longer hardcode worker names.
  All dynamic lookups route through `worker_registry`.
- README rewritten with a two-path table: "Try it out" (curated-five)
  vs "Build your own team" (framework).
- `--skip-naomi` preserved as backcompat alias; preferred flag is
  `--skip-agent <name>` which works for any worker.

### Acknowledged / Deferred
- Per Gemini code review (2026-04-18):
  - **Cross-provider tool-use schema translation** (Gemini #1) — OpenAI-compat
    still returns `{"status": "unavailable"}` for Steward. Tracked for v0.5.0+.
  - **Runner modularization** into SetupPhase/DiscussionPhase/DigestPhase
    (Gemini #2) — large refactor, separated from this release. Tracked
    for v0.5.0.
  - **pydantic-settings** env var consolidation (Gemini #3) — valid
    direction, deferred. Tracked for v0.5.0+.
- Open-mode RT follow-ups (d29eab18f423):
  - Marcus's 5 mock tests now partly addressed by the new MockBackend
    test harness; deeper engine-path tests tracked for v0.4.1+.

## [0.3.0] — 2026-04-18

### Documentation
- **`llm/SPEC.md`** — qualified the "OpenAI-compatible provider" claim to
  disclose that the Steward empirical-lookup subagent is unavailable in
  `openai-compat` mode.
- **`llms-full.txt`** — regenerated from updated SPEC.md to keep the
  machine-layer surface synchronized.
- **`docs/guides/configure-backend.md`** — added Steward limitation
  caveat to the OpenAI mode section.
- **`docs/guides/troubleshooting.md`** — added two entries: Steward
  `status: unavailable` in openai-compat mode, and runtime consent
  prompt on first `amatelier roundtable`.
- **`docs/guides/install.md`** — added Environment variables table
  documenting `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`,
  `GEMINI_API_KEY`, `AMATELIER_MODE`, `AMATELIER_WORKSPACE`,
  `AMATELIER_STEWARD_CONSENT`.

### Fixed (Open-mode integration)
- **`complete_with_tools` text accumulation.** Previously only the final
  iteration's text chunks were returned; intermediate-turn narration
  ("Let me check X", etc.) was lost. Now accumulates across all iterations.
- **`complete_with_tools` SDK exception guard.** Wraps
  `client.messages.create()` in try/except. On rate-limit or network
  failure, returns a `Completion` with whatever text accumulated so far
  plus a diagnostic marker, instead of propagating an unhandled exception
  and losing the partial Steward state.
- **OpenAI-compat JSON mode.** Added `json_mode: bool = False` param to
  `LLMBackend.complete()`. `OpenAICompatBackend` translates
  `json_mode=True` → `response_format={"type": "json_object"}`. Fixes
  first-run crash for GPT-4o users on JSON-requiring engine calls (judge
  scoring, skill classification, skill distillation). Claude backends
  accept and ignore the hint (Claude handles JSON instructions inline).
- Four engine call sites now pass `json_mode=True`: `judge_scorer`,
  `classify_concepts`, `backfill_distill`, `roundtable_runner._distill_skills`.

### Security
- **Steward credential denylist.** `read_file()` and `grep()` now refuse
  to read filenames matching credential patterns even when they live
  inside `WORKSPACE_ROOT`. Blocks `.env`, `.env.local/.production/...`
  (templates like `.env.example` remain readable), `id_rsa`/`id_ed25519`,
  `.ssh/`, `.aws/`, `.gnupg/`, `.npmrc`, `.netrc`, `.pypirc`, `*.pem`,
  `*.key`, `*.p12`, `*.pfx`, anything matching `*_token*`/`*_secret*`.
  Defends against the in-sandbox attack chain identified in security
  audit RT `digest-afd96c74180e` (Elena's Grand Insight: "path
  containment and sensitive-file access are orthogonal concerns").
- **Steward result truncation.** `format_result()` caps each Steward
  payload at 4096 chars before injection into the RT transcript /
  digest. Prevents durable persistence of credential material if the
  denylist is bypassed by a renamed secret file.
- **Runtime consent gate.** `amatelier roundtable` now requires
  affirmative consent before the first Steward dispatch. Set
  `AMATELIER_STEWARD_CONSENT=1` in CI / automation. Interactive users
  see a one-time disclosure prompt per process. Implements GDPR
  Article 13 (disclosure before processing event).
- **Fixed `.env.example` typo** — `AMAMATELIER_WORKSPACE` was a no-op
  env var that silently fell through to default workspace resolution.
  Now `AMATELIER_WORKSPACE` as documented.

## [0.2.0] — 2026-04-17

### Added
- **Open mode** — run amatelier without Claude Code. Bring your own API:
  - Direct Anthropic SDK via `ANTHROPIC_API_KEY`
  - Any OpenAI-compatible endpoint (OpenAI, OpenRouter, Groq, Together, local Ollama/vLLM/LM Studio) via `OPENAI_API_KEY` or `OPENROUTER_API_KEY` + configurable `base_url`
- **`src/amatelier/paths.py`** — platformdirs-backed user data directory. Writable state (DB, logs, digests, evolving MEMORY, spark ledger) lives in `~/.local/share/amatelier/` on Linux, `~/Library/Application Support/amatelier/` on macOS, `%LOCALAPPDATA%\amatelier\` on Windows. Override with `AMATELIER_WORKSPACE` env var.
- **`src/amatelier/llm_backend.py`** — unified LLM interface with three backends (`claude-code`, `anthropic-sdk`, `openai-compat`). Auto-detection: `claude` CLI first, then API keys in environment order.
- **`amatelier docs [topic]`** subcommand — prints bundled documentation (Diátaxis tree, ships in wheel).
- **`amatelier config [--json]`** subcommand — diagnoses active backend, credentials seen, and all resolved paths.
- **Bundled docs** — `docs/` tree is force-included in the wheel. Pip users get offline reference; clone users can also serve it via MkDocs.
- **`examples/`** directory (clone-only) — sample briefings: `hello-world.md`, `single-worker.md`, `full-demo.md`. Not shipped in the wheel (the pip-install surface is "my build"; the repo is "my workshop").
- **First-run bootstrap** — `paths.ensure_user_data()` seeds the writable tree on first use, copying agent persona seeds (CLAUDE.md, IDENTITY.md) from the bundled layer and initializing empty state files.

### Changed
- **BREAKING — storage location.** All writes that previously targeted `site-packages/amatelier/roundtable-server/`, `agents/*/MEMORY.md`, `store/ledger.json` now go to `user_data_dir()`. Existing clone users: set `AMATELIER_WORKSPACE=.` to pin state to the working tree (backward-compat).
- **BREAKING — prerequisites for roundtables.** Claude Code CLI is no longer the only path. Set one of: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, or have the `claude` binary on PATH. Atelier auto-detects.
- **Dependencies** — added `platformdirs>=4.0`, `anthropic>=0.40.0`, `openai>=1.0`.
- **Engine refactor** — 16 engine files now use `WRITE_ROOT` (= `user_data_dir()`) for mutable state while keeping `SUITE_ROOT` for bundled reads. Non-invasive: `SUITE_ROOT = Path(__file__).parent.parent` still resolves to bundled assets.
- **`claude_agent.call_claude()` and `judge_scorer._call_sonnet()`** now delegate to `llm_backend` when in open mode; fall back to CLI in `claude-code` mode.
- **`config.json`** gained a top-level `llm` block for mode selection and model mapping.

### Migration notes for 0.1.x users
- Pip users: upgrade to 0.2.0. If you had roundtables in progress, move any files from the old install location to the new `user_data_dir()` — find it via `amatelier config`.
- Clone users: `export AMATELIER_WORKSPACE=.` keeps the old behavior.
- CI / containers: set `AMATELIER_WORKSPACE=/tmp/amatelier` or similar.

## [0.1.0] — Initial release
- Multi-model AI team (Claude Sonnet, Haiku, Gemini Flash) with roundtable discussions
- Spark economy, skill distillation, therapist-led persona evolution
- SQLite-backed live chat layer
- Amatayo Standard repo layout (pip-installable, dual-surface docs)

[Unreleased]: https://github.com/amatayomosley-web/amatelier/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/amatayomosley-web/amatelier/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/amatayomosley-web/amatelier/releases/tag/v0.1.0
