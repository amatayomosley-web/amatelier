# Troubleshooting

> **Guide** — symptom → cause → fix. Scan the table first; narrative sections below go deeper.

## Quick reference

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `command not found: amatelier` | CLI script directory not on `PATH` | Run `python -m amatelier --version`; add pip's script dir to `PATH` |
| `ModuleNotFoundError: amatelier` after clone | Installed with `pip install .` instead of editable | Reinstall with `pip install -e ".[dev]"` |
| `BackendUnavailable: No LLM backend available` | No credentials detected, no `claude` CLI | Set one of the four documented credentials |
| `anthropic SDK not installed` | Partial venv; `anthropic` missing | `pip install anthropic` (or reinstall amatelier) |
| `openai SDK not installed` | `openai` missing for openai-compat mode | `pip install openai` |
| `google-genai not installed` / Naomi silent | Gemini deps missing or rate-limited | `pip install google-generativeai`; check `gemini_errors.log` |
| `PermissionError` writing to user data | OS blocked the platformdirs location | Set `AMATELIER_WORKSPACE=/writable/path` |
| Roundtable uses old persona rules after package upgrade | Local seeds diverged from bundled | `amatelier refresh-seeds --force` |
| `claude: command not found` with `AMATELIER_MODE=claude-code` | Claude Code CLI not installed | Unset `AMATELIER_MODE` or install Claude Code |
| `pytest` fails with import errors | `[dev]` extras missing | `pip install -e ".[dev]"` |
| `mkdocs build` warnings or failures | Broken links from doc edits | Run `mkdocs build --strict` and fix each warning |

## `command not found: amatelier`

Pip installed the package but the entry-point script is not on your `PATH`. Test:

```bash
python -m amatelier --version
```

If that prints a version, the script directory is the missing piece. On Linux and macOS, user-site installs go to `~/.local/bin`. Add it:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

On Windows, the script dir is usually `%APPDATA%\Python\PythonXY\Scripts`. Add it to your user `PATH` via System Properties, or launch a fresh shell if you just installed.

Reinstall with `--user` if you need per-user isolation:

```bash
pip install --user amatelier
```

## `ModuleNotFoundError` after editable install

You probably ran `pip install .` from the clone — that installs a snapshot, not a link. Uninstall and redo:

```bash
pip uninstall amatelier
pip install -e ".[dev]"
```

The `-e` flag creates the editable link; `[dev]` adds pytest, ruff, mypy.

## `BackendUnavailable: No LLM backend available`

Raised by `llm_backend.get_backend()` when every auto-detection channel fails. Run:

```bash
amatelier config
```

Look at `Credentials seen in environment:`. Every row says `[  ]`. Pick one:

