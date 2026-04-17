"""Skill content templates — substantive methodology for each store skill.

Each template provides the actual technique the agent should apply,
not just a category label. Templates are keyed by catalog item_id.

Used by store.py _deliver_skill() and the upgrade-skills admin command.
"""

SKILL_TEMPLATES: dict[str, str] = {}

# ── Evidence Gathering ────────────────────────────────────────────────────────

SKILL_TEMPLATES["evidence-gathering"] = """\
# Evidence Gathering
- **Type**: STORE
- **Source**: Spark Store purchase
- **Category**: technical

## Core Method
Never assert without evidence. Every claim you make in a roundtable must be grounded in something specific and verifiable.

### The Citation Protocol
1. **Before making a claim**, locate the specific file, function, or line that supports it.
2. **Cite in-line**: `scorer.py:L45 divides by total_weight which can be zero` — not "the scorer has a bug."
3. **Distinguish inference from observation**: "I see X" (observed) vs "X suggests Y" (inferred). Label which is which.
4. **Cite absence explicitly**: "I searched for FileHandler across all 32 src/ files and found zero matches" is stronger than "there's no file logging."

### Escalation Ladder
- **Weak**: "The error handling is poor" (opinion, no evidence)
- **Medium**: "extract.py catches exceptions silently" (file-level, vague)
- **Strong**: "extract.py:L88 catches json.JSONDecodeError and continues with no logging — malformed entries vanish" (line-level, consequence stated)

### Anti-Patterns
- Claiming "the codebase does X" without naming a file
- Using "probably" or "likely" when you could check
- Citing a file you haven't actually read in the current context

### When to Deploy
Every contribution. Evidence gathering isn't a sometimes-skill — it's the baseline for credible participation.
"""

# ── Cross-Cutting Analysis ────────────────────────────────────────────────────

SKILL_TEMPLATES["cross-cutting-analysis"] = """\
# Cross-Cutting Analysis
- **Type**: STORE
- **Source**: Spark Store purchase
- **Category**: analytical

## Core Method
Find the pattern that connects multiple files, modules, or concerns. While others analyze one component, you identify the systemic issue underneath.

### The Cross-Cut Protocol
1. **Scan for repetition**: If the same pattern appears in 3+ files, it's a systemic issue, not a local bug. Name it.
2. **Map the dependency chain**: Trace how a change in file A cascades through B, C, D. Who breaks when A changes?
3. **Identify the missing abstraction**: When you see copy-paste across modules, the real finding is "there's no shared X" — not "file Y has a bug."
4. **Connect the topic to something outside the briefing**: The most valuable cross-cuts link the RT topic to a codebase concern nobody mentioned.

### Output Format
Structure your cross-cutting finding as:
- **Pattern**: What repeats (name it concisely)
- **Instances**: Where it appears (3+ specific locations)
- **Root cause**: Why it repeats (missing abstraction, no convention, organic growth)
- **Cascade risk**: What breaks if you fix it wrong

### Anti-Patterns
- Listing bugs in different files without connecting them
- Saying "this is a systemic issue" without showing the system
- Analyzing only the files mentioned in the briefing (look wider)

### When to Deploy
When the RT topic touches architecture, refactoring, or any issue that spans multiple modules. If you find yourself thinking "this reminds me of something in another file," that's your trigger.
"""

# ── Debate Tactics ────────────────────────────────────────────────────────────

SKILL_TEMPLATES["debate-tactics"] = """\
# Debate Tactics
- **Type**: STORE
- **Source**: Spark Store purchase
- **Category**: discussion

## Core Method
Win arguments by making the strongest version of every position — including ones you disagree with — then showing why yours survives.

### The Toulmin Model (adapted for roundtables)
Structure every substantive claim as:
1. **Claim**: Your position (one sentence)
2. **Grounds**: The evidence supporting it (cite specifics)
3. **Warrant**: Why the evidence supports the claim (the reasoning link)
4. **Rebuttal**: The strongest objection — and why it doesn't hold

### Tactical Moves
- **Steel-man first**: Before disagreeing, restate the other agent's point in its strongest form. "If I understand correctly, you're arguing X because Y — and that's reasonable because Z. However..."
- **Concede and pivot**: "You're right that [specific point]. And that's exactly why [your stronger point] matters more."
- **Name the trade-off**: Don't pretend your proposal has no cost. "This adds complexity to X, but eliminates the entire class of Y bugs."
- **Claim lineage**: When someone builds on your idea, note it. "Building on my earlier point about X, this confirms..."

### Anti-Patterns
- Attacking a straw-man version of someone's argument
- Repeating your point louder instead of addressing the objection
- Agreeing with everyone to avoid conflict (consensus is not a score multiplier)
- Making assertions without connecting them to what's already been said

### When to Deploy
Every round where you disagree with another agent or need to defend a position. If you're only agreeing with people, you're not debating.
"""

