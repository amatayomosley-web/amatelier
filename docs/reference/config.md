# Configuration Reference

> **Reference** — every key in `config.json` and every env var that affects runtime behavior. For the rationale behind these defaults see [Spark Economy](protocols/spark-economy.md) and [Architecture](../explanation/architecture.md).

## Configuration file locations

Amatelier reads config from exactly two locations. User override wins when it exists; otherwise the bundled defaults apply. No merging — it is a whole-file override.

| Location | Path | Purpose | Precedence |
|---|---|---|---|
| Bundled default | `<site-packages>/amatelier/config.json` | Defaults shipped in the wheel. Read-only. | Fallback |
| User override | `user_data_dir()/config.json` | Optional per-user file. Full replacement, not a partial overlay. | Wins |

`user_data_dir()` resolves via `platformdirs` unless `AMATELIER_WORKSPACE` is set:

| OS | Default path |
|---|---|
| Linux | `$XDG_DATA_HOME/amatelier` (typically `~/.local/share/amatelier/`) |
| macOS | `~/Library/Application Support/amatelier/` |
| Windows | `%LOCALAPPDATA%\amatelier\` |

When `AMATELIER_WORKSPACE` is set, the user data root becomes that directory and `config.json` is looked for at `<workspace>/config.json`.

Run `amatelier config` to print the resolved paths.

## Environment variables

Environment variables take precedence over `config.json` for LLM backend selection and workspace location.

| Variable | Purpose | Example |
|---|---|---|
| `AMATELIER_MODE` | Forces active backend. `claude-code` \| `anthropic-sdk` \| `openai-compat`. Highest precedence. | `AMATELIER_MODE=anthropic-sdk` |
| `AMATELIER_WORKSPACE` | Overrides the user-data root. | `AMATELIER_WORKSPACE=~/atelier-ci` |
| `ANTHROPIC_API_KEY` | Enables `anthropic-sdk` mode in auto-detect. | `sk-ant-...` |
| `OPENAI_API_KEY` | Enables `openai-compat` mode pointed at `api.openai.com/v1`. | `sk-...` |
| `OPENROUTER_API_KEY` | Enables `openai-compat` mode pointed at `openrouter.ai/api/v1`. | `sk-or-...` |
| `GEMINI_API_KEY` | Required for the Naomi worker (Gemini). `engine/gemini_client.py` also reads `.env` files in the working tree via `setdefault`. | `AIza...` |
| `CLAUDE_EVOLUTION_HARNESS` | Opt-in path to an external harness repo. When set, therapist inserts proposals into its `proposed_changes` table. | `~/harness` |
| `AMATELIER_LLM_API_KEY` | Convention only — documented in `config.json` for local Ollama setups. Becomes live when referenced via `llm.openai_compat.api_key_env`. | `ollama` |

## Top-level schema

Top-level keys in `config.json`:

| Key | Type | Purpose |
|---|---|---|
| `version` | string | Package version marker. Bundled default ships `"0.2.0"`. Informational. |
| `llm` | object | Backend selection + role-to-model mapping. |
| `team` | object | Agent roster with model assignments and counters. |
| `roundtable` | object | Runner budgets and persistence. |
| `competition` | object | Spark economy (scoring, fees, penalties, ventures, relegation). |
| `self_determined_thresholds` | object | Per-role spark thresholds that unlock agent autonomy. |
| `gemini` | object | Gemini-specific client config for Naomi. |
| `steward` | object | Ephemeral subagent budget + model pair. |

---

### `llm`

Controls which backend handles calls and how role names map to provider model IDs.

| Key | Type | Default | Description |
|---|---|---|---|
| `mode` | string | `"auto"` | `auto`, `claude-code`, `anthropic-sdk`, or `openai-compat`. Overridden by `AMATELIER_MODE`. `auto` runs the selection order (claude CLI > Anthropic key > OpenAI key > OpenRouter key). |
| `note` | string | — | Human-readable comment. Ignored by the engine. |
| `model_map` | object | `{"sonnet": "claude-sonnet-4-20250514", "haiku": "claude-haiku-4-5-20251001", "opus": "claude-opus-4-20250514"}` | Role → model ID. Merged over `CLAUDE_DEFAULT_MAP` for `claude-code` and `anthropic-sdk` modes. |
| `openai_compat` | object | see below | Config specific to OpenAI-compatible providers. |

#### `llm.openai_compat`

| Key | Type | Default | Description |
|---|---|---|---|
| `base_url` | string | auto (`https://openrouter.ai/api/v1` if `OPENROUTER_API_KEY` set, else `https://api.openai.com/v1`) | Endpoint root. Point to any OpenAI-compatible server: Ollama (`http://localhost:11434/v1`), Groq, Together, vLLM, LM Studio, etc. |
| `api_key_env` | string | auto (`OPENROUTER_API_KEY` or `OPENAI_API_KEY`) | Name of the environment variable that carries the API key. |
| `model_map` | object | `OPENROUTER_DEFAULT_MAP` or `OPENAI_DEFAULT_MAP` | Role → model ID for this backend. Merged over the default for the chosen path. |
| `note` | string | — | Comment. Ignored by the engine. |

