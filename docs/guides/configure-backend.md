# Configure a backend

> **Guide** — pick one LLM backend and wire it up. Amatelier auto-detects in this order: `claude` binary on `PATH` → `ANTHROPIC_API_KEY` → `OPENAI_API_KEY` → `OPENROUTER_API_KEY`. An explicit `AMATELIER_MODE` env var overrides auto-detection.

Verify the current state at any time:

```bash
amatelier config
```

The output shows which backends are available, which credentials are visible, the active mode, and all resolved paths.

## Claude Code mode

**Prerequisites.** The `claude` CLI installed and authenticated. Check with `claude --version`.

**Setup.** Nothing else — if the binary is on `PATH`, amatelier picks this mode first.

**Verify.**

```bash
amatelier config
```

Expected:

```text
  active mode: claude-code
  [OK] claude-code    (claude binary on PATH)
```

**Caveat.** This mode shells out to the Claude Code CLI (`claude -p ... --model sonnet --append-system-prompt ...`). It uses your Claude Code subscription. Costs are zero at the amatelier layer.

## Anthropic SDK mode

**Prerequisites.** An API key from [console.anthropic.com](https://console.anthropic.com). Billing enabled on the account.

**Setup.**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

PowerShell:

```powershell
$Env:ANTHROPIC_API_KEY = "sk-ant-..."
```

**Verify.**

```bash
amatelier config
```

Expected:

```text
  active mode: anthropic-sdk
  [OK] anthropic-sdk  (ANTHROPIC_API_KEY env var)
```

**Model map.** Defaults route to `claude-sonnet-4-20250514` (sonnet), `claude-haiku-4-5-20251001` (haiku), and `claude-opus-4-20250514` (opus). Override via `llm.model_map` in `config.json`.

**Caveat.** The `anthropic` package must be installed. It ships as a dependency — if you see `anthropic SDK not installed`, run `pip install anthropic`.

## OpenAI mode

**Prerequisites.** An API key from [platform.openai.com](https://platform.openai.com/api-keys).

**Setup.**

```bash
export OPENAI_API_KEY=sk-...
```

**Verify.**

```bash
amatelier config
```

Expected `active mode: openai-compat` and the `OPENAI_API_KEY` row marked `[OK]`.

**Model map.** Defaults route through `OPENAI_DEFAULT_MAP` in `src/amatelier/llm_backend.py`:

| Role | Default model |
|------|---------------|
| sonnet | `gpt-4o` |
| haiku | `gpt-4o-mini` |
| opus | `gpt-4o` |

Override per backend via `llm.openai_compat.model_map` in `config.json`.

**Caveat.** The engine is written against Anthropic-style role names. OpenAI models have different strengths — expect scoring calibration to drift. Re-tune your briefings if you rely on Sonnet-specific behavior.

## OpenRouter mode

**Prerequisites.** An API key from [openrouter.ai](https://openrouter.ai/keys).

**Setup.**

```bash
export OPENROUTER_API_KEY=sk-or-...
```

When both `OPENAI_API_KEY` and `OPENROUTER_API_KEY` are set, amatelier prefers OpenRouter for the `openai-compat` backend.

**Verify.**

```bash
amatelier config
```

**Model map.** Defaults route back to Anthropic models through OpenRouter's catalog:

| Role | Default model |
|------|---------------|
| sonnet | `anthropic/claude-sonnet-4` |
| haiku | `anthropic/claude-haiku-4-5` |
| opus | `anthropic/claude-opus-4` |

**Caveat.** OpenRouter exposes 100+ models under one key. Swap model IDs in `config.json → llm.openai_compat.model_map` to route to GPT, Gemini, DeepSeek, Llama, or anything else in the catalog.

## Local Ollama mode

**Prerequisites.** [Ollama](https://ollama.ai) installed and running. One pulled model, e.g. `ollama pull llama3.1`.

**Setup.** Edit `config.json` (either the bundled default or a user override at `<user_data_dir>/config.json`):

```json
{
  "llm": {
    "mode": "openai-compat",
    "openai_compat": {
      "base_url": "http://localhost:11434/v1",
      "api_key_env": "AMATELIER_LLM_API_KEY",
      "model_map": {
        "sonnet": "llama3.1",
        "haiku": "llama3.1",
        "opus": "llama3.1"
      }
    }
  }
}
```

Set a non-empty placeholder API key (the OpenAI SDK rejects empty strings even for local servers):

```bash
export AMATELIER_LLM_API_KEY=ollama
```

**Verify.**

```bash
amatelier config
```

**Caveat.** Local models run slower and score lower on the Judge's novelty/challenge axes. Lower your `--budget` and `--max-rounds` while you calibrate.

## Gemini (Naomi)

Naomi is the cross-model worker. She uses Google's Gemini SDK, separate from the three main backends.

**Prerequisites.** An API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey). The free tier is sufficient for most usage.

**Setup.**

```bash
export GEMINI_API_KEY=...
```

Amatelier also loads `GEMINI_API_KEY` from `.env` files next to the package or at the workspace root, so you can keep the key out of your shell profile.

**Skip Naomi entirely.** Pass `--skip-naomi` to `amatelier roundtable` to omit her from the worker roster.

**Caveat.** Naomi is rate-limited to one call every 5 seconds inside the engine's `gemini_client`. Previews of preview-tier Gemini models apply tight quotas. Check `<user_data_dir>/roundtable-server/logs/gemini_errors.log` if Naomi goes silent.

## Force a specific mode

Bypass auto-detection with an environment variable:

```bash
export AMATELIER_MODE=anthropic-sdk      # or claude-code, or openai-compat
```

This is useful when multiple credentials are set and you want to pin a mode for a session. `amatelier config` shows the override in the `explicit override:` line.

## Diagnose with `amatelier config`

The diagnostic prints four blocks: active mode, available backends, credentials seen in the environment, and resolved paths. Use the `--json` flag to produce machine-readable output for scripting:

```bash
amatelier config --json
```

If `active mode` is `none`, no backend is configured — follow one of the sections above.
