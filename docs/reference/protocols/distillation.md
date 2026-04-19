# Distillation Protocol

## Three Modes

### CAPTURE — From Successes
Extract what worked and why. Based on the pattern: when a roundtable or execution succeeds, record the approach.

**Process**:
1. Read the transcript/session record
2. Identify the key decision that led to success
3. Abstract it: strip project-specific details, keep the transferable pattern
4. Write the skill entry

**Trigger**: Truth score >= 0.85 AND task completed successfully.

### FIX — From Failures
Extract what went wrong and how to avoid it. Research shows 28 out of 29 evolved skills came from failures — failure is the primary teacher.

**Process**:
1. Read the transcript/session record
2. Identify the root cause of failure (not symptoms)
3. Write the avoidance pattern: what to check, what to do instead
4. Include the failure signature — how to recognize this situation early

**Trigger**: Truth score < 0.75 OR task failed OR Therapist flags during debrief.

### DERIVE — Merge Existing Skills
Combine two or more existing skills into a stronger pattern. The merged skill covers more ground than either original.

**Process**:
1. Identify two skills that frequently co-occur (both used in same tasks)
2. Find the shared principle underneath both
3. Write a unified skill that subsumes both
4. Mark the originals as "superseded by [new skill ID]"

**Trigger**: Two skills used together in 3+ tasks within 7 days.

## Skill Entry Format

```markdown
# [TITLE]

- **Type**: CAPTURE | FIX | DERIVE
- **Source**: roundtable-[ID] or session-[ID]
- **Context**: When does this apply? (specific conditions)
- **Pattern**: What to do (actionable steps)
- **Anti-pattern**: What NOT to do (if FIX type)
- **When to Apply**: Trigger conditions for loading this skill
- **Confidence**: 0.0-1.0 (starts at 0.6, increases with successful reuse)
- **Uses**: 0 (incremented each time the skill is applied)
```

## Storage

- Agent-specific skills: `agents/{name}/skills/` (not yet shared)
- Shared skills: `shared-skills/entries/` (promoted after validation)

## Promotion to Shared

A skill is promoted from agent-specific to shared when:
1. Used successfully 3+ times by the originating agent, OR
2. Used successfully by 2+ different agents, OR
3. Therapist explicitly promotes it during debrief

On promotion:
- Copy to `shared-skills/entries/`
- Update confidence score based on track record
- Add to the shared skill index

## The Distillation Pipeline

Skill extraction runs inline inside the per-RT Sonnet observer, not as a separate pass. `sonnet_observer.observe_rt` emits CAPTURE / FIX / DERIVE candidates with pre-tagged taxonomy (structural_category, trigger_phase, primary_actor, problem_nature, agent_dynamic) in the same Sonnet call that produces per-agent observations. The runner consumes `obs_summary["skills_observed"]` and persists what passes the JUDGE gate.

```
1. EXTRACT — sonnet_observer emits skill candidates from each RT
2. GATE    — distiller.JUDGE filter (imperative verb, title shape, taxonomy complete)
3. STORE   — Persist to shared-skills/index.json; DERIVE also appended to novel_concepts.json
4. CURATE  — Admin selects best 3–5 for promotion
5. TEST    — Apply in next relevant task, record outcome
6. PROMOTE — If successful, mark as promoted in the shared index
7. EVOLVE  — Update confidence and content based on ongoing use
```

Legacy agent-specific `skills/` directories still receive explicit store-purchased skill deliveries; the observer pipeline feeds the shared index.

## Quality Gates

- Every skill entry must have a concrete "When to Apply" — no vague triggers
- Every FIX must include the failure signature — how to spot the problem
- Every DERIVE must reference the source skills it merges
- Skills with confidence below 0.4 after 5 uses get retired
