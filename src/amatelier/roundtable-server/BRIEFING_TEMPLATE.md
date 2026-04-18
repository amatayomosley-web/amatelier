# Briefing Template

Copy this file and fill in each section when authoring a new roundtable briefing. Replace all `[bracketed placeholders]`. Delete sections that don't apply.

The template reflects patterns that worked in four RTs across 2026-04: layer 8 merger proposal, k-sweep methodology, layer 1 redesign, and interaction-backfill design. Briefings that follow this structure produce tighter convergence and surface real design holes; briefings that skip sections tend to drift.

---

## Template starts below

```markdown
# Briefing: [Short Descriptive Title]

## Context

[2–4 paragraphs. What led to this RT. Prior state. What we've already
established. Link to earlier RT digests when relevant:
"Previous RT (ac4da0cdcb40) deferred X and identified Y as root cause."
"Broad test shows pipeline at 85% pass rate after the Layer 1 + hub judge
repair. The remaining 6 failures trace to a single structural barrier: ..."]

## What Has Shipped / Current State

[Concrete list of recent changes already made, with file paths and
specifics. Prevents agents from re-proposing things already done.]

**File changes (already built and running):**
- `lib/path/to/file.dart`: [what changed]
- `engine/module.py`: [what changed]

**Runtime behavior:**
- `POST /endpoint {"param": value}` [what this does now]
- [How to invoke or verify the new feature]

## The Proposal / The Question

[The actual thing we want the RT to evaluate. Be concrete — paste code
snippets, name parameters, show before/after. Vague briefings produce
vague debates.]

### Mechanism

[How it works end to end. Bullets or numbered steps. Include data-flow
between components.]

1. On [trigger], [component A] does [specific thing]
2. [Component B] reads [specific data], produces [specific output]
3. ...

### Key Design Choices

[Specific decisions that could go multiple ways. Call them out so the RT
knows where to push. Each is a potential point of rejection.]

- **[Choice name]** — [option we picked] vs [alternatives]. Rationale: [why].
- **[Choice name]** — ...

### Budget / Cost Estimate

[Numbers where possible — latency, token count, memory, time to steady state.
Better to be wrong with a number than right with a hand-wave.]

- Per-call latency: ~Xms
- Per-interaction overhead: ~Yms (negligible against Zs baseline)
- Storage: Q rows per shard, ~P bytes each

### Impact Estimate

[Numbers — expected pass rate, resource usage, failure rate. Give a
best/realistic/floor case if uncertain.]

| Phase | Expected outcome |
|-------|------------------|
| Day 0 (install) | 85% (current baseline) |
| Week 1 | 87–89% |
| Week 2 | 90–93% |
| Steady state | 92–96% |

## Round 1: [Focused Question]

[Name the question. Then 3–5 numbered sub-questions. Each a real decision
point, not rhetorical. Be willing to be wrong — the briefing works best
when agents CAN come back with "your premise is flawed because X."]

1. **[Named question]** — [Why it's load-bearing. Specific alternatives
   to consider. What would change the answer.]

2. **[Named question]** — ...

3. **[Named question]** — ...

## Round 2: Severity + Verdict (2-round standard)

Second and final round. Three tasks in one pass:

1. **Severity tagging** — for each finding from Round 1, tag as
   release-blocker / trust damage / minor polish
2. **Mitigations** — for each release-blocker and trust-damage
   finding, propose the minimum change (often "delete text" rather
   than "write new text"). Cite file:line.
3. **Verdict** — consensus on one of:
   - **SHIP as-designed** — no changes, implement immediately
   - **SHIP with modifications** — specify precisely which changes
   - **DEFER** — specify what data/experiment we need first
   - **REJECT** — name the alternative that dominates this approach

Judge renders final verdict at end-of-Round-2 Judge Gate.

## Round 3 (ONLY when genuinely needed)

Add Round 3 only when Round 2 cannot settle the debate — e.g. when
Round 1 surfaces a premise that Round 2 must challenge, AND Round 3
needs to verdict the corrected framing. Default is 2 rounds. See
math in "Default to 2 rounds" above.

## What NOT to Discuss

[Scoping. Things out of scope for this RT because they're separate
workstreams, settled elsewhere, or orthogonal. Prevents drift.]

- [Thing 1 — done in prior RT `digest-xxxxxx.json`]
- [Thing 2 — different workstream]
- [Thing 3 — would require different RT design]

## Steward-Registered Files

[Paths relative to workspace root. Only files the RT needs to read to
ground empirical claims. Judge enforces citation against this list.]

- projects/public/vela-flutter/lib/core/retrieval/merger.dart
- projects/public/vela-flutter/docs/some-doc.md
- projects/public/vela-flutter/staging/some-data/results.json
```

