# empty

A blank-slate template. The admin-side roles are included — any roundtable needs them — but there are zero workers. You build the worker roster yourself.

## What's included

- **admin** — post-RT curation and dispute resolution.
- **judge** — scores each RT on novelty, accuracy, impact, challenge.
- **therapist** — exit interviews and behavior updates.

## What's not

No workers. You add them.

## What this template is for

Users who know exactly what domain-specific roster they want and don't want to edit or delete a roster someone else picked. If you're building a team for a specific domain — legal review, medical literature synthesis, game design critique, ML paper triage — the personas in `curated-five` or `minimal` will just be in your way.

Start here. Then:

```bash
amatelier team new <worker-name>
```

That scaffolds a new worker folder with a CLAUDE.md and IDENTITY.md you fill in. Repeat for each role you want on the team. The runtime will find them and wire them into the RT on the next run.

Pick this if you have a clear idea of your own roster and want a clean slate to build it on.
