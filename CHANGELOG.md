# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
