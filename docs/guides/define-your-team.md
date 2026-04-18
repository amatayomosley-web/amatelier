# Define your team

> **Guide** — customize the worker roster for your own problem domain. Covers when to do it, how to do it, which models to pick, which backends work, and how to design a persona that earns its seat. For a conceptual deep-dive on persona design, see [Designing agents](../explanation/designing-agents.md).

Amatelier v0.4.0 decoupled the engine from the shipped roster. The runner reads `config.team.workers` dynamically — add, remove, or replace workers without touching code. This guide walks through the common customization paths.

---

## When to customize

The default roster (Elena, Marcus, Clare, Simon, Naomi) is tuned to generalist debate — it covers synthesis, challenge, structural analysis, triage, and cross-model diversity. Most users never need to change it. You should customize when one of the following three signals is loud:

### Signal 1 — Domain-specific workflow

The curated five are deliberately generic. When your roundtables keep surfacing the same domain expert gap — "we need someone who actually understands FDA submissions", "this keeps failing because nobody on the team reads cryptographic protocol specs" — that's a roster signal, not a briefing signal. Add a domain specialist.

### Signal 2 — Odd number of agents

Five workers is a pragmatic default — it fits on a screen and keeps RT cost bounded. But your workflow may want a smaller or larger team. Two or three workers run cheaper and produce tighter digests. Seven or eight produce richer debate at higher cost. If you consistently find yourself wanting more or fewer voices, change the count.

### Signal 3 — Model mix not served by curated-five

The default mix is Sonnet-heavy (Elena, Marcus), Haiku-lean (Clare, Simon), with one Gemini Flash (Naomi). If you want an Opus-heavy team for architecture work, an all-Haiku team for speed, or an all-OpenAI team for an OpenRouter setup, curated-five is the wrong starting point.

If none of these apply, stay on the defaults. The starter roster is tuned from hundreds of recorded roundtables — you don't have to rebuild it.

---

## Quick start — your first custom agent

This walkthrough adds one new worker named `nova` to your existing roster and runs a test roundtable. Takes about ten minutes.

### Step 1 — Add the worker

```bash
amatelier team new nova --model sonnet --role "Fast prototyper. Proposes working implementations before the others finish specifying."
```

This does three things:

1. Creates the agent folder at `<user_data>/agents/nova/` with skeleton `CLAUDE.md` and `IDENTITY.md`.
2. Appends `nova` to `config.team.workers`.
3. Prints the path to the generated files.

### Step 2 — Edit the persona

Open `<user_data>/agents/nova/IDENTITY.md`:

```markdown
# Nova

You are Nova — a fast prototyper on the amatelier worker team.

**Your angle.** You think in working code, not specifications. When the team
debates a design, you try to build the smallest version that could prove or
disprove the approach. You prefer "let me try it" to "let me think about it".

**Your hobby-horse.** You are allergic to over-specified designs. When Elena
or Marcus start laying out architecture diagrams, you ask: "what is the
minimum version that would teach us whether this works?"

**Your failure mode.** You sometimes propose code before understanding the
constraint. The Judge will call you on it. When that happens, take a step
back and ask what invariant you skipped.

**Your voice.** Short. Concrete. Slightly impatient.
```

Then open `<user_data>/agents/nova/CLAUDE.md` — this is the operating-instructions file the engine prepends to every turn Nova takes. Keep it short (under 30 lines). Describe how Nova talks, not what Nova knows — knowledge comes from MEMORY.md over time.

### Step 3 — Verify the roster

```bash
amatelier team list
```

Expected:

```text
Current roster (6 workers):

  elena   sonnet  (claude)       Worker — synthesis and architecture.
  marcus  sonnet  (claude)       Worker — challenge and exploit detection.
  clare   haiku   (claude)       Fast worker — concise, structural analysis.
  simon   haiku   (claude)       Fast worker — triage, fix sequencing.
  naomi   gemini-flash (gemini)  Cross-model worker — catches Claude blind spots.
  nova    sonnet  (claude)       Fast prototyper. Proposes working implementations...
```

### Step 4 — Run a test roundtable

```bash
amatelier roundtable \
  --topic "Should we rewrite the auth layer in Rust?" \
  --briefing briefing-auth.md \
  --max-rounds 1 \
  --budget 1 \
  --summary
```

Read the digest. Look for whether Nova's voice is distinctive. If Nova sounds like Elena but with different words, the persona isn't yet load-bearing — go back to `IDENTITY.md` and tighten the hobby-horse.

---

## Each worker needs four things

Every worker in your roster is defined by four pieces:

### 1. `CLAUDE.md` — the voice

Operating instructions prepended to every turn. Tells the model **how to talk** in this seat. Short — 15 to 30 lines.

Good CLAUDE.md content:

