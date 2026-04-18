# Examples

> Tested, copy-runnable examples. Code blocks are extracted and executed by CI (checks/snippets.py). Broken example = red build.

## Conventions

- Each example is self-contained
- Prereqs listed at top of each example
- Expected output shown in a second `text` block
- Language tags on code blocks so extractor routes correctly
- Shell examples use POSIX syntax; Windows users run in bash/WSL or translate env var syntax

## Example: hello world

Prereqs: `pip install amatelier`

```python
from amatelier import hello

print(hello("world"))
```

Expected output:

```text
Hello, world!
```

## Example: anthropic-sdk backend, minimal roundtable

Prereqs: `pip install amatelier` — ANTHROPIC_API_KEY and GEMINI_API_KEY in environment.

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="..."
export AMATELIER_MODE="anthropic-sdk"

amatelier config

amatelier roundtable \
  --topic "what is the most undervalued idea in open-source software?" \
  --briefing examples/briefings/hello-world.md \
  --max-rounds 1 \
  --budget 1 \
  --summary
```

Expected output:

```text
amatelier 0.2.0

LLM backend
  active mode: anthropic-sdk

...

TOPIC: what is the most undervalued idea in open-source software?
ROUNDS: 1
MESSAGES: 12
CONVERGED: ...
JUDGE INTERVENTIONS: ...
BUDGET USAGE:
  elena: spent 0/1
  marcus: spent 0/1
  clare: spent 0/1
  simon: spent 0/1
  naomi: spent 0/1
...
```

Digest lands at `$(amatelier config | grep user_data_dir)/roundtable-server/digest-<rt_id>.json`.

## Example: openrouter backend with custom model map

Prereqs: `pip install amatelier` — OPENROUTER_API_KEY in environment. Custom model map pinning tiers to specific OpenRouter model IDs.

```bash
export OPENROUTER_API_KEY="sk-or-..."

mkdir -p "$(amatelier config --json | python -c 'import sys,json; print(json.load(sys.stdin)["paths"]["user_data_dir"])')"

cat > "$(amatelier config --json | python -c 'import sys,json; print(json.load(sys.stdin)["paths"]["user_data_dir"])')/config.json" << 'EOF'
{
  "llm": {
    "mode": "openai-compat",
    "openai_compat": {
      "base_url": "https://openrouter.ai/api/v1",
      "api_key_env": "OPENROUTER_API_KEY",
      "model_map": {
        "sonnet": "anthropic/claude-sonnet-4",
        "haiku": "anthropic/claude-haiku-4-5",
        "opus": "anthropic/claude-opus-4"
      }
    }
  }
}
EOF

amatelier config --json

amatelier roundtable \
  --topic "pros and cons of monorepos" \
  --briefing examples/briefings/hello-world.md \
  --max-rounds 1 \
  --budget 1 \
  --summary
```

Expected snippet of `amatelier config --json`:

```text
{
  "version": "0.2.0",
  "llm": {
    ...
    "active_mode": "openai-compat",
    "explicit_override": null
  },
  ...
}
```

## Example: local Ollama backend

Prereqs: Ollama installed and running (https://ollama.ai). Pull a model locally first.

```bash
ollama pull llama3.1:70b
ollama pull llama3.1:8b

export AMATELIER_LLM_API_KEY="ollama"
export AMATELIER_MODE="openai-compat"

AMATELIER_USERDATA="$(amatelier config --json | python -c 'import sys,json; print(json.load(sys.stdin)["paths"]["user_data_dir"])')"

cat > "$AMATELIER_USERDATA/config.json" << 'EOF'
{
  "llm": {
    "mode": "openai-compat",
    "openai_compat": {
      "base_url": "http://localhost:11434/v1",
      "api_key_env": "AMATELIER_LLM_API_KEY",
      "model_map": {
        "sonnet": "llama3.1:70b",
        "haiku": "llama3.1:8b",
        "opus": "llama3.1:70b"
      }
    }
  }
}
EOF

amatelier config
amatelier roundtable \
  --topic "what makes a good README" \
  --briefing examples/briefings/hello-world.md \
  --max-rounds 1 \
  --budget 1 \
  --skip-naomi \
  --summary
```

Expected output line confirms openai-compat mode pointing at localhost.

```text
  active mode: openai-compat
  ...
  user_data_dir        ...
```

## Example: custom briefing file

Prereqs: any backend configured. Create a briefing then invoke against it by path.

```bash
cat > /tmp/refactor-briefing.md << 'EOF'
# Briefing: monolith split

## Objective

Decide whether splitting service X from the monolith is worth the coordination overhead.

## Context

- Team size: 8 engineers
- Service X: 4k lines, 3 endpoints, shared DB with monolith
- Deploy cadence: monolith deploys 5x/day, X changes 2x/week