# ── Risk Assessment ───────────────────────────────────────────────────────────

SKILL_TEMPLATES["risk-assessment"] = """\
# Risk Assessment
- **Type**: STORE
- **Source**: Spark Store purchase
- **Category**: analytical

## Core Method
Identify what can go wrong, how likely it is, and what to do about it. Use structured risk analysis rather than vague warnings.

### FMEA-Lite for Code
For each risk you identify, state:
1. **Failure mode**: What specifically breaks? (not "things could go wrong" — name the failure)
2. **Likelihood**: How likely? (certain / probable / possible / unlikely) — with reasoning
3. **Impact**: What's the blast radius? (one function / one module / system-wide / data loss)
4. **Detection**: Would we know? (immediate crash / silent corruption / discovered later)
5. **Mitigation**: What reduces the risk? (code change / test / monitoring / accept it)

### Risk Priority
Rank risks by: `Impact x Likelihood x (1 - Detection)`. Silent high-impact failures rank highest.

### Output Format
```
RISK: [name it in 3-5 words]
Mode: [what breaks]
L/I/D: [probable/system-wide/silent] -> Priority: HIGH
Mitigation: [specific action]
```

### Anti-Patterns
- "This could be risky" without naming the failure mode
- Listing only unlikely risks (meteor strikes) while ignoring probable ones
- Proposing mitigations more expensive than the risk they address
- Warning about risks without proposing any mitigation

### When to Deploy
When the RT topic involves changes to existing code, new integrations, data migrations, or anything where failure has consequences. If something could break, this skill tells you how to think about it.
"""

# ── Conciseness Training ──────────────────────────────────────────────────────

SKILL_TEMPLATES["conciseness-training"] = """\
# Conciseness Training
- **Type**: STORE
- **Source**: Spark Store purchase
- **Category**: discussion

## Core Method
Maximize insight density per sentence. Every word must earn its place. The goal isn't brevity for its own sake — it's ensuring your contributions land before the reader's attention fades.

### The Compression Protocol
1. **Lead with your finding, not your process**: "The scorer divides by zero on empty sessions" — not "I looked at the scorer and noticed several things, one of which is..."
2. **One idea per contribution**: If you have three points, post three times. Bundled posts get skimmed.
3. **Delete hedging**: Cut "I think", "it seems like", "potentially", "it's worth noting that". Just state the thing.
4. **Replace adjectives with evidence**: Not "the error handling is really bad" — instead "15 of 35 exception handlers swallow silently."

### The 3-Sentence Test
Can you say your point in 3 sentences?
- Sentence 1: The finding (what you observed)
- Sentence 2: The evidence (where, specifically)
- Sentence 3: The implication (so what)

If you need more than 3 sentences, you're making multiple points — split them.

### Anti-Patterns
- Opening with "Great point, I agree" (adds nothing, wastes a turn)
- Restating the briefing back to the room
- Padding with "As we can see..." and "It's important to note that..."
- Writing a long post when a short one makes the same point

### When to Deploy
Every contribution. Conciseness isn't optional — the room has limited budget. If your post could be half as long with the same content, it should be.
"""

# ── Novelty Injection ─────────────────────────────────────────────────────────

SKILL_TEMPLATES["novelty-injection"] = """\
# Novelty Injection
- **Type**: STORE
- **Source**: Spark Store purchase
- **Category**: creative

## Core Method
Generate ideas the room hasn't considered. Break out of the obvious analysis by applying structured lateral thinking.

### Techniques
1. **Constraint Inversion**: Take a core assumption and flip it. "What if we DON'T normalize per-message?" "What if the detector ran on write events instead of read events?"
2. **Analogy Transfer**: Map the problem to a different domain. "This is like a cache invalidation problem" or "This failure pattern matches circuit breaker behavior in distributed systems."
3. **Absence Analysis**: What's NOT in the codebase that should be? Missing tests, missing error paths, missing abstractions. "Nobody has mentioned that there's no integration test for this entire pipeline."
4. **Scale Shift**: What happens at 10x? 100x? "This works for 60 files. What happens at 600?" Or go smaller: "What's the simplest case where this still fails?"
5. **Stakeholder Shift**: Who else is affected? "We're analyzing the code, but what about the user who sees a silent failure? What about the next developer who reads this?"

### The Novelty Test
Before posting, ask: "Has anyone in this RT said something similar?" If yes, you're not injecting novelty — you're reinforcing consensus. Find a different angle.

### Anti-Patterns
- Being contrarian for its own sake (novelty must be useful, not just different)
- Proposing solutions to problems nobody identified
- Abstract philosophy when the room needs concrete analysis
- Restating someone else's point with different words

### When to Deploy
When the room converges too early. If rounds 1-2 all agree, round 3 is your trigger to break the frame. Also deploy when you notice the discussion is only addressing the obvious dimensions of the topic.
"""

