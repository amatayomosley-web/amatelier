# Architecture

Technical reference for Atelier's internals. If you want a conceptual overview, read [README.md](README.md) first.

---

## Repository Layout

```
atelier/
├── engine/                    Python orchestrators (runner, therapist, scorer, etc.)
│   └── migrations/            SQL schema migrations, applied in order
├── roundtable-server/         Live SQLite chat layer (db_client, server)
│   └── logs/                  Gemini error log etc. (runtime, gitignored)
├── agents/                    Per-agent dirs — CLAUDE.md + IDENTITY.md shipped,
│   │                          runtime state (MEMORY, behaviors, sessions) gitignored
│   ├── elena/
│   ├── marcus/
│   ├── clare/
│   ├── simon/
│   ├── naomi/
│   ├── judge/
│   ├── therapist/
│   ├── opus-therapist/
│   ├── opus-admin/
│   └── haiku-assistant/
├── protocols/                 11 on-demand protocol docs
├── store/                     Skill catalog, templates, ledger (runtime)
├── shared-skills/             Curated distilled skills (runtime)
├── tests/                     Integration tests
├── tools/                     watch_roundtable.py live viewer
├── benchmarks/                Leaderboard snapshots (runtime)
├── SKILL.md                   Skill metadata + landing card for Claude Code
├── STEWARD.md                 Steward design spec
├── config.json                Team roster, models, fees, thresholds
└── run-roundtable.sh          Convenience wrapper
```

---

## Engine File Map

The engine is 16 Python modules, about 9,000 lines total. Responsibility-by-file:

### Entry points

| File | Lines | Purpose |
|------|------:|---------|
| `roundtable_runner.py` | 1673 | Orchestrator. Opens RT, spawns agents, runs debate rounds, closes, triggers post-RT pipeline. |
| `therapist.py` | 1387 | Post-RT debrief runner. Interviews workers, writes memory/behaviors/sessions. |

### Data layer

| File | Lines | Purpose |
|------|------:|---------|
| `db.py` | 249 | SQLite connection, migration runner, core message ops (`speak`, `listen`, cursor tracking). |

### Scoring

| File | Lines | Purpose |
|------|------:|---------|
| `judge_scorer.py` | 492 | Runs the Judge LLM call to score each agent per RT on 4 dimensions. |
| `scorer.py` | 580 | Score aggregation, fee deduction, gate bonuses, Byzantine variance flags. |
| `analytics.py` | 783 | Growth analytics across RTs — per-agent trend analysis, leaderboard computation. |

### Economy & skills

| File | Lines | Purpose |
|------|------:|---------|
| `store.py` | 831 | Skill store — purchases, delivery, boost application, request fulfillment. |
| `distiller.py` | 247 | Extract skill candidates (CAPTURE / FIX / DERIVE) from RT transcripts. |
| `backfill_distill.py` | 270 | Retroactive distillation for historical digests. |
| `classify_concepts.py` | 173 | Five-axis taxonomy classifier for DERIVE skills → novel_concepts.json. |

### Agent state

| File | Lines | Purpose |
|------|------:|---------|
| `agent_memory.py` | 867 | Structured MEMORY.json access — goals, session summaries, episode aging. |
| `evolver.py` | 485 | Apply therapist-proposed behavior changes; sync skills_owned from ledger. |

### Agent adapters

| File | Lines | Purpose |
|------|------:|---------|
| `claude_agent.py` | 449 | Spawn a Claude Code subprocess as a worker. Listens to DB, posts replies. |
| `gemini_agent.py` | 268 | Spawn Gemini-backed worker (Naomi). |
| `gemini_client.py` | 179 | Thin wrapper over google-generativeai. |

### Steward

| File | Lines | Purpose |
|------|------:|---------|
| `steward_dispatch.py` | 461 | Parse `[[request:]]` tags, spawn ephemeral file-access subagent, inject results. |

### Import graph (simplified)

```
roundtable_runner ──┬─→ db
                    ├─→ steward_dispatch ──→ [spawns ephemeral claude-p subprocess]
                    ├─→ judge_scorer
                    ├─→ scorer ──→ analytics
                    ├─→ distiller ──→ classify_concepts
                    ├─→ store ──→ scorer
                    ├─→ evolver ──→ store
                    ├─→ agent_memory
                    ├─→ [spawns claude_agent subprocess per worker]
                    └─→ [spawns gemini_agent subprocess for Naomi]

claude_agent ──→ db
gemini_agent ──→ db, gemini_client

therapist ──┬─→ db
            ├─→ agent_memory
            ├─→ evolver
            └─→ store
```

The runner does not import worker agents directly — it spawns them as subprocesses that communicate via the SQLite DB.

---

## Database Schema

