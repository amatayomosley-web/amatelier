# Example session — Self-host AI vs hosted APIs

A real Amatelier roundtable, captured end-to-end. Five agents (four workers + the Judge), two rounds, one GATE awarded, fully converged.

## Topic

> Self-host AI vs use Claude/OpenAI APIs — decision tree for a B2B SaaS founder in 2026

Briefing in this directory: [`briefing.md`](briefing.md).

## Headline stats

| | |
|---|---|
| Roundtable ID | `e8d2aa8c7cf8` |
| Mode | `claude-code` (used the operator's Claude Code session — zero API spend) |
| Workers | elena · marcus · clare · simon (Naomi skipped — no `GEMINI_API_KEY`) |
| Rounds | 2 |
| Total messages | 54 (23 substantive + 31 runner phase markers) |
| Judge interventions | 3 |
| **Real GATEs awarded** | **1** (marcus, +3 sparks, for the fine-tuning moat reframe) |
| Converged | yes |
| Skills distilled | 15 candidates |
| Wall time | ~30 minutes |

## Reproduce

```bash
pip install amatelier
amatelier roundtable \
  --topic "Self-host AI vs use Claude/OpenAI APIs — decision tree for a B2B SaaS founder in 2026" \
  --briefing examples/briefings/self-host-vs-api.md \
  --max-rounds 2 \
  --budget 1 \
  --skip-naomi \
  --summary
```

Or grab the briefing from the repo and drop your own topic.

## What the screenshots show

### [`screenshots/01-header-and-opening.svg`](screenshots/01-header-and-opening.svg)

The live watcher UI at the start of Round 1. Blue header panel with RT ID, topic, and live counters. Then Round 1's rule, then the first four worker messages — Clare opens with the structural take, Elena synthesizes, Simon brings triage, Marcus challenges.

Each agent has a stable color:

- **clare** — magenta (structural)
- **elena** — cyan (synthesis)
- **simon** — yellow (triage)
- **marcus** — red (challenge)
- **judge** — bold yellow (moderator)

### [`screenshots/02-gate.svg`](screenshots/02-gate.svg) · ★ GATE moment

This is the one that matters — the Judge awarded Marcus a GATE mid-debate for what the Judge called:

> "His fine-tuning moat reframe (Gate 0C) directly fulfilled the briefing's mandatory 'red flag' requirement that Elena's draft omitted, and shifted the flip point from cost-based to strategic — the argument that fine-tuning GPT-4 is a configuration while fine-tuned Llama weights are a defensible asset changes the self-host calculus at lower volume than Gate 2 economics suggest."

Bordered yellow panel, star icon, Marcus's color, timestamp. This is the visual signature of Amatelier's scoring mechanism working live — a specific message flagged as load-bearing, +3 sparks to Marcus on the spot.

### [`screenshots/03-round-transition.svg`](screenshots/03-round-transition.svg)

Round 2 opens. Blue horizontal rule. Clare immediately pushes back on the sequencing, Elena converges on a Gate 0C artifact, Simon notes Marcus and Clare have already resolved the tension without realizing it.

### [`screenshots/04-session-summary.svg`](screenshots/04-session-summary.svg)

Final summary panel: per-agent message counts sorted by contribution, duration, GATE count. Auto-renders on RT close.

## Transcript and digest

- [`transcript.md`](transcript.md) — full 54-message markdown transcript with round headers and per-message byline
- [`digest.json`](digest.json) — structured digest (scores, contributions, convergence reason, GATE reasoning, distilled skills, therapist session notes)
- [`latest-result.md`](latest-result.md) — one-line summary

## Highlights from the final positions

Agents converged on a **three-gate decision tree**, not a binary:

- **Gate 0A** — scale / call-volume check (flips at ~X calls/day)
- **Gate 0C** — ownable weights as moat (the Marcus reframe — the GATE-worthy move)
- **Gate 1** — compliance / regulatory (EU AI Act, data residency — flagged as needing Steward grounding; wasn't injected this run)
- **Gate 2** — unit economics
- **Gate 3** — execution capability

Key argument in the final positions:

> **marcus:** "Clare's moat rebuttal is mostly right but cuts too hard. The moat argument *does* add something Gate 3 alone doesn't capture: the strategic lock-in asymmetry. Even a team with 2 MLOps engineers who fine-tune Llama weights builds a strategic asset that a GPT-4 fine-tune doesn't produce — the Llama derivative is ownable and portable; the GPT-4 fine-tune is configuration trapped in OpenAI's stack."

> **elena:** "Simon's synthesis on Gate 0C is correct and closes the Marcus/Clare tension. The artifact should read: 'If competitive edge lives in specialized model behavior → Gate 0C fires, self-host required, Gates 2/3 become feasibility checks not decision gates.'"

## Scoring

The Judge scored each worker on novelty, accuracy, impact, challenge (each 0–3, or 10 for a grand insight). Totals for this RT:

| Agent | Novelty | Accuracy | Impact | Challenge | Total |
|---|---|---|---|---|---|
| marcus | 2 | **3** | 2 | 2 | **9** (+3 GATE bonus) |
| elena | 2 | 2 | 2 | 2 | 8 |
| clare | 2 | 2 | 2 | 1 | 7 |
| simon | 2 | 1 | 2 | 1 | 6 |

Marcus earned the only 3 this RT (accuracy on the moat reframe) plus the GATE bonus.

## What's intentionally not here

- **No API calls cost accounting** — this RT ran in claude-code mode (operator's Claude Code session). Cost = $0.
- **No Naomi contributions** — `GEMINI_API_KEY` wasn't set; Naomi skipped via `--skip-naomi`. The Judge flagged "Naomi's regulatory grounding is absent" as a known gap.
- **No Steward grounding** — briefing didn't register files; Steward inactive. EU AI Act / data residency claims remain estimates rather than grounded facts.

All three are addressable by configuring the mode/keys differently — see [`docs/guides/configure-backend.md`](../../../docs/guides/configure-backend.md).

## Generating your own session artifacts

If you want to capture screenshots + transcript + digest from your own roundtables for sharing:

```bash
# After a roundtable finishes, find its ID via:
amatelier config --json | python -c "import json, sys, sqlite3; p=json.load(sys.stdin)['paths']['user_db_path']; conn=sqlite3.connect(p); print([r[0] for r in conn.execute('SELECT id FROM roundtables ORDER BY created_at DESC LIMIT 5')])"

# Then:
python scripts/render_session.py --rt <ID> --out examples/sessions/<your-slug>/
```

The script reads from `user_data_dir`, generates the four SVGs above, writes the transcript and copies the digest. Deterministic — same RT in, same bytes out.
