# Your first run with Amatelier

> **Tutorial** — follow every step in order. By the end you will have produced a digest file from a working roundtable and know where to find it. If you already know the tool and want task-specific instructions, see the [guides](../guides/install.md).

A roundtable is one debate cycle. Ten persona agents (workers, a Judge, a Therapist, and Admin) exchange turns in a SQLite-backed chat room on a topic you define. The runner scores the turns, writes a digest, and exits. That is what you are going to produce.

## Prerequisites

- Python 3.10 or newer
- A terminal
- One LLM credential (covered in Step 2)

## Step 1 — Install

Install the package from PyPI:

```bash
pip install amatelier
```

Confirm the CLI is on your `PATH`:

```bash
amatelier --version
```

Expected output:

```text
0.3.0
```

If you see `command not found`, read the [troubleshooting guide](../guides/troubleshooting.md#command-not-found-amatelier).

## Step 2 — Pick a backend

Amatelier auto-detects three backends. Run the diagnostic:

```bash
amatelier config
```

Expected output (before you set any credentials):

```text
amatelier 0.3.0

LLM backend
  active mode: none

Available backends:
  [  ] claude-code    (claude binary on PATH)
  [  ] anthropic-sdk  (ANTHROPIC_API_KEY env var)
  [  ] openai-compat  (OPENAI_API_KEY or OPENROUTER_API_KEY env var)

Credentials seen in environment:
  [  ] CLAUDE_ON_PATH
  [  ] ANTHROPIC_API_KEY
  [  ] OPENAI_API_KEY
  [  ] OPENROUTER_API_KEY
  [  ] GEMINI_API_KEY
...
!! No backend available. Set up one of:
     - Install Claude Code (https://claude.com/claude-code)
     - export ANTHROPIC_API_KEY=... (https://console.anthropic.com)
     - export OPENAI_API_KEY=... (https://platform.openai.com)
     - export OPENROUTER_API_KEY=... (https://openrouter.ai)
```

Set **one** credential. For this tutorial use the Anthropic SDK path — it is the shortest route:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

On Windows PowerShell:

```powershell
$Env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Optionally enable Naomi (the Gemini-powered cross-model worker):

```bash
export GEMINI_API_KEY=...
```

Run `amatelier config` again. Expected:

```text
LLM backend
  active mode: anthropic-sdk

Available backends:
  [  ] claude-code    (claude binary on PATH)
  [OK] anthropic-sdk  (ANTHROPIC_API_KEY env var)
  [  ] openai-compat  (OPENAI_API_KEY or OPENROUTER_API_KEY env var)
```

## Step 3 — Create a briefing

A briefing is a markdown file telling the agents what to debate. The shipped `examples/briefings/hello-world.md` exists in the git repo, not in the pip wheel. Write your own inline.

Create `briefing-hello.md` in your current directory:

```bash
cat > briefing-hello.md <<'EOF'
# Briefing: hello world

## Objective
Exchange one round on "what is the most undervalued idea in open-source software?" Each worker introduces themselves and offers one substantive opinion.

## Constraints
- Messages under 150 words
- One round only
- One opinion per worker

## Success criteria
A digest file with all workers present, Judge scores, and a summary.
EOF
```

On Windows PowerShell, create the file with your editor of choice and paste the same contents.

## Step 4 — Run the roundtable

Execute:

```bash
amatelier roundtable \
  --topic "hello" \
  --briefing briefing-hello.md \
  --max-rounds 1 \
  --budget 1 \
  --summary
```

Expected output (abbreviated — the runner prints per-turn lines):

```text
[runner] topic=hello briefing=briefing-hello.md budget=1
[runner] spawning workers: elena, marcus, clare, simon, naomi
[elena] ...
[marcus] ...
[judge] scoring round 1...
[runner] digest written: <path>/digest-rt-XXXX.json
```

Typical cost on the Anthropic SDK with the default Sonnet+Haiku mix: $0.30 to $0.80.

## Step 5 — Find the digest

The digest landed in your user data directory. Ask the CLI where that is:

```bash
amatelier config
```

Look under `Paths:`:

```text
Paths:
  bundled_assets_dir     ...\site-packages\amatelier
  bundled_docs_dir       ...\site-packages\amatelier\docs
  user_data_dir          C:\Users\<you>\AppData\Local\amatelier
  user_db_path           C:\Users\<you>\AppData\Local\amatelier\roundtable-server\roundtable.db
```

Open the most recent digest file in `user_data_dir/roundtable-server/`:

```bash
ls "$(amatelier config --json | python -c 'import json,sys;print(json.load(sys.stdin)["paths"]["user_data_dir"])')/roundtable-server" | grep digest
```

The digest is JSON. Open it and read the `summary`, `scores`, and `turns` keys. That file is the canonical artifact of a roundtable.

## What you have

- Amatelier installed from PyPI
- An active backend
- One completed roundtable
- A digest file on disk describing the turns, scores, and summary

## See a real example

A fully captured roundtable lives at [`examples/sessions/2026-04-18-self-host-vs-api/`](https://github.com/amatayomosley-web/amatelier/tree/main/examples/sessions/2026-04-18-self-host-vs-api/). Four SVG screenshots, a 54-message transcript, the structured digest, and a README explaining what to look for — including a real Judge GATE awarded to marcus for reframing the self-host decision.

## Next steps

- [Configure a different backend](../guides/configure-backend.md) — OpenAI, OpenRouter, local Ollama
- [Architecture](../explanation/architecture.md) — how the runner, Judge, and Therapist fit together
- [Spark economy](../reference/protocols/spark-economy.md) — how scores turn into agent currency
- [CLI reference](../reference/cli.md) — every flag