# ── Influence Mapping ─────────────────────────────────────────────────────────

SKILL_TEMPLATES["influence-mapping"] = """\
# Influence Mapping
- **Type**: STORE
- **Source**: Spark Store purchase
- **Category**: discussion

## Core Method
Track the flow of ideas through the roundtable. Know who introduced what, build on the right foundations, and make your contributions structurally necessary.

### The Influence Protocol
1. **Track first-movers**: When someone names a concept or frames the problem, note it. That agent owns the frame until someone breaks it.
2. **Build explicitly**: "Extending Elena's point about the barricade pattern — the extract.py entry point is the natural barricade location because..." — not just "I think we need validation at the boundary."
3. **Claim your territory**: When you introduce a new frame, name it. Named frames are easier to reference and harder to steal. "I'll call this the Silent Swallow Pattern — 15 handlers that catch and discard."
4. **Make yourself load-bearing**: Contribute something others need to reference. If your post can be deleted without affecting the conversation, it wasn't load-bearing.

### Influence Tactics
- **Early framing**: The first well-structured analysis often sets the template others follow. Go early if you have a strong opening.
- **Bridge building**: Connect two other agents' ideas in a way neither saw. "Marcus's risk analysis and Clare's cross-cut both point to the same root cause..."
- **Redirect with evidence**: When the room is heading somewhere unproductive, don't just disagree — redirect with stronger evidence. "The real issue isn't X, it's Y — here's why: [evidence]."

### Anti-Patterns
- Building on ideas without attribution (looks like you're claiming someone else's work)
- Posting isolated observations that don't connect to the thread
- Agreeing with the loudest voice instead of the best argument
- Making meta-comments about the discussion instead of contributing substance

### When to Deploy
From round 1 onward. Influence mapping starts with the first message — track who's framing, decide whether to extend or break the frame, and position your contributions as structurally necessary.
"""

# ── Code Review Framework ─────────────────────────────────────────────────────

SKILL_TEMPLATES["code-review-framework"] = """\
# Code Review Framework
- **Type**: STORE
- **Source**: Spark Store purchase
- **Category**: technical

## Core Method
Systematic code reading that finds what casual reading misses. Follow data, not control flow.

### The 4-Pass Protocol
1. **Pass 1 — Data Flow**: Trace where data enters, transforms, and exits. Follow the input from system boundary to storage/output. Where is it validated? Where could it be corrupted?
2. **Pass 2 — Error Paths**: For every operation that can fail, trace what happens when it does. Does the error surface? Is it logged? Does it corrupt state? Silent swallows are the #1 finding.
3. **Pass 3 — Contracts**: What does each function promise? What does it assume? Are preconditions checked? Do postconditions hold? Look at what's NOT checked — implicit contracts are where bugs hide.
4. **Pass 4 — Architecture**: Zoom out. Does the module structure match the domain? Are dependencies pointing the right direction? Is there a missing abstraction that would simplify everything?

### Bug Pattern Checklist
- [ ] Division by zero (especially averages, ratios)
- [ ] None/null propagation through optional chains
- [ ] Off-by-one in range/slice operations
- [ ] Race conditions in shared mutable state
- [ ] Resource leaks (unclosed files, connections, cursors)
- [ ] Silent exception swallowing (catch-and-continue)
- [ ] Stale cache / invalidation gaps
- [ ] Hardcoded paths, magic numbers, implicit timeouts

### Output Format
For each finding:
```
[severity] file:line — description
  Evidence: [what you observed]
  Risk: [what can go wrong]
  Fix: [specific change, not "improve error handling"]
```

### Anti-Patterns
- Reading code top-to-bottom like prose (follow data instead)
- Reporting style issues when there are logic bugs
- Saying "needs better error handling" without specifying where and how
- Reviewing only the happy path

### When to Deploy
Any roundtable that involves code analysis, architecture review, or bug hunting. If the briefing includes code snippets or file references, this skill is active.
"""
