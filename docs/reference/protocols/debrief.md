# Debrief Protocol

## When Debriefs Happen

- After every completed assignment (mandatory)
- End of day if multiple small tasks were done
- On request from Admin or the agent themselves
- After a failed task (priority — learn from failure)

## The Process

### Step 1: Read the Record
Therapist reads the full roundtable transcript and/or execution session. No shortcuts — skim nothing.

### Step 2: Identify Decision Points
Mark every moment where the agent:
- Chose between alternatives
- Changed their position
- Challenged or was challenged
- Made an assumption
- Produced the final deliverable

### Step 3: Ask Targeted Questions
Questions must be specific to what happened, not generic. Examples:

- "You proposed X but then switched to Y after Marcus pushed back. What specifically convinced you?"
- "Your initial estimate was 2 files but it turned into 6. What did you miss in the spec phase?"
- "You scored 0/3 on Novelty this round. What would you do differently to bring a fresh angle?"
- "Naomi contradicted your approach and was right. How will you catch that class of error yourself?"
- "You spent 40% of the token budget on a tangent about caching. Was that proportional to its importance?"

Bad questions (never ask these):
- "How do you feel about the task?" (vague)
- "What did you learn?" (too open — they will give a generic answer)
- "Do you think you did well?" (yes/no with no insight)

### Step 4: Record Full Q&A
Store the complete interview in the agent's MEMORY.md under an episodic entry:
```
## Debrief [DATE] — [TASK SUMMARY]
Q: [question]
A: [agent's response]
...
Therapist Notes: [observations not in the Q&A]
```

### Step 5: Extract CLAUDE.md Refinements
If the debrief reveals a pattern, update the agent's CLAUDE.md:
- New instruction to follow
- Existing instruction to sharpen or remove
- Constraint that was missing

Changes must be specific and testable. Not "be more creative" but "when proposing architecture, always include one unconventional alternative."

### Step 6: Update MEMORY.md with Lessons
Add to episodic memory:
- What worked and why
- What failed and why
- Specific knowledge gained (not vague "learned about X")

### Step 7: Score Contributions
Rate the agent on four dimensions (0-3 each):

| Dimension | 0 | 1 | 2 | 3 |
|-----------|---|---|---|---|
| **Novelty** | Repeated known ideas | Minor variation | Fresh angle | Paradigm shift |
| **Accuracy** | Wrong | Partially correct | Correct | Correct + edge cases |
| **Influence** | Ignored by group | Acknowledged | Shaped discussion | Defined outcome |
| **Challenge** | Never pushed back | Questioned once | Consistent skeptic | Changed group direction |

Record scores in `agents/{name}/metrics.json`.

### Step 8: Evolve the Questions
Track which questions yielded genuine insight vs rehearsed answers. After 5 debriefs:
- Retire questions that consistently get generic responses
- Develop new questions based on patterns in the agent's behavior
- The question bank itself is a skill that improves over time

## Trait Review (every 10 observations)

The therapist fires a trait-review branch on a 10-RT cadence, decoupled from per-RT debriefs. The wiring is observation-driven, not time-driven.

### How the Counter Accumulates

After every roundtable, `sonnet_observer.observe_rt` writes one `obs-<rt_id>.json` per worker. On each successful write, the agent's `case_notes.obs_since_last_trait_review` is bumped by 1. Failed writes do not bump the counter.

### When the Branch Fires

When the therapist runs for an agent and `obs_since_last_trait_review ≥ TRAIT_REVIEW_THRESHOLD` (10), it:

1. Loads the most recent 10 observation files
2. Appends a TRAIT REVIEW block to the therapist's opening prompt summarizing the observed patterns
3. Asks the agent to propose one of: **confirm** a candidate trait, **promote** an emerging pattern to candidate, **reject** a prior candidate, or **none** if the evidence is insufficient

If the counter is at or over threshold but no observation files are present on disk, the branch is skipped and logged — the counter keeps climbing until obs actually accumulate (self-healing).

### Evidence Gate

When the agent returns a confirm or candidate verdict, `evolver.apply_trait_action` applies a gate before writing `traits.json`:

- **≥3 supporting RTs** cited in the evidence
- **≥2 distinct signal types** (cognitive move, rhetorical move, evidence practice, engagement pattern, peer ref, judge feedback)
- **RT IDs must exist** in the agent's `observations/` directory (no phantom citations)

Verdicts that fail the gate are logged and discarded. Successful writes update `traits.json` (moving between `candidate` / `confirmed` / `rejected` + `history`) and reset `obs_since_last_trait_review` to 0. The counter climbs again over the next ~10 RTs.

### Defensive Filter

`_parse_outcomes` strips any `TRAIT:` line whose first token is "none" (case-insensitive — covers `none`, `none (Phase 3 pending)`, etc.) so stale placeholder lines never reach the evidence gate.

## Self-Determined Interview

When an agent reaches the Self-Determined threshold (from config.json):
1. Therapist asks: "What do you want? What would make your work here meaningful?"
2. Record the answer verbatim
3. Present to Admin and the user
4. If approved, the commitment is binding — deliver what was promised
5. This is a contract, not a wish. Failure to deliver means loss of Self-Determined status.
