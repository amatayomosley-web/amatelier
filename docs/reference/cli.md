# CLI Reference

> **Reference** — every command and flag. For a walkthrough see [Tutorials](../tutorials/first-run.md). For why it is designed this way see [Explanation](../explanation/architecture.md).

## Synopsis

```bash
amatelier COMMAND [ARGS...]
```

The entry point is installed by `pip install amatelier` and dispatches to engine modules (`roundtable`, `therapist`, `analytics`, `watch`) via `runpy`, or handles `docs`, `config`, `refresh-seeds` directly.

## Global options

| Flag | Type | Applies to | Description |
|---|---|---|---|
| `--version` | flag | top-level only | Prints the installed package version and exits with code 0. |
| `--help` / `-h` | flag | top-level only | Prints usage summary to stderr and exits with code 2. |

Subcommands carry their own `--help` surface because they dispatch into engine-level argparse parsers.

## Commands

| Command | Purpose | Example |
|---|---|---|
| `roundtable` | Run one structured debate — all five workers, judged, scored, persisted. | `amatelier roundtable --topic "Auth" --briefing brief.md --summary` |
| `therapist` | Run post-RT exit interviews (memory + behavior updates) against a digest. | `amatelier therapist --digest digest-42.json --agents elena,marcus` |
| `analytics` | Inspect agent growth, spark economy, trends, engagement. Has subcommands. | `amatelier analytics economy` |
| `watch` | Tail the live roundtable chat from SQLite. No API calls. Ctrl-C to exit. | `amatelier watch` |
| `docs` | Print bundled docs to stdout or list topics. | `amatelier docs guides/install` |
| `config` | Diagnose detected LLM backend, credentials, and resolved paths. | `amatelier config --json` |
| `refresh-seeds` | Re-copy persona seeds (`CLAUDE.md`, `IDENTITY.md`) from the wheel into user data. | `amatelier refresh-seeds --agent elena --force` |

---

## `amatelier roundtable`

Runs one full roundtable debate. Dispatches to `src/amatelier/engine/roundtable_runner.py`. Prints the digest JSON to stdout (or a summary if `--summary`). Blocks until complete.

```bash
amatelier roundtable --topic TEXT --briefing PATH [OPTIONS]
```

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--topic` | string | — | yes | Short discussion topic. Recorded in the `roundtables` table and shown in `watch`. |
| `--briefing` | path | — | yes | Path to a markdown briefing file. Read verbatim and passed as shared context to every agent. |
| `--workers` | CSV list | config team | no | Comma-separated worker names. Overrides the full worker roster in `config.team.workers`. Order affects speaker rotation. |
| `--max-rounds` | int | `roundtable.max_rounds` (3) | no | Hard cap on debate rounds. Runner may finish earlier on consensus. |
| `--skip-naomi` | flag | `false` | no | Exclude Naomi (the Gemini worker). Use when `GEMINI_API_KEY` is missing or Gemini quota is exhausted. |
| `--speaker-timeout` | int (seconds) | `200` | no | Per-speaker wall-clock timeout. Shorter values risk truncated replies; longer values tolerate slow providers. |
| `--budget` | int | `3` | no | Extra floor turns per agent on top of the minimum rotation. Higher = more airtime per worker, more tokens spent. |
| `--skip-post` | flag | `false` | no | Stop after scoring and distillation. Skips therapist, store-boost consumption, goal aging, bulletin aging, skill sync. Use when driving these steps manually. |
| `--summary` | flag | `false` | no | Print a human-readable textual summary instead of the raw digest JSON. |

**Exit behavior:** 0 on success, 1 on runner error or keyboard interrupt (database is cut cleanly before exit).

**Example:**

```bash
amatelier roundtable --topic "JWT refresh" --briefing brief-42.md --budget 4 --summary
```

---

## `amatelier therapist`

Runs post-RT interactive exit interviews. One call handles the agent list sequentially. Dispatches to `src/amatelier/engine/therapist.py`.

```bash
amatelier therapist --digest PATH [OPTIONS]
```

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--digest` | path | — | yes | Path to `digest-<rt_id>.json` produced by the runner. Source of record for scores and transcript context. |
| `--agents` | CSV list | all | no | Comma-separated subset of workers to interview. Omit to run all five. |
| `--turns` | int | `2` | no | Exchange turns per interview. Each turn = one therapist prompt + one agent reply. |