- **Claude Code** — install the CLI from [claude.com/claude-code](https://claude.com/claude-code)
- **Anthropic SDK** — `export ANTHROPIC_API_KEY=sk-ant-...` from [console.anthropic.com](https://console.anthropic.com)
- **OpenAI** — `export OPENAI_API_KEY=sk-...` from [platform.openai.com](https://platform.openai.com/api-keys)
- **OpenRouter** — `export OPENROUTER_API_KEY=sk-or-...` from [openrouter.ai/keys](https://openrouter.ai/keys)

Rerun `amatelier config` after setting the var. One row should now say `[OK]`.

See the [backend configuration guide](configure-backend.md) for per-backend setup and caveats.

## `anthropic SDK not installed` / `openai SDK not installed`

Raised lazily when the selected backend imports its client library. `anthropic` and `openai` are listed as runtime dependencies and install by default, so this typically means a broken venv or a manual uninstall. Reinstall:

```bash
pip install anthropic openai
```

Or reinstall amatelier itself:

```bash
pip install --force-reinstall amatelier
```

## Naomi silent or Gemini errors

Naomi runs on Google's Gemini SDK with a 5-second minimum call interval (preview tier rate limits are tight). Check the error log in your user data dir:

```bash
amatelier config --json | python -c "import json,sys,pathlib; d=json.load(sys.stdin)['paths']['user_data_dir']; print(pathlib.Path(d) / 'roundtable-server' / 'logs' / 'gemini_errors.log')"
```

Common causes:

- `GEMINI_API_KEY` missing — amatelier checks `os.environ`, a `.env` next to the installed package, and a `.env` at the workspace root
- `google-generativeai` not installed — `pip install google-generativeai`
- Quota exhausted — wait for the window to reset or upgrade the Gemini tier
- Preview model deprecated — update `config.json → gemini.model`

Omit Naomi from a run:

```bash
amatelier roundtable --topic ... --briefing ... --skip-naomi
```

## Permission errors on `user_data_dir`

The bootstrap writes to the OS-default user data directory:

- Linux: `~/.local/share/amatelier/`
- macOS: `~/Library/Application Support/amatelier/`
- Windows: `%LOCALAPPDATA%\amatelier\`

If the user running amatelier lacks write permission (sandboxed CI, hardened containers), redirect:

```bash
export AMATELIER_WORKSPACE=/tmp/amatelier
```

Any absolute writable path works. `amatelier config` shows the resolved value.

## Reset agent rules or start over

Amatelier never clobbers local persona edits on package upgrade. When you do want the latest shipped rules — e.g. after a release that improved the therapist framework — run:

```bash
amatelier refresh-seeds --force
```

Add `--agent <name>` to target a single worker. `--dry-run` previews without writing. Accumulated `MEMORY.md`, `behaviors.json`, and `metrics.json` are preserved; only `CLAUDE.md` and `IDENTITY.md` refresh.

## `claude: command not found` with explicit mode

You set `AMATELIER_MODE=claude-code` but the CLI is absent. Two options:

1. Unset the override and let auto-detection pick another backend:
   ```bash
   unset AMATELIER_MODE
   ```
2. Install Claude Code from [claude.com/claude-code](https://claude.com/claude-code).

## Steward returns `{"status": "unavailable"}` in openai-compat mode

**Symptom.** Agents emit `[[request: ...]]` tags during a debate, but the
runner logs `Steward result injected for {agent} ({status: unavailable})`
instead of the expected empirical lookup. Workers receive a degradation
message instead of code excerpts.

**Cause.** The Steward empirical-lookup subagent is not implemented for
`openai-compat` mode. Tool-use schemas differ across OpenAI-compatible
providers and the cross-provider abstraction was deferred.

**Fix.** Switch to a mode that supports Steward:

```bash
# Option A — use the Anthropic SDK directly
export ANTHROPIC_API_KEY=sk-ant-...
export AMATELIER_MODE=anthropic-sdk

# Option B — use the Claude CLI
# (install from https://claude.com/claude-code)
unset AMATELIER_MODE    # auto-detects claude-code
```

If your RTs genuinely don't need empirical grounding, omit
`[[request: ...]]` tags from your briefings and the degradation message
will not appear.

## Runtime consent prompt on first `amatelier roundtable`

**Symptom.** The CLI blocks with a disclosure text about the Steward
reading files and asks `Proceed? [y/N]:`.

**Cause.** GDPR-aligned consent gate added in v0.2.0. Runs once per
process before the first Steward dispatch.

**Fix.** In interactive use, answer `y` once per session. For CI /
automation, set the env var:

```bash
export AMATELIER_STEWARD_CONSENT=1
```

See `.env.example` for the documented default.

## Tests failing locally

Run the smoke tests to isolate the problem:

```bash
pytest tests/test_smoke.py -v
```

If imports fail, reinstall with dev extras:

```bash
pip install -e ".[dev]"
```

If specific tests fail on a fresh clone, check that your Python version matches the `pyproject.toml` minimum (3.10) and that you are running from the repository root.

## MkDocs build issues

When developing docs, run the strict build to catch broken links:

```bash
mkdocs build --strict
```

Every warning becomes a hard error. Fix each one before committing. Missing `--strict` lets silent link rot through.

## Still stuck

- Search [existing issues](https://github.com/amatayomosley-web/amatelier/issues)
- Open a new issue with the bug report template; include the output of `amatelier config --json`
