# Amatelier examples

Clone-only material — briefings, sample workflows, and remix-ready templates. These are **not** shipped in the pip wheel; they're here for people who clone the repo to study or extend atelier.

## Layout

- `briefings/hello-world.md` — minimal, 1 worker, ~1 minute
- `briefings/single-worker.md` — single-agent focused task
- `briefings/full-demo.md` — all 5 workers, fully exercises the spark economy + distillation

## How to use

1. Install atelier from your clone (or the PyPI release):
   ```bash
   pip install -e .
   # or
   pip install amatelier
   ```

2. Configure a backend (one of):
   - Install Claude Code (nothing else needed)
   - `export ANTHROPIC_API_KEY=<your key>`
   - `export OPENAI_API_KEY=<your key>` (for GPT models)
   - `export OPENROUTER_API_KEY=<your key>` (for 100+ models)
   - `export GEMINI_API_KEY=<your key>` (for Naomi)

3. Run a briefing:
   ```bash
   amatelier roundtable \
     --topic "hello world" \
     --briefing examples/briefings/hello-world.md \
     --max-rounds 1 \
     --budget 1 \
     --summary
   ```

4. Read the digest that lands in your `user_data_dir()` — find it via `amatelier config` under "Paths".

## Writing your own briefing

A briefing is a plain-markdown file. Structure:

```markdown
# Briefing: <short title>

## Objective
What you want the team to deliberate on.

## Context
Background information the workers need to reason well.

## Constraints
Hard limits — what's out of scope, what must hold.

## Success criteria
How you'll know the output is good.

## Notes
Anything else — data sources, references, tone preferences.
```

Copy any example briefing and edit it. The team reads the whole file at the start of round one.

## Why clone-only?

The pip-install surface is "my build" — a self-contained, ready-to-run atelier. The repo is "my workshop" — it includes the examples, tests, CI workflows, and LLM-facing documentation I use while developing atelier. Users who want to just run atelier get the first; users who want to remix or learn from it get the second.

See the [Amatayo Standard](../CLAUDE.md) for the full design philosophy.
