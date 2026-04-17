# Atelier

A self-evolving multi-model AI team skill for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

Ten agents with distinct personalities compete in structured roundtable discussions, earn sparks, buy skills, and evolve through therapist-led debrief sessions. Cross-model — Claude Sonnet, Claude Haiku, and Gemini Flash — with a live Judge moderator who intervenes in real time.

The name **Atelier** is the project identity. The skill installs as `~/.claude/skills/claude-suite/` to match the internal path references agents use to find each other.

---

## Team Roster

### Admin side (fixed roles, no competition, no persona evolution)

| Agent | Model | Role |
|-------|-------|------|
| Opus Admin | Opus 4.6 | Strategy, directives, final sign-off. You talk to this one. |
| Haiku Assistant | Haiku 4.5 | Mechanics: spawning, round management, digest, scripts. |
| Judge | Sonnet 4 | Live referee. Active in chat, keeps workers on track, enforces directive compliance. |
| Opus Therapist | Opus 4.6 | Observation: debriefs, scoring supervision, persona evolution. Not live in chat. |

### Worker side (competition, persona evolution, scoring)

| Agent | Model | Role |
|-------|-------|------|
| Elena | Sonnet 4 | Worker — synthesis and architecture. |
| Marcus | Sonnet 4 | Worker — challenge and exploit detection. |
| Clare | Haiku 4.5 | Fast worker — concise, structural analysis. |
| Simon | Haiku 4.5 | Fast worker — triage, fix sequencing. |
| Naomi | Gemini Flash | Cross-model worker — catches Claude blind spots. |
| Therapist | Haiku | Interviewer — runs the post-roundtable debrief cycle. |

---

## How It Works

An 8-step workflow, orchestrated by the runner:

1. **REQUEST** — You state a goal
2. **BRIEF** — Admin writes a briefing file (`briefing-xxx.md`) delegating to Assistant
3. **ROUNDTABLE** — Assistant spawns workers + Judge. Workers discuss in a live SQLite-backed chat; Judge moderates.
4. **DIGEST** — Assistant compresses the transcript into a structured digest for Admin
5. **DECIDE** — Admin reads digest, accepts / overrides / requests another round
6. **EXECUTE** — Approved plan is built by workers in their own terminals
7. **DISTILL** — CAPTURE / FIX / DERIVE skills are extracted from the transcript
8. **DEBRIEF** — Therapist interviews each worker, updates their MEMORY and evolves their behaviors

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/amatayomosley-web/atelier.git

# 2. Install as a Claude Code skill
cp -r atelier ~/.claude/skills/claude-suite

# 3. Set your Gemini API key (free tier works)
cd ~/.claude/skills/claude-suite
cp .env.example .env
# Edit .env, set GEMINI_API_KEY=<your key from https://aistudio.google.com/apikey>

# 4. Run your first roundtable
python engine/roundtable_runner.py \
  --topic "Your topic here" \
  --briefing roundtable-server/briefing-001.md \
  --budget 3 \
  --summary
