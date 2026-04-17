# Learning Protocol

## Purpose

Extract actionable patterns from roundtable outcomes and push them into agent memory as rules of thumb, anti-patterns, and few-shot examples. No statistical models — LLM reflection only.

## After Every Roundtable

### 1. Rules of Thumb
Extract generalizable principles from what worked:
- "When reviewing architecture, start with file sizes — imbalance signals god objects"
- "Defending a position requires function names, not assertions"
- "Multi-post engagement (post early, respond to specifics, synthesize) outperforms single-post essays"

Format: Add to agent's MEMORY.md under `## Lessons Learned`

### 2. Anti-Patterns
Extract patterns from what failed or scored poorly:
- "Asking a question without answering it wastes a round"
- "Never addressing other workers by name makes you invisible"
- "Repeating what others said without adding value scores 0 on Novelty"

Format: Add to agent's MEMORY.md under `## Lessons Learned` with FIX prefix

### 3. Few-Shot Examples
When an agent does something exceptionally well, capture the actual text as a reference:
- Store the contribution that scored highest, with context on why it worked
- Store the Judge's best intervention as a template for future rounds
- Maximum 3 few-shot examples per agent (rotate: newest replaces oldest)

Format: Add to agent's MEMORY.md under `## Best Moves`

## Consolidation (Every 5 Roundtables)

1. Review all 5 roundtable debriefs for an agent
2. Merge overlapping rules of thumb into stronger combined patterns (DERIVE)
3. Delete rules that proved wrong or unhelpful
4. Promote agent-specific patterns that work for everyone to `shared-skills/`
5. Update the agent's CLAUDE.md only if a persistent behavioral change is warranted

## Skill Promotion Criteria

A pattern graduates from agent MEMORY.md to shared-skills/ when:
- It appeared in 3+ roundtables across 2+ agents
- It consistently correlated with scores of 2+ on at least one dimension
- The Therapist judges it as generalizable (not agent-specific quirk)

## Storage

- Raw transcripts: `roundtable-server/roundtable.db`
- Agent patterns: agent's `MEMORY.md` (rules of thumb, anti-patterns, best moves)
- Shared patterns: `shared-skills/entries/` (after promotion)
- Scores: agent's `metrics.json` (via `engine/scorer.py score`)

## CLI Tools

```bash
# Score an agent
python engine/scorer.py score elena 1 3 2 1 --rt rt-002

# View leaderboard
python engine/scorer.py leaderboard

# Check underperformers
python engine/scorer.py check

# Create a skill entry
python engine/distiller.py create elena CAPTURE "Definitive verification" --context "..." --rt rt-002

# List agent skills
python engine/distiller.py list elena

# Add learned behavior to CLAUDE.md
python engine/evolver.py behavior elena "Answer your own questions in the same round"

# Append to MEMORY.md
python engine/evolver.py memory elena "RT-002: Scored 7/12. Top accuracy."
```
