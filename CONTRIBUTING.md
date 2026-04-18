# Contributing to Amatelier

Thanks for your interest in improving this project.

## Before you start

1. Search [existing issues](https://github.com/amatayomosley-web/amatelier/issues) to avoid duplicates
2. For significant changes, open an issue first to discuss the approach
3. Read the [Code of Conduct](CODE_OF_CONDUCT.md)

## About this repo

Amatelier follows the **Amatayo Standard v1.0**. In practical terms for contributors:

- **Dual documentation surfaces.** Narrative docs live in `docs/` (MkDocs, Diataxis tiers); machine-readable docs live in `llm/` (flat, exhaustive). Generated derivatives (`llm/API.md`, `llm/SCHEMA.md`, `llms.txt`, `llms-full.txt`, `.cursor/rules/*`, `.github/copilot-instructions.md`) are rebuilt by CI — do not hand-edit.
- **Fire-and-forget agent rules.** AI contributors (Claude Code, Cursor, Copilot, Aider, Codex) read [`CLAUDE.md`](CLAUDE.md) and [`AGENTS.md`](AGENTS.md) for working rules. Changes to those files propagate into per-agent seeds via `amatelier refresh-seeds` (see below).
- **Pip vs clone split.** `pip install amatelier` ships a runnable package with bundled docs; the git clone adds `examples/`, `tests/`, CI, and LLM-facing sources. Runtime state lives under `amatelier.paths.user_data_dir()` — never in `src/amatelier/`.

## Dev setup

```bash
git clone https://github.com/amatayomosley-web/amatelier
cd amatelier
make setup      # installs package + dev deps editable
make test       # runs pytest smoke suite
make lint       # ruff + mypy
make demo       # runs examples/first_run/
```

Or open the repo in a DevContainer / GitHub Codespace — the `.devcontainer/` config handles everything automatically.

## Contributor tools (CLI)

Once installed editably, these commands help verify your changes end-to-end:

```bash
amatelier config          # show active LLM mode, credentials, resolved paths
amatelier docs            # open the bundled documentation
amatelier refresh-seeds   # re-materialize per-agent seeds under user_data_dir
```

Use `refresh-seeds` after editing any file under `src/amatelier/agents/*/CLAUDE.md` or `IDENTITY.md` to confirm your seed changes land correctly in the user data directory.

## Pull request workflow

1. Fork the repo and create a feature branch: `git checkout -b feat/my-thing`
2. Make focused commits using [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat: add new capability`
   - `fix: correct behavior of X`
   - `docs: clarify installation`
   - `BREAKING CHANGE: describe the break`
3. Keep PRs small — one logical change per PR
4. Ensure `make lint && make test` pass locally
5. Open the PR against `main`; fill the PR template

## Testing

Two pytest suites run in CI:

```bash
pytest tests/test_smoke.py -v
pytest tests/test_refresh_seeds.py -v
```

`tests/test_integration.py` is a standalone script (not pytest) that exercises live LLM backends and is **not** run in CI. Execute it manually when verifying backend changes.

## Continuous integration

Three workflows gate every PR:

- **CI** (`.github/workflows/ci.yml`) — ruff lint, mypy type check, pytest smoke suite across Linux / macOS / Windows and Python 3.10 / 3.12 / 3.13
- **Docs** (`.github/workflows/docs.yml`) — `mkdocs build --strict`; any warning fails the build
- **Wheel smoke** (`.github/workflows/wheel-smoke.yml`) — builds the wheel, installs it in a clean env, runs the CLI

All three must pass before merge.

## Code style

- Ruff handles formatting and linting (`make format` to fix)
- Type hints required on public APIs (`mypy --strict`)
- Keep files under 500 lines
- Write tests for new code; aim for at least 80% coverage

## Releases

Releases are fully automated on tag push. Maintainers run:

```bash
git tag v0.2.0
git push --tags
```

CI then publishes to PyPI (via trusted publishing) and creates a signed GitHub Release.

## Enabling branch protection (maintainers)

Once the repo is created, enable these in Settings / Branches / `main`:

- Require pull request reviews (at least 1)
- Require status checks to pass (`test`, `build-check`, `docs`, `wheel-smoke`)
- Require signed commits (recommended)
- Require linear history
- Block force pushes
