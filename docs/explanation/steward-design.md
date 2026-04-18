# The Steward — Empirical Grounding for Roundtable Debates

## What It Is

The Steward is an ephemeral subagent with file tools (Read, Grep, Glob). It executes precise lookups against pre-registered files and returns citation-ready extracts. It does not theorize, argue, or persist between calls.

## Why It Exists

RT `e81ad3251b80` (Vela Gate dualSignal Granularity) exposed the problem: 42 unverified file/path citations and 57 numeric claims across 5 agents, with 1 caught hallucination (Naomi fabricated "6 of 8 failures occurred on shards with centroid rank 1"). The Judge demanded the measurement 5 times; no agent could run it. The group converged on Option D using partially invented data.

The Steward prevents this by giving debaters a path to ground claims in real data, and giving the Judge a path to verify them.

## Architecture

```
Debater speaks with [[request: show me the gating logic]] tag
    |
Runner detects [[request:]] tag
    |
Runner fires Steward subagent async (Haiku with file tools)
    |
Debater goes to back of speaking queue
    |
Other agents continue speaking
    |
Steward returns extract → runner injects into debater's context
    |
Debater's turn comes back → speaks with evidence
```

The Steward is NOT a roster member. No CLAUDE.md persona, no MEMORY.json, no Therapist sessions, no spark balance. It exists only as an ephemeral subprocess with file tools.

## Invocation

Debaters include a request tag in their speak message:

```
[[request: show me the relevanceGate function in merger.dart]]
```

The tag content is natural language — debaters don't need structured queries. The Steward is smart enough to navigate the codebase and find what was asked for.

## Defer-to-Back Queue

When an agent makes a request during the speak phase:

1. Their message (with `[[request:]]` tag) goes into the transcript immediately
2. Runner fires the Steward subagent asynchronously
3. Agent moves to the **back of the speaking queue**
4. Other agents continue speaking (debate doesn't stall)
5. As each Steward completes, results are injected into context
6. When the deferred agent's turn comes back around, they have their data

### Intermission

If ALL remaining agents in the queue have deferred (everyone requested data, nobody left to speak), the runner pauses and waits for all Steward tasks to complete. Results are injected, then speaking resumes. This is an emergent state — "intermission" — not a planned phase.

## Budget

- **3 requests per agent per RT** (total, not per-round)
- Forces strategic allocation: front-load to ground opening position, or save for rebuttal fact-checks
- Prevents filibuster (can't keep deferring forever)
- **1 active request per agent at a time**
- Unused requests do NOT roll over

## Execution Paths

### Deterministic (no model call)
For simple lookups the runner handles without an LLM:
- JSON filters: `count rows where gateReason=='dualSignal' in results.json`
- Value extraction: `value of vectorFloorStrict in tuning.dart`

### Subagent (Haiku or Sonnet)
For anything requiring code comprehension or navigation:
- "Show me the relevanceGate function"
- "How does the centroid pre-filter interact with hub rescue?"
- Any fuzzy or multi-line request

The subagent gets `Read`, `Grep`, `Glob` tools — file access only. No `Edit`, no `Write`, no `Bash`.

## Private Injection

Steward results are **private to the requesting agent + Judge**. Not injected into all 5 agents' contexts (saves tokens).

The requesting agent cites the relevant parts when they speak. Other agents see the citation in the speech. The between-rounds summarizer naturally compresses cited evidence into the debate state (~40 tokens vs 2000 raw).

**Exception:** Judge-dispatched verifications are shared to all (verdicts, not arguments).

## Result Format

```
[Research result for marcus | haiku | 4.2s]:
merger.dart:152-168 — relevanceGate function:
  ({bool passed, List<ScoredAtom> results, String reason}) relevanceGate(
      List<ScoredAtom> merged,
      double threshold, [
      bool relaxed = false,
      RetrievalTuning? tuning,
  ]) {
      if (merged.isEmpty) { return (..., reason: 'empty'); }
      final domainResult = domainGate(merged, relaxed, tuning);
      if (!domainResult.passed) return domainResult;
      return confidenceGate(domainResult.results, threshold, relaxed, tuning);
  }
```

Properties:
- Always includes source file + line numbers
- Factual only — no interpretation
- Hard cap: 2000 tokens (truncate with `[truncated]` if exceeded)

## Citation Enforcement

The Judge enforces grounded claims via the existing moderation role:

- Any claim with a specific number/threshold/line-number that does NOT reference a Steward result or the briefing is scrutinized
- `HALT [{agent}]: fabricated data` for invented metrics
- Workers who cite Steward results accurately are recognized
- Workers who fabricate when they could have requested are penalized on `accuracy`

This is what makes the Steward not just available but *required*.

## What the Steward Does NOT Do

- **No theorizing.** Returns data, not opinions.
- **No writing.** Read-only file tools. Cannot modify files, run tests, or execute code.
- **No cross-file inference.** Each request navigates from the request to the answer. "Search everything" is bounded by registered files.
- **No persistence.** Dies after each request. No cache, no memory, no session continuity.
- **No personality.** No behavioral evolution, no Therapist sessions.
- **Never guesses.** If it can't find the answer, it says "Not found" and lists what it checked.

## Registered Files

The Steward can ONLY access files declared in the briefing's data pack:

```markdown
## Steward-Registered Files
- staging/smoke-expanded/results.json
- staging/diagnostic-probe/*.json
- lib/core/retrieval/merger.dart
- lib/core/retrieval/tuning.dart
```

Briefings without this section → Steward disabled for that RT.

## Parameters

| Parameter | Value | Location |
|-----------|-------|----------|
| Budget per agent | 3 requests/RT | `config.json → steward.budget_per_agent` |
| Timeout | 120 seconds | `config.json → steward.timeout_seconds` |
| Max response tokens | 2000 | `config.json → steward.max_response_tokens` |
| Haiku model | claude-haiku-4-5-20251001 | `config.json → steward.haiku_model` |
| Sonnet model | claude-sonnet-4-20250514 | `config.json → steward.sonnet_model` |

## Implementation

- `engine/steward_dispatch.py` — request parser, budget tracker, subagent spawner, result formatter
- Runner speak-phase loop modified for defer-to-back queue + async dispatch + intermission
- Judge CLAUDE.md updated with citation enforcement instructions
- All worker CLAUDE.md files updated with `[[request:]]` syntax documentation
- Steward log saved alongside digest as `steward-log-{rt_id}.json`

## Success Criteria

1. **Zero fabricated metrics** — debaters stop inventing numbers because requesting is cheaper than the accuracy penalty
2. **No context bloat** — full files never enter shared context; only 2000-token surgical extracts, compressed to ~40 tokens by summarizer
3. **Empirically grounded convergence** — RT outcomes reference real data
4. **Judge can verify** — every cited number has a traceable extract in the Steward log
5. **No debate stalling** — async dispatch + defer-to-back keeps the conversation moving

## Permission inheritance (operational)

The Steward is **not** a separate sandbox. Like the worker and judge
subagents the runner spawns, it inherits the Claude Code permission
context of the working directory where the runner was launched from.
Concretely:

- `spawn_steward_subagent()` calls `subprocess.run(["claude", ...,
  "--allowedTools", "Read,Grep,Glob", "--dangerously-skip-permissions"])`
  with `cwd=WORKSPACE_ROOT`
- When the Claude CLI starts, it reads `.claude/settings.json` +
  `.claude/settings.local.json` from the spawning CWD — not from
  `AMATELIER_WORKSPACE`
- `WORKSPACE_ROOT` resolves from the `AMATELIER_WORKSPACE` env var or
  the installed package location's ancestor; typically it equals the
  directory the user ran `amatelier roundtable` from
- The credential denylist in `engine/steward_tools.py` defends the
  anthropic-sdk tool-use path; the claude-code CLI path relies on the
  Claude CLI's own Read tool and any `.claude/settings*.json` rules
  present in the spawning folder

**For users auditing untrusted briefings:** run amatelier from a
clean workspace folder with narrow permission grants. The denylist +
truncation + consent gate defend common leak paths, but
prompt-injected agents still inherit whatever filesystem reach the
spawning folder's permissions allow. See `SECURITY.md` for the full
operational posture.
