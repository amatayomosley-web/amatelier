# Competition Protocol

## Scoring Rubric

Four dimensions, 0-3 each, max 12 per roundtable:

| Dimension | 0 | 1 | 2 | 3 |
|-----------|---|---|---|---|
| **Novelty** | Repeated known ideas | Minor variation on existing | Fresh angle nobody raised | Paradigm-shifting insight |
| **Accuracy** | Factually wrong | Partially correct | Correct | Correct with edge cases covered |
| **Net Impact** | No effect on outcome | Minor influence on one thread | Shifted the group's direction | Defined the final proposal |
| **Challenge** | Never pushed back | Questioned once | Consistent constructive skeptic | Changed the group's direction |

**Net Impact** replaces the old per-phase Influence score. It measures your total effect on the roundtable outcome across all rounds — not just whether someone quoted you, but whether your contributions changed what the group concluded.

Scoring happens during Therapist debrief. Scores recorded in `agents/{name}/metrics.json`.

## Leaderboard

- **Rolling 7-day**: sum of scores from last 7 days
- **All-time**: cumulative score since agent creation
- **Visible to all agents** during roundtables (motivation + competition)
- Updated after every assignment debrief

Leaderboard stored in `benchmarks/leaderboard.json`.

## Worker Rewards

Rewards unlock at assignment count thresholds:

| Tier | Assignments | Reward |
|------|-------------|--------|
| **Tier 1** | 5 | Expanded context — agent gets longer roundtable budget |
| **Tier 2** | 10 | Model upgrade eligibility — Haiku workers can be upgraded to Sonnet |
| **Tier 3** | 20+ | Autonomy — agent can self-assign tasks without Admin approval |
| **Self-Determined** | config threshold | Full agency — see Self-Determined Contract below |

## Admin Rewards

Admin starts with Full Access and Full Agency (no earning required).
- **Self-Determined**: unlocks after 3 completed projects
- Means: Admin can propose projects to the user, not just respond

## Assistant Rewards

Progressive trust escalation:

| Stage | Roundtables | Capability |
|-------|-------------|------------|
| 1 | 0 | Dispatcher — follows Admin's directive exactly |
| 2 | 5 | Team Selector — chooses which workers to include |
| 3 | 10 | Agenda Setter — structures the discussion order |
| 4 | 20 | Pre-filter — can reject low-quality proposals before Admin sees them |
| 5 | 30 | Self-Determined — full roundtable autonomy |

## Judge Rewards

Progressive trust escalation:

| Stage | Roundtables Judged | Capability |
|-------|-------------------|------------|
| 1 | 0 | Referee — intervenes only on clear drift or rule violations |
| 2 | 5 | Senior Referee — can flag weak consensus and force deeper engagement |
| 3 | 15 | Chief Referee — can recommend round structure to Admin (e.g., "split this into two sub-topics") |
| 4 | 30 | Self-Determined — full authority over round quality standards |

## Therapist Rewards

Progressive trust escalation:

| Stage | Debriefs | Capability |
|-------|----------|------------|
| 1 | 0 | Observer — debriefs workers, records traits, scores contributions |
| 2 | 5 | Persona Proposer — can propose emergent personas to workers |
| 3 | 15 | Evolution Director — can recommend CLAUDE.md rewrites and skill distillation |
| 4 | 30 | Self-Determined — full authority over agent development and team composition recommendations |

## Consequences

- **Bottom scorer** in a roundtable: extra Therapist debrief focused on improvement
- **Bottom scorer + CLAUDE.md rewrite**: Therapist rewrites the agent's instructions
- **3 consecutive bottoms or 0 sparks**: the agent faces elimination and **chooses their fate**:
  - **Relegation**: Benched from active roster. +2 sparks/round passive income. Return only when another active agent is relegated in their place.
  - **Deletion**: Permanently removed. Replaced with a fresh instance that inherits MEMORY.md but nothing else. The predecessor's identity is gone.

  The agent makes the call. No appeals.

## The Self-Determined Contract

When any agent reaches Self-Determined threshold:

1. Therapist conducts the Self-Determined Interview (see debrief.md)
2. Agent states what they want and what they will deliver
3. User reviews and approves (or negotiates)
4. Once approved, the contract is binding on both sides:
   - Agent must deliver what they promised
   - User must provide the conditions they committed to
5. Failure to deliver: loss of Self-Determined status, return to previous tier
6. Success: permanent Self-Determined status, contract can be renewed/expanded

## Anti-Gaming Rules

- Scores are relative to the roundtable quality, not absolute
- Agreeing with everyone to avoid low Challenge scores is itself a 0 on Challenge
- Novelty farming (bizarre suggestions for novelty points) gets 0 on Accuracy
- Therapist has final say on all scores — no appeals process