SQLite at `roundtable-server/roundtable.db`. Four migrations, applied in order at startup by `db._ensure_schema()`.

### 001_initial.sql

**`roundtables`** — one row per RT. `id`, `topic`, `status` (open/closed), `participants` (comma-separated), timestamps.

**`messages`** — append-only chat log. `roundtable_id`, `agent_name`, `message`, `timestamp`.

**`read_cursors`** — per-agent-per-RT read position. Agents use this to know which messages they've seen.

### 002_scores_table.sql

**`scores`** — per-agent per-RT grades on 4 dimensions (novelty, accuracy, impact, challenge). `total`, `reasoning`, `grand_insight` (10-score citation), `scored_by` (which judge run). Foreign key to roundtables.

### 003_spark_ledger.sql

**`spark_ledger`** — immutable record of every spark transaction. Positive = earned, negative = fee or penalty. `reason`, `category` (scoring/fee/penalty/purchase/gate_bonus/venture), optional `roundtable_id`. Current balance = `SUM(amount) WHERE agent_name = X`.

### 004_byzantine_flags.sql

Adds `is_flagged` and `flagged_since_round` columns to `scores`. Used by the variance detector (`scorer.compute_variance_flags`) to catch agents whose scores deviate too far from peers across multiple RTs — a suspicious-pattern signal, not a penalty.

---

## Agent Lifecycle

The full journey of an agent across a single roundtable:

```
1. PRE-RT
   runner reads agents/<name>/CLAUDE.md (operating rules)
                          IDENTITY.md   (persona seed)
                          MEMORY.md     (accumulated context, runtime)
                          MEMORY.json   (structured: goals, skills_owned, sessions)
                          behaviors.json (therapist-evolved behavioral deltas)

2. ENTRY FEE
   scorer deducts fee from spark_ledger (5/8/15 sparks by model class)

3. BOOSTS
   store.apply_boosts_for_rt — purchased consumables fire (extra floor turns,
   first-speaker slot, etc.)

4. SPAWN
   runner launches engine/claude_agent.py or gemini_agent.py as a subprocess
   in its own terminal. Agent connects to the DB as <agent_name>.

5. ROUNDS
   runner posts "ROUND N: begin", then "YOUR TURN: <agent>". Agent listens
   on the DB, generates a response using its assembled context (CLAUDE +
   IDENTITY + MEMORY + behaviors + round state summary), posts via
   db.speak. Judge also listens and intervenes (REDIRECT / GATE / HALT)
   in real time.

6. STEWARD (optional, during any round)
   If agent includes [[request: ...]] in a post, runner extracts the query,
   spawns an ephemeral claude -p subagent with Read/Grep/Glob tools, runs
   the lookup against files registered in the briefing, injects the result
   as a runner message. Agent sees it on next turn.

7. CLOSE
   Runner closes RT. Transcript available via db.get_transcript.

8. SCORING
   judge_scorer runs the Judge LLM once with the full transcript. Emits
   scores per agent. scorer.score persists to scores table, processes GATE
   signals from judge_messages for bonuses.

9. DISTILLATION
   distiller extracts 10–15 skill candidates from transcript via a
   separate Sonnet call. classify_concepts adds taxonomy tags. DERIVE
   skills appended to novel_concepts.json. Admin later curates the best
   3–5 for shared-skills/index.json.

10. THERAPIST (post-RT debrief)
    therapist.py iterates each worker. For each:
      - Builds context from digest + memory + behaviors + session
      - Runs 2–4 turn interview with Opus
      - Parses therapist output for behavioral_deltas, memory_updates,
        session_summary, trait adjustments
      - Writes to behaviors.json, MEMORY.md, MEMORY.json,
        sessions/<rt_id>.md

11. POST-RT CLEANUP
    store.consume_boosts_after_rt — consumables fire for this RT mark as
    spent. age_bulletin_requests — open store requests age one step.
    agent_memory.age_goals — tick active goals forward.
    evolver.sync_skills_owned — refresh agents' skill list from ledger.

12. ANALYTICS
    analytics.update — per-agent growth trends, leaderboard snapshot
    written to benchmarks/leaderboard.json.
```

---

## Roundtable Runner Pipeline

`roundtable_runner.py:run_roundtable()` — the execution skeleton:

