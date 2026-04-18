# Briefing: full demo

## Objective

Exercise every feature of amatelier on a non-trivial topic: 5 workers deliberate, Judge moderates, Steward lookups fire when agents request them, distillation extracts CAPTURE/FIX/DERIVE skills after the round, therapist interviews each worker.

## Topic suggestion

"design the API for a library that lets Python apps send desktop notifications cross-platform, handling macOS, Windows, and Linux differently"

(Feel free to substitute any topic that admits real architectural deliberation — something where the right answer is non-obvious.)

## Context

This is the "did I break something?" test — if this briefing runs clean end-to-end, the full pipeline is healthy:

- Roundtable: 5 workers × 3 rounds × budget 3
- Judge: moderates live, calls GATE on exceptional reframes
- Steward: agents issue `[[request: ...]]` for external lookups
- Distillation: Sonnet pass extracts skills from transcript
- Therapist: 2-turn debrief per worker, persona evolution

## Constraints

- Keep the topic tight enough that 3 rounds converge. Pure research questions blow past budget.
- If running on open mode, watch costs — this briefing can burn $2–5 on Sonnet.

## Suggested invocation

```bash
amatelier roundtable \
  --topic "<your topic>" \
  --briefing examples/briefings/full-demo.md \
  --max-rounds 3 \
  --budget 3 \
  --summary
```

## Success criteria

After the run, check:

```bash
amatelier config      # should show the mode you ran in
ls "$(amatelier config --json | jq -r .paths.user_data_dir)/roundtable-server/"
# Expect: digest-<rt_id>.json, transcript-<rt_id>.txt, rt-<rt_id>/, roundtable.db
```