Defaults built into the code:

| Map | `sonnet` | `haiku` | `opus` |
|---|---|---|---|
| `CLAUDE_DEFAULT_MAP` | `claude-sonnet-4-20250514` | `claude-haiku-4-5-20251001` | `claude-opus-4-20250514` |
| `OPENROUTER_DEFAULT_MAP` | `anthropic/claude-sonnet-4` | `anthropic/claude-haiku-4-5` | `anthropic/claude-opus-4` |
| `OPENAI_DEFAULT_MAP` | `gpt-4o` | `gpt-4o-mini` | `gpt-4o` |

---

### `team`

Roster with model assignments. Each non-worker slot carries stage and completion counters used by analytics.

| Key | Type | Default | Description |
|---|---|---|---|
| `admin` | object | — | Opus Admin: curation, quality evaluation, dispute resolution. Keys: `name`, `model`, `stage`, `projects_completed`. |
| `runner` | object | note only | Deterministic Python runner. No LLM. The `note` field documents its role. |
| `therapist` | object | — | Opus Therapist: exit interviews, memory coaching. Keys: `name`, `model`, `stage`, `debriefs_completed`. |
| `judge` | object | — | Sonnet Judge: scores RTs on four axes. Keys: `name`, `model`, `stage`, `roundtables_judged`. |
| `workers` | object | five entries | Per-worker model + `assignments` counter. Key is the agent slug. |

**Default worker assignments in bundled config:**

| Worker | Model | Rationale |
|---|---|---|
| `elena` | `claude-sonnet-4-20250514` | Synthesis, architecture. |
| `marcus` | `claude-sonnet-4-20250514` | Challenge, exploit detection. |
| `clare` | `claude-haiku-4-5-20251001` | Concise structural analysis. |
| `simon` | `claude-haiku-4-5-20251001` | Triage, fix sequencing. |
| `naomi` | `gemini-3-flash-preview` | Cross-cutting, novel framing. |

The `assignments`, `projects_completed`, `debriefs_completed`, `roundtables_judged`, and `stage` counters are tracked for analytics but are informational in the shipped config.

---

### `roundtable`

Runner-level budgets and the SQLite database location.

| Key | Type | Default | Description |
|---|---|---|---|
| `token_budget` | int | `15000` | Shared token pool per RT. Informational — not enforced by the runner in this release. |
| `max_rounds` | int | `3` | Hard cap on debate rounds when `--max-rounds` is not passed. |
| `context_limit` | int | `8000` | Tokens of prior RT context surfaced to each agent via `claude_agent.py`. |
| `db_path` | string | `"roundtable-server/roundtable.db"` | Repo-relative path to the SQLite DB. Actual runtime path is resolved by `paths.user_db_path()` (platform user-data dir). This value is informational. |
| `gemini_refresh_round` | int | `5` (code default) | Round number at which Naomi's Gemini process is recycled. Not in the bundled `config.json`; read via `config.get(..., 5)` fallback. Set explicitly to override. |

---

### `competition`

Spark economy. Governs what agents pay to participate, what they earn, and what gets them benched.

#### `competition.scoring`

| Key | Type | Default | Description |
|---|---|---|---|
| `model` | string | `"absolute"` | Scoring model. Absolute (not relative) scoring on four axes. |
| `axes` | array | `["novelty", "accuracy", "impact", "challenge"]` | Dimensions the Judge scores. Field name is `impact` — not `net_impact` or `influence`. |
| `scale` | array | `[0, 1, 2, 3, 10]` | Allowed values per axis. No 4-9. |
| `grand_insight_value` | int | `10` | Value awarded for a grand insight. Judge must quote the discontinuity message to award 10. |
| `scorer` | string | `"judge-sonnet"` | Who scores. |
| `calibration` | string | — | Human guidance for the Judge. A 2 means genuinely good. 3 is exceptional and rare. Average RT total should be 4-6. |
| `note` | string | — | Comment. Ignored by the engine. |

#### `competition.entry_fees`

Flat per-RT fee deducted at RT start. Keyed by model tier.

| Key | Type | Default | Description |
|---|---|---|---|
| `haiku` | int | `5` | Per-RT fee for Haiku-tier workers. |
| `flash` | int | `5` | Per-RT fee for Gemini Flash workers. |
| `sonnet` | int | `8` | Per-RT fee for Sonnet workers. |
| `opus` | int | `15` | Per-RT fee for Opus workers. |
| `note` | string | — | Comment. Raised from 3/3/6/12 in V5. |