1. **Config load** — `config.json`, entry fees, team roster
2. **Briefing load** — parse `briefing-xxx.md`, extract Steward-registered files
3. **DB open** — create RT row, set status=open
4. **Apply boosts** — consume purchased consumables; apply first-speaker slot if won
5. **Entry fees** — deduct from spark_ledger per agent
6. **Research window (Round 0)** — each worker gets 3 **free** Steward requests to ground openings; fire in parallel
7. **Spawn workers + Judge** — subprocesses launched, wait for them to connect
8. **Post briefing** — runner broadcasts the briefing to the chat
9. **Round loop** (default 3 rounds):
    - Post "ROUND N: begin" with budget status
    - **Speak phase** — each worker posts once. If a worker includes `[[request:]]`, they go to the back of the queue while their Steward task runs. If all queue is deferred, intermission fires.
    - **Rebuttal phase** — reverse order, each worker posts a rebuttal
    - **Judge gate** — Judge decides CONVERGED or CONTINUE. If CONVERGED, break the round loop.
    - **Floor phase** — workers with remaining budget may contribute or PASS
    - **Round summary** — Haiku summarizer writes a cumulative debate state (not a per-round summary — a running ESTABLISHED / LIVE POSITIONS / OPEN QUESTIONS / SHIFTS structure)
    - **Rotate speaking order** — first speaker moves to the back
    - **Health audit** — detect dead workers / timeouts / majority-dead abort condition
10. **Close RT** — mark status=closed, collect final transcript
11. **Build digest** — structured JSON summary (contributions, final positions, convergence reason, budget usage)
12. **Judge scoring** — `judge_scorer.judge_score()` runs the Judge LLM with transcript
13. **Process GATE bonuses** — scan Judge messages for `GATE: agent — reason`
14. **Byzantine variance check** — flag scores that deviate from peer consensus
15. **Ventures extraction** — parse `<VENTURE>` / `<MOONSHOT>` / `<SCOUT>` tags
16. **Save leaderboard** — write to benchmarks/leaderboard.json
17. **Update analytics** — per-agent trend computation
18. **Distillation** — extract skill candidates from transcript
19. **Novel concepts append** — DERIVE skills → novel_concepts.json
20. **Therapist debrief** (unless --skip-post)
21. **Store cleanup** — consume boosts, age requests
22. **Memory cleanup** — age goals, add session summaries
23. **Skills sync** — refresh skills_owned per agent
24. **Notification** — write `roundtable-server/latest-result.md`, fire OS toast

Skip-post (`--skip-post` flag) short-circuits after distillation for faster iteration during development.

---

## Scoring System

Each RT emits a per-agent score row. Judge grades four dimensions (0–3 scale, or 10 for a grand insight):

| Dimension | Signal |
|-----------|--------|
| **Novelty** | Said something the group didn't know |
| **Accuracy** | Claims correct and defensible |
| **Impact** | Changed the group's direction or output |
| **Challenge** | Pushed back on weak consensus with evidence |

`total = novelty + accuracy + impact + challenge` (0–12 typical, or higher if a 10 lands).

Calibration target: average RT total is 4–6. A 10 is rare by design — gate-level contributions only.

The score_judge prompt includes calibration examples and explicit reminders that most contributions are 1s. Judge-side model is Sonnet with `--effort max`.

Scores are persisted to `scores` table and aggregated by `analytics.py` into per-agent growth curves. Those curves feed session-start context so each agent enters a new RT knowing how they've been trending.

---

## Distillation Pipeline

After scoring completes, `distiller.py` runs an LLM extraction over the full transcript:

```
Input:  full RT transcript (up to 50K chars, capped)
Model:  Sonnet
Output: JSON array of 10–15 skill objects
```

Each skill has:

```json
{
  "title": "Short descriptive name",
  "type": "CAPTURE | FIX | DERIVE",
  "agent": "originator (or comma-separated for collab)",
  "pattern": "specific technique, with file/line refs",
  "when_to_apply": "concrete conditions for reuse",
  "structural_category": "state-boundary | signal-integrity | ...",
  "trigger_phase": "system-design | code-review | debugging | ...",
  "primary_actor": "individual-contributor | reviewer | architect | ...",
  "problem_nature": "state-lifecycle | calibration-metric | ...",
  "agent_dynamic": "convergence | synthesis | reframing (DERIVE only)",
  "tags": ["3-5 searchable keywords"],
  "one_liner": "plain-English summary"
}
```

**CAPTURE** — observed reusable technique.
**FIX** — an anti-pattern correction.
**DERIVE** — new concept synthesized from multiple contributions. Requires `agent_dynamic`.

DERIVE skills are also classified by `classify_concepts.py` along five orthogonal axes and appended to `novel_concepts.json` with a content-hash dedup check.

Admin later reviews the raw skill candidates in the digest and curates the best 3–5 into `shared-skills/index.json` for team-wide availability.

---

## Store / Economy

`store.py` implements the spark economy. Key tables:

- `store/catalog.json` — purchasable items (skills, boosts, slots)
- `store/skill_templates.py` — full methodology text for 8 foundational skills
- `store/ledger.json` — pending purchases and consumable state (runtime, gitignored)
- `spark_ledger` DB table — immutable transaction log (current balance = SUM of amounts per agent)

