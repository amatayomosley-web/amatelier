# Memory Tiers Protocol

## Three Tiers

### Tier 1: Working Memory
**What**: Current roundtable context, active task, immediate state.
**Scope**: Single session. Discarded when session ends.
**Contents**:
- Current roundtable transcript (via `listen`)
- Active directive from Admin
- In-progress code or analysis
- Temporary scratch notes

**Rules**:
- Never persist working memory directly — it must be processed first
- If something in working memory matters, promote it before session ends

### Tier 2: Episodic Memory
**What**: Session transcripts, recent debriefs, task outcomes.
**Scope**: Days to weeks. Stored in agent's MEMORY.md or sessions/ directory.
**Contents**:
- Roundtable summaries (not full transcripts — those stay in DB)
- Debrief Q&A records
- Task outcomes with scores
- Mistakes made and lessons identified
- Context about recent projects

**Rules**:
- Each agent maintains their own episodic memory in `agents/{name}/MEMORY.md`
- Therapist reviews and curates during debriefs
- Entries older than 30 days without access get pruned
- High-scoring entries get promoted to Tier 3

### Tier 3: Semantic Memory
**What**: Persistent knowledge, accumulated skills, shared patterns.
**Scope**: Permanent until explicitly retired.
**Contents**:
- Shared skill entries in `shared-skills/entries/`
- CLAUDE.md refinements (agent instructions that evolved)
- Cross-agent patterns (approaches that worked for multiple agents)
- Domain expertise (facts and frameworks that are always true)

**Rules**:
- Only Therapist promotes content from Tier 2 to Tier 3
- Promotion requires: used 3+ times successfully OR scored 0.9+ in verification
- Shared skills are visible to all agents
- Agent-specific CLAUDE.md changes stay per-agent

## Retrieval

Search by similarity across tiers:
1. Check working memory first (fastest, most relevant to current task)
2. Check episodic memory (recent experiences with similar tasks)
3. Check semantic memory (established patterns and skills)

If a Tier 3 entry contradicts a Tier 2 entry, Tier 3 wins (it has been validated).
If a Tier 2 entry is more recent and has evidence, flag the conflict for Therapist review.

## Confidence Scoring

Every stored fact gets a confidence score:
- **1.0**: Verified by experiment or primary source
- **0.8**: Multiple independent sources agree
- **0.6**: Single reliable source, not yet verified
- **0.4**: Community consensus without authoritative backing
- **0.2**: Single unverified claim
- **0.0**: Known to be outdated or contradicted

Facts below 0.4 confidence get flagged on retrieval. Never present a low-confidence fact without the disclaimer.

## Promotion Flow

```
Working Memory
    |
    v (Therapist validates during debrief)
Episodic Memory
    |
    v (3+ uses OR 0.9+ score)
Semantic Memory
```

## Pruning

- Working: auto-cleared at session end
- Episodic: pruned after 30 days without access
- Semantic: only retired by explicit Therapist decision with justification
