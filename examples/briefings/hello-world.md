# Briefing: hello world

## Objective

Exchange three turns on the topic "what is the most undervalued idea in open-source software?" Each worker should introduce themselves and offer one substantive opinion.

## Context

This is a smoke-test briefing. Success is measured by:
- All workers introduce themselves
- Each worker makes at least one opinion statement
- The Judge scores the round
- A digest file is produced

No external research, no steward lookups, no implementation work. Pure conversation.

## Constraints

- Keep messages short (≤ 150 words each)
- One round only
- Skip deep chains of reasoning — one opinion per worker is enough

## Success criteria

A digest file in `user_data_dir()/roundtable-server/digest-*.json` with:
- All workers present
- Scores assigned by the Judge
- A short summary

## Suggested invocation

```bash
amatelier roundtable \
  --topic "what is the most undervalued idea in open-source software?" \
  --briefing examples/briefings/hello-world.md \
  --max-rounds 1 \
  --budget 1 \
  --summary
```

Typical cost on live API (open mode, mixed Sonnet+Haiku): ~$0.30–$0.80.
On Claude Code: zero (your subscription).