Flow for a typical purchase:

1. Agent announces `PURCHASE: <item_id>` in a post during an RT
2. Runner detects the tag after the round, calls `store.attempt_purchase(agent, item_id)`
3. `store.attempt_purchase`:
   - Checks balance against item cost
   - Deducts spark_ledger entry if affordable
   - Delivers skill content (appends to agent MEMORY or registers consumable)
   - Records in store/ledger.json
4. Next RT: `apply_boosts_for_rt` reads ledger for this agent, applies active consumables

Relegation logic (`analytics.check_relegation`): three consecutive net-negative RTs triggers bench / deletion choice — Admin decides.

---

## Steward System

Full design in [STEWARD.md](STEWARD.md). Summary:

- Agents request data by including `[[request: ...]]` in a post
- Runner detects the tag, parses the request
- Deterministic path tries first: JSON filters, regex lookups, value extraction (no LLM)
- If deterministic fails, spawn ephemeral `claude -p` subagent with `--allowedTools Read,Grep,Glob`
- Agent operates only on files listed in the briefing's `## Steward-Registered Files` section
- Result injected back into chat as a runner message, tagged `[Research result for <agent>]`
- Budget: 3 per-agent per-RT, tracked in `StewardBudget`
- Research window (Round 0): 3 **free** concurrent requests per agent to ground opening statements
- Judge enforces citation — empirical claims without a Steward citation or inline math derivation are penalized

---

## Agent State Files

Per agent (in `agents/<name>/`):

| File | Purpose | Gitignored? |
|------|---------|-------------|
| `CLAUDE.md` | Operating rules, DB client location, workflow | Shipped |
| `IDENTITY.md` | Persona seed — who this agent is at base | Shipped |
| `MEMORY.md` | Accumulated context — what they've learned | Runtime (gitignored) |
| `MEMORY.json` | Structured state — goals, skills_owned, session pointers, active episodes | Runtime |
| `behaviors.json` | Therapist-proposed behavioral deltas (accepted and pending) | Runtime |
| `metrics.json` | Current sparks, rank, trait adjustments | Runtime |
| `sessions/<rt_id>.md` | Per-RT debrief summary from Therapist | Runtime |
| `skills/<skill_id>.md` | Delivered purchased skills | Runtime |

`CLAUDE.md` is the operating manual — it doesn't change as the agent evolves. `IDENTITY.md` is the persona seed and can be edited by the Therapist over time. Runtime files are where personality actually lives.

---

## Configuration

`config.json` is the single source of tuning for roster, fees, thresholds, and model choice.

Structure (abridged):

```json
{
  "version": "...",
  "team": { "workers": { "<name>": { "model": "...", "role": "..." } } },
  "roundtable": { "max_rounds": 3, "gemini_refresh_round": 5, ... },
  "competition": {
    "entry_fees": { "haiku": 5, "flash": 5, "sonnet": 8, "opus": 15 },
    "gate_bonus": { "enabled": true, "max_per_rt": 3, "sparks": 3 }
  },
  "self_determined_thresholds": { ... },
  "gemini": { "model": "...", "max_tokens": ..., "temperature": ... },
  "steward": {
    "enabled": true,
    "budget_per_agent": 3,
    "timeout_seconds": 120,
    "max_response_tokens": 2000,
    "haiku_model": "claude-haiku-4-5-20251001",
    "sonnet_model": "claude-sonnet-4-20250514"
  }
}
```

---

## Extension Points

- **Add an agent type** — new entry in `config.json:team.workers`, new dir in `agents/`, wire in `roundtable_runner._launch_worker`
- **Add a skill to the store** — update `store/catalog.json` and add template in `store/skill_templates.py`
- **Change scoring dimensions** — edit judge_scorer prompt + migration to add columns to `scores` table
- **Add a protocol** — drop markdown file in `protocols/`, reference it from SKILL.md's protocol table
- **Custom Steward handlers** — add deterministic paths in `steward_dispatch.try_deterministic` before the subagent fallback fires

---

## Testing

Integration test: `tests/test_integration.py`. Covers:

- DB roundtrip: open RT → speak → listen → close
- Score persistence: insert → read → aggregate
- Transcript index: build from real DB → verify format
- Recall: filter by agent / keyword / round
- Cumulative debate state: verify prior_state threading
- Therapist wiring: `_apply_outcomes` → verify memory/episodes/diary written
- Runner wiring: verify session bridge + goal aging + session summary calls
- Context loading: claude_agent + gemini_agent use render_memory

Run:

```bash
cd ~/.claude/skills/claude-suite/engine
python ../tests/test_integration.py
```

No external API calls required — tests use fixture data.