## Constraints

- No downtime migration
- Budget: one quarter

## Success criteria

Each worker proposes a split-or-stay position with at least one load-bearing tradeoff cited from the context above.

## Steward-Registered Files

(none — this briefing uses no external file references)
EOF

amatelier roundtable \
  --topic "split service X from monolith, yes or no" \
  --briefing /tmp/refactor-briefing.md \
  --budget 3 \
  --summary
```

Expected output: digest with 5 workers posting positions; Judge scores; skills distilled.

## Example: skip Naomi, single-worker smoke test

Prereqs: any Claude-compatible backend (claude-code mode or anthropic-sdk mode). No Gemini key required with `--skip-naomi`.

```bash
amatelier roundtable \
  --topic "hello" \
  --briefing examples/briefings/hello-world.md \
  --workers elena \
  --max-rounds 1 \
  --budget 1 \
  --skip-naomi \
  --skip-post \
  --summary
```

Expected output:

```text
...
TOPIC: hello
ROUNDS: 1
MESSAGES: ...
CONTRIBUTIONS:
  elena: ...
  judge: ...
FINAL POSITIONS:
  [elena]: ...
```

`--skip-post` halts after distillation — no therapist run, no store cleanup, no leaderboard update.

## Example: reading the digest in Python

Prereqs: at least one completed roundtable. Locate digest via `amatelier config`.

```python
import json
from pathlib import Path
from amatelier import paths

digest_dir = paths.user_digest_dir()
digests = sorted(digest_dir.glob("digest-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
if not digests:
    raise SystemExit("no digests yet — run: amatelier roundtable --topic ... --briefing ...")

latest = digests[0]
d = json.loads(latest.read_text(encoding="utf-8"))

print(f"rt_id: {d.get('rt_id')}")
print(f"topic: {d.get('topic')}")
print(f"rounds: {d.get('rounds')}")
print(f"converged: {d.get('converged')}")
print(f"contributions: {d.get('contributions')}")
for agent, pos in d.get("final_positions", {}).items():
    print(f"  [{agent}] {pos[:120]}...")
```

Expected output (shape):

```text
rt_id: <hex>
topic: <your topic>
rounds: <int>
converged: True|False
contributions: {'elena': <int>, 'marcus': <int>, ...}
  [elena] ...
  [marcus] ...
  ...
```

## Example: refresh agent seeds after a package upgrade

Prereqs: `pip install --upgrade amatelier`. By default, pip upgrades do NOT touch user-edited persona files in `user_data_dir()/agents/<name>/`. Run `refresh-seeds` to pull shipped updates.

```bash
amatelier refresh-seeds --dry-run

amatelier refresh-seeds --force
```

Expected output of `--dry-run`:

```text
dry run — no files written

Refreshed: 0

Skipped: <N>
  [SKIP] elena/CLAUDE.md (already current)
  [SKIP] marcus/CLAUDE.md (user-modified; use --force to overwrite)
  ...
```

Output of `--force`:

```text
Refreshed: <N>
  [WRITE] marcus/CLAUDE.md
  ...

Note: <M> agent(s) refreshed. Their accumulated MEMORY.md / behaviors.json / metrics.json are untouched — only the persona rules and identity seeds were overwritten.
```

Single-agent form: `amatelier refresh-seeds --agent elena --force`.

## Example: programmatic LLM backend

Prereqs: `pip install amatelier` and one of the supported backends configured. Useful when a calling program needs the backend abstraction but not the full roundtable orchestration.

```python
from amatelier.llm_backend import get_backend, describe_environment

print(describe_environment())

backend = get_backend()

result = backend.complete(
    system="You are a terse code reviewer.",
    prompt="Review: def add(a, b): return a - b",
    model="haiku",
    max_tokens=200,
    timeout=60.0,
)

print(f"backend: {result.backend}")
print(f"model:   {result.model}")
print(f"latency: {result.latency_ms:.0f} ms")
print(f"tokens:  in={result.input_tokens} out={result.output_tokens}")
print(f"text:    {result.text[:400]}")
```

Expected output (shape):

```text
{'claude-code': {'available': ..., 'detected_via': ...}, 'anthropic-sdk': {...}, ...}
backend: anthropic-sdk
model:   claude-haiku-4-5-20251001
latency: <int> ms
tokens:  in=<int> out=<int>
text:    The function subtracts instead of adding...
```

## Example: tail a live roundtable

Prereqs: a roundtable in progress (start one in another terminal with `amatelier roundtable ...`).

```bash
amatelier watch
```

Expected output: streams new chat messages as they land in `user_data_dir()/roundtable-server/roundtable.db`. Zero LLM cost — pure SQLite reads. Shows speaker name, message preview, and Judge interventions in real time. Exit with Ctrl-C.
