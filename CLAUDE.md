# Amatelier — Claude Code Instructions

Instructions for working on this repository inside Claude Code.

## What this project is

A self-evolving multi-model AI team skill for Claude Code

## Repo layout

- `src/amatelier/` — shipped package (the canonical code)
- `tests/` — mirrors `src/` structure
- `examples/first_run/` — zero-config runnable demo
- `docs/` — human documentation (MkDocs, Diataxis tiers)
- `llm/` — LLM-facing documentation (flat, exhaustive, machine-readable)
- `scripts/` — shell and one-off utility scripts
- `.github/workflows/` — CI, publish, release, docs workflows

## Rules

1. **Amatayo Standard.** This repo follows the Amatayo Standard. Structure is enforced by CI.
2. **Dual-docs invariant.** Every change that adds a public symbol, CLI flag, or config key must update `llm/SPEC.md` and the relevant `docs/reference/*` file. The `llm/API.md` and `llm/SCHEMA.md` files are generated — don't hand-edit them.
3. **`llm/` is flat.** Never create subdirectories in `llm/`. Flat is the invariant.
4. **Tests required.** New code requires new tests. `make test` must pass before PR.
5. **Conventional commits.** `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`. Releases are driven by commit history.
6. **No secrets.** `.env.example` documents variables; real values never committed.

## Two-layer paths (critical)

Amatelier is pip-installable; the bundled package must stay read-only at runtime. Two layers exist:

- **Bundled layer** — `src/amatelier/` and any files shipped inside the wheel. This is the canonical source. Runtime code MUST NOT write here.
- **User data layer** — everything returned by `amatelier.paths.user_data_dir()` and its siblings (`user_agent_dir`, `user_db_path`, `user_digest_dir`, `user_briefing_dir`, `user_store_ledger`, `user_novel_concepts`, `user_shared_skills_index`, `user_config_override`). All mutable state goes here.

Rules for AI agents editing this repo:

- Any code that persists state, writes logs, updates ledgers, or mutates agent memory must route through a `paths.user_*()` helper. Do not hard-code paths under `src/amatelier/` for writes.
- Persona seed files (per-agent `CLAUDE.md`, `IDENTITY.md` under `src/amatelier/agents/<name>/`) are bundled. Edits to seeds only affect a user's environment after `amatelier refresh-seeds` or a fresh install.
- Generated files must not be hand-edited: `llm/API.md`, `llm/SCHEMA.md`, `llms.txt`, `llms-full.txt`, `.cursor/rules/*.mdc`, `.github/copilot-instructions.md`. CI regenerates them.

## Three LLM backend modes

All LLM calls must go through `amatelier.llm_backend.get_backend()`. The backend abstraction resolves to one of three modes at runtime:

| Mode | Selected when | Backend class |
|---|---|---|
| `claude-code` | Running inside Claude Code, `claude` binary on PATH | `ClaudeCLIBackend` |
| `anthropic-sdk` | `ANTHROPIC_API_KEY` present, no Claude Code session | `AnthropicSDKBackend` |
| `openai-compat` | `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, or local Ollama | `OpenAICompatBackend` |

Override with `AMATELIER_MODE=claude-code|anthropic-sdk|openai-compat`.

When introducing new LLM calls:

- Call `get_backend()` and use the returned object's interface. Do not shell out to the `claude` CLI directly and do not `import anthropic` at the call site.
- Any new backend capability must be added to the `LLMBackend` Protocol in `src/amatelier/llm_backend.py` and implemented by all three concrete backends.
- Surface new provider env vars in `describe_environment()` so `amatelier config` reports them.

## Tests

- `tests/test_smoke.py` — pytest suite, import/CLI smoke checks, runs in CI
- `tests/test_refresh_seeds.py` — pytest suite, verifies seed materialization, runs in CI
- `tests/test_integration.py` — **standalone script**, exercises live LLM backends, NOT pytest and NOT run in CI. Execute manually when verifying backend changes.

Run the CI-equivalent suites locally:

```bash
pytest tests/test_smoke.py -v
pytest tests/test_refresh_seeds.py -v
```

## Common commands

```bash
make setup        # install package + dev deps
make test         # run test suite
make lint         # ruff + mypy
make demo         # run examples/first_run/
make docs         # build docs site locally
amatelier config          # show active mode, credentials, paths
amatelier refresh-seeds   # rematerialize per-agent seeds in user data dir
```

## When editing docs

Use the `dual-docs-architect` skill. It classifies every write (tutorial / guide / reference / explanation x human / LLM / both) and routes to the correct file.

## When scaffolding new repos

Use the `repo-architect` skill. Don't copy this file by hand — let the skill render it.