**Side effects:** Updates `agents/<name>/MEMORY.md`, `MEMORY.json`, `behaviors.json`, `metrics.json`. May queue proposals into an external evolution harness if `CLAUDE_EVOLUTION_HARNESS` is set (otherwise skipped with a log line).

---

## `amatelier analytics`

Growth analytics across the roster. Dispatches to `src/amatelier/engine/analytics.py`. Subcommand is required; no-argument invocation prints help.

```bash
amatelier analytics SUBCOMMAND [ARGS...]
```

| Subcommand | Purpose |
|---|---|
| `report` | Full growth report for one agent or all. |
| `trends` | Per-dimension trend (↑↓→) over recent RTs. |
| `economy` | Spark economy overview (balances, fees, tier thresholds). |
| `history` | Therapist session history for one agent. |
| `snapshot` | Save a dated leaderboard snapshot and emit as JSON. |
| `update` | Recompute analytics caches for every agent. |
| `engagement` | Cross-agent engagement matrix across all digests. |

### `amatelier analytics report`

| Arg / Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `agent` | positional | — | no (when `--all`) | Agent name. Omit together with `--all` to loop every worker. |
| `--all` | flag | `false` | no | Report for every worker in `team.workers`. |
| `--json` | flag | `false` | no | Emit machine-readable JSON instead of the formatted text. |

### `amatelier analytics trends`

| Arg | Type | Default | Required | Description |
|---|---|---|---|---|
| `agent` | positional | — | yes | Agent name. Prints trend arrow per scoring dimension with current average. |

### `amatelier analytics economy`

No flags. Prints a text summary of balances, fees, and bonuses.

### `amatelier analytics history`

| Arg | Type | Default | Required | Description |
|---|---|---|---|---|
| `agent` | positional | — | yes | Agent name. Emits therapist session history as JSON. |

### `amatelier analytics snapshot`

No flags. Writes a dated snapshot file and echoes it as JSON.

### `amatelier analytics update`

No flags. Recomputes derived metrics for the full roster.

### `amatelier analytics engagement`

No flags. Emits a cross-agent engagement matrix as JSON derived from all persisted digests.

---

## `amatelier watch`

Live tail of the roundtable SQLite chat. No LLM API calls. Connects to the active roundtable (latest row in `roundtables` with `status='open'`). Polls every two seconds. Ctrl-C to exit.

No flags. The DB path is resolved from `src/amatelier/tools/watch_roundtable.py` to `<package>/roundtable-server/roundtable.db`.

| Agent colour | ANSI code |
|---|---|
| Judge | `\033[93m` (yellow) |
| Runner | `\033[90m` (grey) |
| Naomi | `\033[96m` (cyan) |
| Any other worker | `\033[92m` (green) |

**TODO:** The `watch` subcommand in this version reads from a repo-relative path and will not find the DB when installed from a wheel with `AMATELIER_WORKSPACE` set. This is a source-code ambiguity — the path in `watch_roundtable.py` is not routed through `paths.user_db_path()`.

---

## `amatelier docs`

Browser-free view of the bundled Diátaxis tree.

```bash
amatelier docs [TOPIC]
```

| Arg | Type | Default | Required | Description |
|---|---|---|---|---|
| `TOPIC` | string | — | no | Omit to list all topics. Accepts `tier/slug`, `slug`, or `tier slug` forms. Resolution order: `<docs>/TOPIC.md` → `<docs>/TOPIC/index.md` → `<docs>/guides/TOPIC.md` → `<docs>/tutorials/TOPIC.md` → `<docs>/reference/TOPIC.md` → `<docs>/explanation/TOPIC.md`. |

Exits 1 if docs are not bundled or topic is not found. Exits 0 on success.

