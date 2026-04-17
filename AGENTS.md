# Amatelier — Agent Instructions

Generic instructions for any AI agent or coding assistant working in this repository. (Claude Code, Cursor, Copilot, Aider, Codex, or others.)

## What this project is

A self-evolving multi-model AI team skill for Claude Code

## Layout you need to know

| Path | Purpose |
|---|---|
| `src/amatelier/` | Shipped package — canonical code |
| `tests/` | Mirror of `src/` |
| `examples/first_run/` | Zero-config demo |
| `docs/` | Human-facing documentation |
| `llm/` | Machine-readable documentation (flat, exhaustive) |
| `.github/workflows/` | CI, publish, release, docs |

## Invariants

- **Amatayo Standard compliance.** CI enforces. Any PR that breaks structure will fail.
- **Hand-written sources:** `docs/` (narrative content), `src/`, `CLAUDE.md`, `llm/SPEC.md`, `llm/<domain>.md`.
- **Generated derivatives:** `llm/API.md`, `llm/SCHEMA.md`, `llms.txt`, `llms-full.txt`, `.cursor/rules/*.mdc`, `.github/copilot-instructions.md`. Don't hand-edit these — they are rebuilt by CI and changes will be overwritten.
- **`llm/` is flat** — no subdirectories.
- **Conventional commits** — `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, with `BREAKING CHANGE:` footer for majors.
- **Tests and lint pass before PR** — `make test && make lint`.

## Read before acting

1. `README.md` — surface-level context
2. `docs/explanation/architecture.md` — why the system is shaped this way
3. `llm/SPEC.md` — canonical machine-readable description
4. The specific file you're editing

For deep context in one shot: `curl https://raw.githubusercontent.com/amatayomosley-web/amatelier/main/llms-full.txt`