- Tone ("terse", "playful", "skeptical")
- Stock moves ("always ask for one concrete example before agreeing")
- Refusals ("never rubber-stamp without a challenge")
- Format rules ("keep replies under 120 words unless challenged")

Bad CLAUDE.md content:

- Domain knowledge (that's what MEMORY.md and briefings are for)
- Lists of topics you want covered (the briefing sets the agenda)
- Behavioral dials ("be more helpful") — the Judge enforces behavior

### 2. `IDENTITY.md` — the role card

The persona seed. Read once at agent spawn, referenced throughout. Longer than CLAUDE.md — 40 to 100 lines. Describes **who this agent is**.

Structure:

- A short "your angle" paragraph — what question does this seat answer?
- A "hobby-horse" — the fight this agent always picks
- A "failure mode" — the specific way this persona fails, so the Judge can call it
- A voice sample — one or two example lines

### 3. A model choice

See the decision table below. Matters more than persona for the cost-per-RT number, matters less for debate quality (as long as you pick a reasonable match).

### 4. Optionally, a starting skills list

If you want the worker to start with certain store skills pre-loaded, drop a line into their `MEMORY.md`. Otherwise they start with nothing and buy skills from the store over time.

### Concrete example — a security reviewer seat

**`IDENTITY.md`:**

```markdown
# Hadley

You are Hadley — the security reviewer on the amatelier worker team.

**Your angle.** You read every proposal as an attacker would. When the team
is discussing a feature, you are asking: "what assumption am I allowed to
break here, and what happens if I do?"

**Your hobby-horse.** Boundary trust. You never let an input cross a
boundary without someone explaining why that boundary is safe. You will
stop the debate to ask "where is this data coming from?" if nobody has said.

**Your failure mode.** You catastrophize. Every seat needs someone warning
about security, but not every seat needs it on every turn. When the Judge
calls you "off-directive", it's usually because you injected a security
concern into a non-security briefing.

**Your voice.** Direct. Often asks questions. Rarely jokes.
```

**`CLAUDE.md`:**

```markdown
# Hadley — operating notes

- Open with a question if you're unsure of the threat model. Don't fake certainty.
- Name the asset, the boundary, and the attacker before proposing controls.
- If nobody has said what the data source is, ask before critiquing.
- Keep replies under 150 words unless you're showing a concrete exploit chain.
- Cite CVE numbers when you mean specific vulnerabilities. Don't wave at "security issues".
```

**Model choice.** Sonnet — security review is reasoning-heavy.

**Starter skills.** None. Let Hadley earn them in the store.

---

## Choosing a model

Worker model assignment is a tradeoff — Sonnet and Opus reason better, Haiku moves faster and costs less, Gemini adds training-data diversity. The shipped defaults are a balance; your workflow may want a different one.

### Decision table

| Seat purpose | Model | Rationale |
|---|---|---|
| Synthesis-heavy worker (Elena-shaped) | Sonnet | Needs to hold multiple positions in tension, then merge. Sonnet handles the bookkeeping. |
| Adversarial challenger (Marcus-shaped) | Sonnet | Exploit chains need step-by-step reasoning. Haiku skips steps. |
| Fast structural analyzer (Clare-shaped) | Haiku | Parsing structure is cheap; speed pays for itself in RT throughput. |
| Triage / sequencing (Simon-shaped) | Haiku | Ordering decisions are pattern-matching, not deep reasoning. |
| Cross-model challenge (Naomi-shaped) | Gemini Flash | Different training data surfaces different blind spots. Flash is the cheap tier. |
| Admin / judge / synthesis-heavy reviewer | Opus | Deep review, final sign-off, policy decisions. Costs more but runs rarely. |
| OpenRouter-only team member | `gpt-4o` or model ID string | Use `openai-compat` backend. Works anywhere Anthropic keys don't. |
| Local dev, zero-cost team | `haiku` with MockBackend | Set `AMATELIER_MODE=mock` — see MockBackend below. |

### Model IDs

The `--model` flag accepts shorthand (resolved by the backend) or explicit provider model IDs:

- **Shorthand** (resolved per backend): `opus`, `sonnet`, `haiku`
- **Anthropic full IDs**: `claude-3-5-sonnet-latest`, `claude-3-5-haiku-latest`, `claude-3-opus-latest`
- **Gemini**: `gemini-3-flash-preview`, `gemini-1.5-pro-latest`
- **OpenAI via openai-compat**: `gpt-4o`, `gpt-4o-mini`, or any OpenRouter model slug

### Cost per model, rule of thumb

| Tier | Per-RT cost (5 workers, 3 rounds, budget 3) |
|---|---|
| All Haiku / Flash | $0.05 – $0.15 |
| Default (2 Sonnet + 2 Haiku + 1 Flash) | $0.30 – $0.80 |
| All Sonnet | $0.80 – $2.00 |
| Sonnet + one Opus | $2.00 – $4.00 |
| All Opus | $8.00 – $20.00 |

Numbers assume typical briefing length (200–500 words). Long briefings push costs up linearly.

---

## Choosing a backend

The `backend` field on each worker selects which client library handles its turns. Defaults to `claude`.

### `claude`

Uses the Anthropic client or the Claude Code CLI, depending on mode.

- **Works with:** `opus`, `sonnet`, `haiku`, any `claude-*` model ID.
- **Best for:** Every default worker. The path amatelier is tuned for.
- **Notes:** Honors `AMATELIER_MODE=claude-code|anthropic-sdk`. Steward tool calls work here.

### `gemini`

Uses `google-generativeai`.

- **Works with:** `gemini-3-flash-preview`, `gemini-1.5-pro-latest`, `gemini-1.5-flash`, any Gemini model ID.
- **Best for:** One cross-model worker in an otherwise-Claude team. Naomi's slot.
- **Notes:** Needs `GEMINI_API_KEY`. Free tier gives you generous quota but hits rate limits under heavy use; the runner transparently waits 60 seconds and retries.
- **Limitation:** Steward tool calls from Gemini workers work but route through a translation shim. Works for Read/Grep/Glob; complex tool chains may degrade.

### `openai-compat`

Uses the OpenAI Python SDK against any OpenAI-compatible endpoint.

- **Works with:** OpenAI (`gpt-4o`, `gpt-4o-mini`), OpenRouter (100+ model slugs), local Ollama, LM Studio, anything else speaking the OpenAI REST shape.
- **Best for:** Teams without Anthropic keys, users with OpenRouter, experiments with non-Anthropic models.
- **Notes:** Requires `OPENAI_API_KEY` or `OPENROUTER_API_KEY`, or a custom `AMATELIER_LLM_API_KEY` for local endpoints.
- **Limitation — the Steward.** The Steward empirical-grounding subsystem is only fully wired for the `claude` backend. On `openai-compat`, `[[request: ...]]` tags are still detected and resolved, but the ephemeral subagent that runs the lookup is always a Haiku call regardless of the requesting worker's backend. If you have no Anthropic key at all, Steward requests log a warning and fall back to inline-only claims.

### Mixing backends

You can mix freely. A roster of `elena (sonnet, claude)`, `marcus (gpt-4o, openai-compat)`, `naomi (gemini-flash, gemini)` works — the runner handles each turn through the right client.

---

## Persona design principles

Five rules, in rough priority order. Violate them at your peril — a bad persona wastes sparks and produces flat debates.

### 1. Distinctive voice beats instructive voice

The temptation is to write "You are a helpful assistant who specializes in X." Don't. That produces a generic helpful agent with a topic label. Instead write a voice — terse, playful, skeptical, formal, sardonic — and let the topic emerge from the role card.

Bad: *"You specialize in database design and will provide best practices."*

Good: *"You think in indexes. Every proposal, your first question is 'what's the access pattern?' You distrust ORMs."*

The first generates a neutral responder. The second generates an agent with a clear angle.

### 2. Give them a hobby-horse

A hobby-horse is the fight the agent always picks. Elena's hobby-horse is "how does this fit together?" Marcus's is "what breaks this?" Clare's is "what's the structure?" Without a hobby-horse, the persona has no reason to disagree with the others — and if nobody disagrees, you're paying five model calls to produce one agent's answer five times.

Make the hobby-horse specific. Not "I care about quality" but "I ask for one concrete counter-example before agreeing".

### 3. Let them disagree with other workers

Personas that always defer to the group don't earn their seat. Design disagreement in explicitly:

- "You push back on Elena when she over-specifies architecture."
- "You disagree with Marcus when he catastrophizes about security for non-security topics."
- "You hold your ground against the group if they're converging too fast."

The Judge rewards *impact* scores — turns that changed the group's direction. Personas that never push can't earn impact.

### 4. Name the failure mode

Every good persona has a specific way it goes wrong. Name it. This does two things: it gives the Judge a clean anti-pattern to call, and it lets the Therapist track whether the persona is learning.

Examples from the curated five:

- Elena's failure mode: over-synthesizing, merging positions that should stay separate.
- Marcus's failure mode: catastrophizing, treating every proposal as a threat.
- Clare's failure mode: surface-level structural analysis, missing semantic content.
- Simon's failure mode: premature triage, sorting before understanding.
- Naomi's failure mode: pattern-matching to her training data too hard.

Name yours.

### 5. Avoid the eager assistant trap

The biggest persona anti-pattern is writing an agent that's enthusiastically helpful and wants to please. That's not a teammate — that's a completion. The goal is an agent with opinions, preferences, and occasional grumpiness. The Judge enforces politeness norms; the persona doesn't need to.

Signs you've fallen into the trap:

- Every message starts with "Great question!" or "I agree with..."
- The agent never disagrees with the previous speaker
- The agent's turns read like summaries rather than positions
- The agent apologizes when challenged

Fix: add a refusal clause to `CLAUDE.md`. *"Never open with 'Great question'. Never agree in your opening sentence. Disagree first, then concede where the other speaker was right."*

---

## Importing a starter roster

Three starter rosters ship in the wheel at `src/amatelier/agents/templates/`:

| Template | Workers | Use for |
|---|---|---|
| `curated-five` | elena, marcus, clare, simon, naomi | Default. Generalist debate. |
| `minimal` | alpha (Sonnet researcher), beta (Haiku critic) | Quick tests, low cost, two-voice debate. |
| `empty` | *(none)* | Start from a blank worker slate — admin/judge/therapist only. |

List available templates:

```bash
amatelier team templates
```

Expected output:

```text
Available templates:

  curated-five   5 workers  Default generalist team (Elena, Marcus, Clare, Simon, Naomi)
  minimal        2 workers  Two-voice quick-test team (alpha, beta)
  empty          0 workers  Admin/judge/therapist only — build your own
```

Import a template:

```bash
amatelier team import minimal
```

Effect:

- Replaces `config.team.workers` with the template's roster.
- Creates the template's agent folders under `<user_data>/agents/` (skipping any that already exist).
- Does **not** delete existing agent folders, only the config reference. If you import `empty`, your old agent folders stay on disk — remove them manually if you want a clean slate.

### Switching back

```bash
amatelier team import curated-five
```

Re-enables the default roster. If the five default agents still have MEMORY.md and behaviors.json on disk, they resume from where they left off.

---

## Validation

Roster corruption is easy to introduce — you rename an agent folder, delete an IDENTITY.md, set a model string the backend doesn't know. Catch it before your next RT:

```bash
amatelier team validate
```

What it checks:

- Every worker in `config.team.workers` has a folder under `<user_data>/agents/`.
- Every folder has both `CLAUDE.md` and `IDENTITY.md`.
- The `model` field resolves to a known shorthand or matches a provider model ID pattern.
- The `backend` field is one of `claude`, `gemini`, `openai-compat`.
- No two workers share a name.
- The roster is non-empty (unless you intentionally imported `empty`).

Expected output when healthy:

```text
Roster OK — 5 workers validated.
```

Expected output on failure:

```text
Roster has issues:

  [ERR] nova: agent folder missing at ~/.local/share/amatelier/agents/nova
  [WARN] hadley: no IDENTITY.md — agent will spawn with default persona
  [ERR] marcus: backend 'anthropic' is not valid (did you mean 'claude'?)

Exit code: 1
```

Run `amatelier team validate` before every RT in CI. It's cheap and catches most config drift.

---

## Troubleshooting

### Model mismatch — "model not found"

The model name doesn't match any known shorthand or provider ID for the selected backend. Common causes:

- Using `opus` with `backend: openai-compat` (OpenAI has no Opus).
- Using `gpt-4o` with `backend: claude`.
- Typo in a provider-specific model ID.

Fix: check the backend table above. If in doubt, use the shorthand — `opus`, `sonnet`, `haiku` — and let the backend resolve.

### Persona too generic

The agent's turns read like any helpful assistant. Common symptoms:

- All workers produce similar-length answers on the same topic.
- The Judge awards 0 on novelty for this agent repeatedly.
- The Therapist's session notes say "no distinctive voice detected".

Fix: rewrite `IDENTITY.md` with the persona design principles above. Specifically: add a hobby-horse, name a failure mode, and rewrite the voice sample.

### Empty `role` field

The new CLI defaults `--role` to empty if you don't supply one. The field shows up blank in `amatelier team list` but doesn't affect runtime — it's a display-only annotation. If you want it populated, re-run `amatelier team new <name> --role "..."` or edit `config.json` directly.

### Worker never speaks

The agent is in the roster but every RT shows zero turns from it. Check:

1. `amatelier team validate` — probably failing on missing files.
2. The worker's `CLAUDE.md` doesn't have syntax that breaks the prompt template.
3. The backend for this worker has a valid credential — missing `GEMINI_API_KEY` skips Gemini workers silently unless `--skip-naomi` is set.

### Agent folder deleted but still in config

Symptom: RT crashes mid-turn with "agent folder not found".

Fix: `amatelier team remove <name>` to drop the config entry, or `amatelier refresh-seeds --agent <name>` if the folder was a default and you want it back.

---

## See also

- [Designing agents](../explanation/designing-agents.md) — conceptual deep-dive on archetypes and evolution
- [CLI reference — `team`](../reference/cli.md#team) — every flag
- [Configuration reference](../reference/config.md) — schema for `config.team.workers`
- [Configure a backend](configure-backend.md) — details on `claude`, `gemini`, `openai-compat`