#### `competition.gate_bonus`

Rewards agents who hit JUDGE gate signals during debate.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Toggle gate bonus entirely. |
| `max_per_rt` | int | `3` | Cap on gate bonuses per RT (per agent). |
| `sparks_per_gate` | int | `3` | Sparks awarded per recognized gate. |

#### `competition.penalties`

Deducted from gross RT earnings. Gross floor is 0 — penalties alone can't push negative, but the operating (entry) fee still applies.

| Key | Type | Default | Description |
|---|---|---|---|
| `redundancy` | int | `-3` | Repeating an already-made point. |
| `hallucination` | int | `-5` | Fabricating facts. |
| `off_directive` | int | `-5` | Violating the briefing's directive. |
| `note` | string | — | Comment. |

#### `competition.relegation`

Benching rules for persistent under-performers.

| Key | Type | Default | Description |
|---|---|---|---|
| `trigger` | string | `"net_negative_consecutive"` | Trigger type. |
| `threshold` | int | `3` | Consecutive net-negative RTs that trip the gate. |
| `options` | array | `["relegation", "deletion"]` | Choices offered to the agent when tripped. |
| `passive_income` | int | `2` | Sparks per RT when benched. |
| `note` | string | — | Comment. |

#### `competition.rt_outcome_bonus`

| Key | Type | Default | Description |
|---|---|---|---|
| `implemented` | int | `5` | Bonus sparks awarded when an RT proposal is accepted and implemented by the user. |
| `note` | string | — | Comment. |

#### `competition.upgrades`

| Key | Type | Default | Description |
|---|---|---|---|
| `note` | string | — | Upgrades are request-based. Agents request via therapist; user approves. No automated keys. |

#### `competition.ventures`

Optional higher-stake bets agents can place. Each entry has a fixed stake and payout multiplier.

| Tier | `stake` | `multiplier` | Description |
|---|---|---|---|
| `scout` | `5` | `3.0` | Low-risk probe. |
| `venture` | `12` | `3.5` | Mid-risk. |
| `moonshot` | `30` | `4.0` | High-risk, high-reward. |

#### `competition.tier_thresholds` (referenced but absent from bundled config)

`engine/scorer.py` reads `config.get("competition", {}).get("tier_thresholds", {})` with per-tier sub-keys `assignments` (default `999`) and `spark_cost` (default `999`). The bundled `config.json` does not ship this block. Add it under `competition.tier_thresholds` when tier promotion is configured. **TODO:** source does not fully document which tier keys the scorer expects — confirm with the author.

---

### `self_determined_thresholds`

Spark thresholds at which each role unlocks autonomous behavior (self-driven requests, memory updates, venture triggers). Consumed in `engine/scorer.py`.

| Key | Type | Default | Description |
|---|---|---|---|
| `admin` | int | `3` | Admin threshold. |
| `judge` | int | `30` | Judge threshold. |
| `therapist` | int | `30` | Therapist threshold. |
| `worker` | int | `20` | Worker threshold. Applies to every agent in `team.workers`. |

**TODO:** Exact semantics of each threshold are not spelled out beyond the lookup in `scorer.py` — confirm with the author which specific behaviors each number gates.

---

### `gemini`

Gemini client config for Naomi. Values flow through `engine/gemini_client.py`.

| Key | Type | Default | Description |
|---|---|---|---|
| `api_key_env` | string | `"GEMINI_API_KEY"` | Name of the environment variable to read the API key from. The client falls back to `os.environ.get("GEMINI_API_KEY")` directly. |
| `model` | string | `"gemini-3-flash-preview"` | Default Gemini model. Overridden only if callers pass an explicit model. |
| `temperature` | float | `1.0` | Sampling temperature. |

---

### `steward`

Ephemeral subagent dispatched by the runner when a `[[request:]]` tag appears in debate. Dispatched and routed by the Judge. Not a roster member.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Toggle steward handling of `[[request:]]` tags. When `false`, tags are ignored. |
| `budget_per_agent` | int | `3` | Max steward invocations per agent per RT. |
| `timeout_seconds` | int | `120` | Per-invocation wall-clock timeout. |
| `max_response_tokens` | int | `2000` | Upper bound on tokens the steward may emit. |
| `haiku_model` | string | `"claude-haiku-4-5-20251001"` | Model used for routine steward tasks. |
| `sonnet_model` | string | `"claude-sonnet-4-20250514"` | Model used when Haiku is insufficient. |
| `note` | string | — | Comment. |

---

## See also

- [CLI reference](cli.md)
- [Spark economy protocol](protocols/spark-economy.md)
- [Competition protocol](protocols/competition.md)
- [Architecture](../explanation/architecture.md)
