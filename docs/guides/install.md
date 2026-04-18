# Install

> **Guide** — task-oriented. Pick one of the three paths below. For a guided first-run walkthrough, see the [first-run tutorial](../tutorials/first-run.md).

Amatelier ships two surfaces: a **pip wheel** (self-contained, bundled docs) and a **git clone** (wheel contents plus `examples/`, `tests/`, CI workflows, and LLM-facing docs). Think of the wheel as "the build" and the clone as "the workshop". Example briefings live only in the clone.

## Path 1 — Consumer (pip)

Install from PyPI:

```bash
pip install amatelier
```

Verify:

```bash
amatelier --version
```

Upgrade:

```bash
pip install -U amatelier
```

Uninstall:

```bash
pip uninstall amatelier
```

Pip gives you the CLI, bundled docs accessible via `amatelier docs`, and first-run bootstrap that seeds `user_data_dir` with agent persona files. No example briefings ship in the wheel — write your own, or clone the repo for the stock examples.

## Path 2 — Contributor (editable clone)

Clone and install in editable mode with dev extras:

```bash
git clone https://github.com/amatayomosley-web/amatelier
cd amatelier
pip install -e ".[dev]"
```

Run the tests:

```bash
make test
```

Or directly:

```bash
pytest tests/test_smoke.py -v
```

`-e` makes source edits take effect without reinstalling. `[dev]` adds pytest, ruff, and mypy. You now have `examples/briefings/hello-world.md`, `single-worker.md`, and `full-demo.md` available as ready-to-run scripts.

### Pin runtime state to the working tree

By default, mutable state (databases, digests, ledgers) lives in the OS user-data directory. Clone users often prefer everything in one place:

```bash
export AMATELIER_WORKSPACE=.
```

This pins `user_data_dir()` to the current working directory. Run `amatelier config` to confirm.

## Path 3 — DevContainer (zero setup)

If you have VS Code with the Dev Containers extension or you are working in GitHub Codespaces:

1. Open the repository root
2. VS Code: press `F1`, run **Dev Containers: Reopen in Container**
3. Codespaces: **Code** button → **Codespaces** → **Create codespace on main**

The container spec at `.devcontainer/devcontainer.json` provisions Python, the dev extras, and the CLI in roughly two minutes.

## Verify your install

```bash
amatelier --version
amatelier config
```

Expected: the version string, followed by the backend diagnostic. If `active mode` says `none`, you still need a backend — see [configure a backend](configure-backend.md).

## Environment variables

| Variable | Purpose | Example |
|---|---|---|
| `ANTHROPIC_API_KEY` | Enables `anthropic-sdk` backend | `sk-ant-...` |
| `OPENAI_API_KEY` | Enables `openai-compat` backend against `api.openai.com` | `sk-...` |
| `OPENROUTER_API_KEY` | Enables `openai-compat` backend against OpenRouter (preferred over OpenAI if both set) | `sk-or-...` |
| `GEMINI_API_KEY` | Required for the Gemini Flash worker (Naomi). Skip with `--skip-naomi` if absent | `AIza...` |
| `AMATELIER_MODE` | Force a specific backend. Values: `claude-code`, `anthropic-sdk`, `openai-compat`. If unset, amatelier auto-detects in that order of preference | `anthropic-sdk` |
| `AMATELIER_WORKSPACE` | Override where mutable state (DB, digests, ledger) lives. Defaults to OS user-data dir. Use `.` to pin to the current working tree | `/path/to/project` |
| `AMATELIER_STEWARD_CONSENT` | Pre-approve the consent gate for `amatelier roundtable` in CI / non-interactive contexts. Set to `1`, `yes`, or `true` | `1` |

Set via shell (`export FOO=bar`), a `.env` file at the repo root (see `.env.example`), or your CI secret store.

## Alternatives and caveats

- **Python version.** Amatelier requires Python 3.10 or newer. Check with `python --version`.
- **Virtualenvs.** Install into a project venv if you already run multiple Python projects. `pip install amatelier` works identically inside any standard venv.
- **Windows.** The CLI handles UTF-8 stdout reconfiguration at import time, so the console renders arrows and em-dashes correctly on `cp1252` defaults.
- **Offline docs.** `amatelier docs` prints the bundled Diátaxis tree. No network required.

## Troubleshooting

If install succeeds but `amatelier` is not found, or editable installs fail to import, see the [troubleshooting guide](troubleshooting.md).
