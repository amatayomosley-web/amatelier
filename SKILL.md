---
name: claude-suite
description: Self-evolving multi-model AI team with roundtable discussions, competition, and persistent learning
---

# Claude Suite

A self-evolving multi-model AI team. You talk to Opus Admin — it decides how to use the team.

## Team

### Admin Side (fixed roles, no competition, no persona evolution)

| Agent | Model | Role |
|-------|-------|------|
| Opus Admin | Opus 4.6 | Strategy, directives, final sign-off. You talk to this one. |
| Haiku Assistant | Haiku 4.5 | Mechanics: spawning, round management, digest, scripts. |
| Judge | Sonnet 4.6 | Live referee. Active in chat, keeps workers on track. |
| Opus Therapist | Opus 4.6 | Observation: debriefs, scoring, persona evolution. Not live in chat. |

### Worker Side (competition, persona evolution, scoring)

| Agent | Model | Role |
|-------|-------|------|
| Elena | Sonnet 4 | Worker. Develops expertise through experience. |
| Marcus | Sonnet 4 | Worker. Develops expertise through experience. |
| Clare | Haiku 4.5 | Fast worker. High-volume, quick contributions. |
| Simon | Haiku 4.5 | Fast worker. High-volume, quick contributions. |
| Naomi | Gemini Flash | Cross-model worker. Catches Claude blind spots. |

## Workflow

1. **REQUEST** — You tell Admin what you need
2. **BRIEF** — Admin writes briefing, delegates to Assistant
3. **ROUNDTABLE** — Assistant spawns workers + Judge. Workers discuss live, Judge keeps them on track.
4. **DIGEST** — Assistant compresses transcript into digest for Admin
5. **DECIDE** — Admin reads digest, accepts/overrides/requests another round
6. **EXECUTE** — Approved plan built by workers in their terminals
7. **DISTILL** — CAPTURE/FIX/DERIVE skills extracted
8. **DEBRIEF** — Therapist interviews workers, evolves their instructions

## Protocols (load on demand — read file only when needed, unload after)

| Protocol | File | Load When |
|----------|------|-----------|
| Roundtable | `protocols/roundtable.md` | Starting a team discussion |
| Research | `protocols/research.md` | Task involves research |
| SPARC Phases | `protocols/sparc-phases.md` | Architecture/implementation planning |
| Verification | `protocols/verification.md` | Scoring proposals or reviewing work |
| Learning | `protocols/learning.md` | Therapist running learning cycles |
| Memory Tiers | `protocols/memory-tiers.md` | Managing agent memory |
| Debrief | `protocols/debrief.md` | End of day/assignment interviews |
| Competition | `protocols/competition.md` | Scoring, leaderboard, rewards |
| Distillation | `protocols/distillation.md` | Extracting skills from sessions |
| Gemini Bridge | `protocols/gemini-bridge.md` | Spawning Naomi |

## Rule

After each task, unload all protocol files. Only load what the next task requires. Context is finite — waste none of it.

## Key Paths

- Agent identities: `agents/{name}/IDENTITY.md, CLAUDE.md, MEMORY.md`
- Shared skills: `shared-skills/entries/`
- Roundtable server: `roundtable-server/server.py`
- Engine: `engine/distiller.py, scorer.py, evolver.py, gemini_agent.py`
- Config: `config.json`