---

## `amatelier config`

Diagnose backend selection, credentials, and paths.

```bash
amatelier config [--json]
```

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--json` | flag | `false` | no | Emit the full snapshot as JSON instead of the formatted text report. |

**Text output includes:**

- Active mode (`claude-code`, `anthropic-sdk`, `openai-compat`, or `none`).
- Explicit override if `AMATELIER_MODE` is set.
- Availability markers per backend with detection source.
- Credentials presence (boolean) for `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`.
- Resolved paths for bundled assets, bundled docs, user data, SQLite DB, and `AMATELIER_WORKSPACE`.

**Exit code 1** when no backend is available (prints setup guidance). **Exit code 0** otherwise.

---

## `amatelier refresh-seeds`

Re-copy persona seeds (`CLAUDE.md`, `IDENTITY.md`) from the installed wheel into `user_data_dir()/agents/<name>/`. Accumulated state (`MEMORY.md`, `behaviors.json`, `metrics.json`, sessions) is never touched.

```bash
amatelier refresh-seeds [OPTIONS]
```

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `--agent` | string | all | no | Refresh only this agent. Skipped with a warning if no bundled seed exists for the name. |
| `--force` | flag | `false` | no | Overwrite seeds even when the user has modified them. Without this flag, modified seeds are listed as skipped. |
| `--dry-run` | flag | `false` | no | Report what would change without writing. |

Output lists per-file `[WRITE]` and `[SKIP]` lines with reasons. Returns 0 on success, 1 if the bundled agent directory is missing.

---

## Environment variables that affect the CLI

| Variable | Read by | Effect | Example |
|---|---|---|---|
| `AMATELIER_MODE` | `llm_backend.resolve_mode` | Forces backend selection. One of `claude-code`, `anthropic-sdk`, `openai-compat`. Highest precedence, beats config and auto-detect. | `export AMATELIER_MODE=anthropic-sdk` |
| `AMATELIER_WORKSPACE` | `paths.user_data_dir` | Overrides the platform user-data directory. Applies to every command. | `export AMATELIER_WORKSPACE=~/atelier-ci` |
| `ANTHROPIC_API_KEY` | Anthropic SDK backend | Enables `anthropic-sdk` mode in auto-detect. Passed to the SDK client. | `export ANTHROPIC_API_KEY=sk-ant-...` |
| `OPENAI_API_KEY` | OpenAI-compat backend | Enables `openai-compat` mode with `api.openai.com/v1`. | `export OPENAI_API_KEY=sk-...` |
| `OPENROUTER_API_KEY` | OpenAI-compat backend | Enables `openai-compat` mode and routes to `openrouter.ai/api/v1` with Anthropic default model map. | `export OPENROUTER_API_KEY=sk-or-...` |
| `GEMINI_API_KEY` | `engine/gemini_client.py` | Required for Naomi (the Gemini worker). Unset + no `--skip-naomi` = runtime failure mid-RT. | `export GEMINI_API_KEY=...` |
| `CLAUDE_EVOLUTION_HARNESS` | `engine/therapist.py` | Path to an external harness repo. When set, therapist queues proposals into its `proposed_changes` table. When unset, proposals are logged and skipped. | `export CLAUDE_EVOLUTION_HARNESS=~/harness` |
| `AMATELIER_LLM_API_KEY` | `OpenAICompatBackend` (when chosen) | Not a fixed variable — it is a **convention** documented in `config.json` for local Ollama setups. Becomes the active key variable only when set as `llm.openai_compat.api_key_env`. | `export AMATELIER_LLM_API_KEY=ollama` |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | Runtime error (runner failure, missing docs, missing bundled agents, no backend available in `config`). |
| `2` | Usage error (unknown command, no args supplied, `--help` printed). |

Engine subcommands may also exit with their own non-zero codes surfaced through the dispatcher.

## See also

- [Configuration reference](config.md)
- [Install guide](../guides/install.md)
- [Roundtable protocol](protocols/roundtable.md)
- [Spark economy protocol](protocols/spark-economy.md)
