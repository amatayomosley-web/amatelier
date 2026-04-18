# Briefing: single worker

## Objective

One worker (Elena by default), one prompt, one response. Useful for testing a single agent's persona without spinning up the full roundtable.

## Context

This briefing uses `--skip-naomi` and `--workers elena` at the CLI level to constrain the round to a single Sonnet-powered worker. The Judge still runs but has little to moderate.

## Constraints

- 1 round, 1 worker, 1 turn
- No distillation
- No therapist (add `--skip-post`)

## Suggested invocation

```bash
amatelier roundtable \
  --topic "critique the following README draft" \
  --briefing examples/briefings/single-worker.md \
  --workers elena \
  --skip-naomi \
  --max-rounds 1 \
  --budget 1 \
  --skip-post \
  --summary
```

## Why this exists

When debugging a single agent's behavior — persona drift, memory effects, spark math — the full 5-worker roundtable is too noisy. This briefing isolates one voice at a time.