---

## Authoring principles

**Concrete beats abstract.** "Change k from 60 to ~15" produces better debate than "tune the RRF parameter." Include code snippets, numeric targets, and exact file paths. A reader should be able to locate everything you reference.

**Name the decisions.** Agents can only push back on choices if you've named the choices. "We chose option A over option B because X" invites "actually, C is better." Hiding the choices means the RT rubber-stamps them.

**Invite the rejection verdict.** Briefings that only offer "SHIP or SHIP-with-modifications" get SHIP. Include "REJECT — name the alternative" in Round 3 to unlock real critique. That's how the layer 8 RT found the Inversion Fault.

**Scope hard.** The "What NOT to Discuss" list does more work than any other section. Without it, every RT rehashes prior decisions. Be specific — link to the prior digest ID when possible.

**Steward files matter.** Agents that don't cite Steward results are penalized. Under-registering files means agents can't ground their claims and the RT devolves into opinion. But **over-registering is not free** — registered files bloat the briefing context that every worker loads, increasing token burn and the likelihood of timeout cascades at 5-worker concurrency. Empirically: 16 files ran clean in Security RT `afd96c74180e`; 43 files timed out in rounds 2-3 of Open-mode RT `d29eab18f423`. **Target: 15–25 registered files per RT.** Unlisted files can still be requested via `[[request:]]` if an agent needs them.

**Default to 2 rounds.** Math: 5 workers × 2 rounds × ~3 phase slots (speak/rebuttal/floor) = ~30 message slots. With 8 concerns + severity + mitigations + verdict (~29 items), that's 50% bandwidth margin — enough for full coverage with debate friction. Collapse R1 into enumeration-only; fold severity/mitigations/verdict into R2. Use 3 rounds only when there's a genuine decision that needs Round 2 to challenge Round 1's finding AND Round 3 to verdict.

## Subagent Permission Inheritance (read before running)

When `roundtable_runner.py` spawns workers (Elena/Marcus/Clare/Simon/Naomi), the Judge, and the Steward, those subprocesses **inherit the Claude Code permission context of the directory the runner was launched from**. Specifically:

- Workers and judge spawn via `subprocess.Popen([python, claude_agent.py, ...])` from the runner's CWD
- Claude Code (when invoked by those subprocesses) reads `.claude/settings.json` and `.claude/settings.local.json` **relative to the spawning CWD**, not the audit target
- The Steward subagent runs under `--allowedTools Read,Grep,Glob[,WebFetch,WebSearch]` with `--dangerously-skip-permissions` — its filesystem reach is the CWD's workspace

**Practical implication:** if you run claude-suite from `Claude Flow/.claude/skills/claude-suite/` to audit a staged copy of amatelier at `Claude Flow/staging/...`, the subagents can read anything under `Claude Flow/` that that folder's permissions allow — *not* just the staged amatelier files. Users running RTs on sensitive codebases should:
- Run from a clean workspace folder with narrow permissions, OR
- Stage audit targets into a subfolder of the clean workspace, OR
- Register ONLY the files relevant to the audit (the Steward treats unregistered files as out-of-scope for lookup)

This is the same posture as running `claude` directly — subagents are not a separate sandbox.

**Budget/impact numbers.** Even rough estimates. "~500ms" is better than "slow". "85% → 92%" is better than "improved." Numbers give the RT something to falsify.

## Anti-patterns to avoid

- **Leading questions.** "Is this the right approach?" gets "yes." "What are three reasons this could fail?" gets critique.
- **Too many rounds.** Two rounds is often enough. Three is the maximum before the debate frays.
- **Hidden premises.** If your proposal rests on an assumption, name it. "This assumes the embedder handles subfield distinctions, which it may not."
- **Briefing as tutorial.** Agents don't need Vela/Claude Suite internals explained from scratch. Keep context focused on THIS decision.
- **Briefing as ask.** "Please evaluate this and let me know what you think" produces low-impact RTs. Set up specific decisions with concrete alternatives.

## Example briefings (reference)

- `briefing-layer8-merger.md` — proposal → rejection for Inversion Fault
- `briefing-ksweep-plan.md` — methodology critique → reshaped experiment
- `briefing-layer1-redesign.md` — architecture redesign with type dispatch
- `briefing-interaction-backfill.md` — new system design with 4-round scope

Each demonstrates a different use of the template. The first two ended in rejection/revision; the latter two ended in defer-with-clarifications. All four produced actionable outputs.