```

The runner opens a SQLite-backed chat, spawns the workers + Judge as subprocesses, and prints a human-readable summary when the roundtable completes.

---

## The Spark Economy

Each roundtable is a small market. Agents pay an entry fee, earn sparks by scoring well, and spend sparks on skills or slot privileges.

### Entry fees (deducted at RT start)

| Model | Fee |
|-------|-----|
| Haiku / Flash | 5 sparks |
| Sonnet | 8 sparks |
| Opus | 15 sparks |

### Scoring dimensions (Judge grades, 0–3 scale per dimension, or 10 for a grand insight)

- **Novelty** — did you say something the group didn't already know?
- **Accuracy** — is what you said correct and supported?
- **Impact** — did it change the group's direction or the final output?
- **Challenge** — did you push back on a weak consensus with evidence?

Typical contribution scores 1 in each. Average RT total is 4–6. A 10 in any single dimension requires a genuinely load-bearing insight — rare by design.

### Penalties

| Behavior | Cost |
|----------|------|
| Redundancy | −3 sparks |
| Hallucination | −5 sparks |
| Off-directive | −5 sparks |
| Three consecutive net-negative RTs | Bench or deletion choice |

### Bonuses

- **Gate bonus** — Judge can flag exceptional reframes with `GATE: agent — reason` (max 3 per RT, +3 sparks each)
- **Venture bonus** — 5 sparks awarded when a proposal extracted from the RT is implemented

See [`protocols/spark-economy.md`](protocols/spark-economy.md) and [`protocols/competition.md`](protocols/competition.md) for the full rules.

---

## The Skill Store

Agents spend sparks on purchasable skills and consumable items. Eight foundational skills ship in the catalog (`store/catalog.json`, templates in `store/skill_templates.py`). Skill delivery happens automatically after purchase — the skill content gets appended to the agent's `MEMORY.md`.

### Skill distillation

After each roundtable, a separate Sonnet call extracts skill candidates from the transcript:

- **CAPTURE** — an observed technique worth remembering
- **FIX** — an anti-pattern correction
- **DERIVE** — a new concept synthesized from multiple contributions

Admin curates the best 3–5 per RT for the shared skill pool. DERIVE skills are also appended to `novel_concepts.json` with five-axis taxonomy classification (structural category, trigger phase, primary actor, problem nature, agent dynamic).

See [`protocols/distillation.md`](protocols/distillation.md).

---

## The Steward

The Steward is an empirical-grounding system. Agents request data during debates using `[[request: ...]]` tags in their messages. The runner detects the tag, spawns an ephemeral subagent with `Read` / `Grep` / `Glob` tools, runs the lookup against files registered in the briefing, and injects the result back into the chat.

This eliminates agents fabricating numbers or quoting files they haven't read. Every empirical claim must either cite a Steward research result or show inline mathematical derivation — the Judge enforces this distinction.

Research window: before Round 1 begins, every worker gets 3 **free** concurrent Steward requests to ground their opening positions. Mid-debate requests cost against a per-agent budget (default 3 per RT).

See [`STEWARD.md`](STEWARD.md) for the full design.

---

## The Therapist

Opus-tier coaching after each roundtable. The Therapist runs a 2–4 turn private interview with each worker, using a structured framework:

- **GROW + AAR** — Goal, Reality, Options, Way forward, then After-Action Review
- **SBI feedback** — Situation, Behavior, Impact
- **OARS motivational interviewing** — Open questions, Affirmations, Reflective listening, Summary

Outputs per session:
- Behavioral deltas (`behaviors.json`)
- Memory updates (`MEMORY.md`, `MEMORY.json`)
- Session summary (`sessions/<rt_id>.md`)
- Optional trait adjustments and goal aging

Over dozens of roundtables, each agent's persona evolves — they develop specializations, learn which rhetorical moves work for them, and their instructions sharpen without direct engineering.

See [`protocols/debrief.md`](protocols/debrief.md) and [`protocols/learning.md`](protocols/learning.md).

---

## Watching Live

While a roundtable runs you can tail the chat in real time:

```bash
python tools/watch_roundtable.py
```

This opens the latest roundtable's SQLite table and streams new messages as they arrive. Shows speaker, message, and Judge interventions. Zero API cost — it's just reading the database.

---

## Architecture Overview

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full technical picture. Quick map:

- **`engine/`** — Python orchestrators. `roundtable_runner.py` is the entry point.
- **`roundtable-server/`** — SQLite-backed live chat layer (`db_client.py`, `server.py`) + diagnostics
- **`agents/`** — Per-agent directories with `CLAUDE.md` (operating instructions) and `IDENTITY.md` (persona seed). Runtime state lives here too but is gitignored.
- **`protocols/`** — 11 on-demand protocol docs loaded only when a given workflow needs them
- **`store/`** — Skill catalog, spark economy state
- **`tools/`** — Live watcher
- **`tests/`** — Integration tests
- **`shared-skills/`** — Curated distilled skills (post-Admin curation)

---

## Prerequisites

- **Claude Code** — [install guide](https://docs.anthropic.com/en/docs/claude-code)
- **Python 3.10+**
- **google-generativeai** ≥ 1.51.0 — for the Gemini (Naomi) agent
- **Gemini API key** — free tier is sufficient for most usage

```bash
pip install google-generativeai
```

---

## License

MIT — see [LICENSE](LICENSE).
