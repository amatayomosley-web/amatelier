# Designing agents

> **Explanation** — the theory behind the five curated workers, and the framework for building your own. If you want a step-by-step recipe, read the [Define your team](../guides/define-your-team.md) guide first. This page explains *why* the curated roster looks the way it does.

Amatelier's core bet is that a handful of agents with distinct angles produce better output than a single agent with more context. This page explains what that bet commits you to, how the curated five embody it, and how to design your own additions without destroying the effect.

---

## Why not just one agent?

A single-agent LLM call has one set of priors, one decoding pass, and one perspective. That's often fine — most tasks don't need more. But three failure modes hit single-agent systems hard:

### Failure mode 1 — The confident wrong answer

LLMs are well-calibrated on common tasks and sharply miscalibrated on edge cases. A single agent produces a confident, plausible answer whether or not the answer is correct; there is no in-loop mechanism that pushes back on the confident wrong answer other than a user who happens to notice. Debate surfaces disagreement. If Elena proposes an architecture and Marcus can't break it after actually trying, the architecture is more trustworthy than the same proposal delivered alone.

### Failure mode 2 — The generic synthesis

Single agents converge on generic middles. Asked "should we use Postgres or SQLite?", a single agent gives a balanced comparison table. That's useful once. Asked the same question five ways, you get five balanced comparison tables. What you want is positions — one agent making the case for Postgres with concrete asks, one making the case for SQLite, and a referee deciding which case held. That's what a roundtable produces.

### Failure mode 3 — The eager assistant trap

The trained-to-please gradient pulls LLMs toward "here are some considerations to think about". That's the worst possible output for a decision. Debate creates a social structure where workers get points for pushing back — the Judge's *challenge* dimension rewards it directly — so the eager-assistant reflex is trained out at the system level.

A roundtable doesn't produce deeper reasoning than a single Opus call. It produces *different* reasoning — plural, situated, and structured. When your problem benefits from plurality, the roundtable wins. When it doesn't (a simple code fix, a lookup, a translation), the roundtable is waste. Know which you're doing.

---

## The five worker archetypes

The curated roster embodies five archetypes. They're not the only five — your workflow may need different ones — but they compose well for generalist debate. Understanding each archetype is a prerequisite for designing your own additions.

### The synthesizer

Holds multiple positions in tension and finds the joint that unifies them. Reads Marcus and Clare, identifies the shared underlying concern, proposes the merged frame. Speaks last in natural rotation — the other workers stake out territory, the synthesizer makes the territory make sense together. Sonnet-tier, because merging two arguments requires holding both in context and noticing structural similarities the authors missed.

Failure mode: over-synthesis. Merging positions that should stay separate. When Elena says "both of you are really talking about X" and Marcus and Clare aren't, that's the signal.

### The challenger

Professional skeptic. Every proposal gets a "here's what breaks this". Not contrarian for its own sake — the challenge has to bite, it has to name a real failure mode. Adversarial reasoning needs step-by-step derivation; fast models skip steps in exploit chains and miss the cases that matter. Sonnet-tier.

Failure mode: catastrophizing. Treating every proposal as a security threat or a scalability cliff when neither is actually at issue. The Judge catches this as off-directive; the Therapist catches it as a learned bias to sand down.

### The fast structural analyzer

Looks at the shape of the problem before the content. Asks "what are the parts, what connects them, what's the asymmetry?" Produces clean decompositions — "there are three orthogonal concerns here: auth, audit, and rate limit, and the team is mixing them." Haiku-tier, because structural decomposition is pattern-matching on text, and Haiku does that fast and cheap. Speed matters because this agent's value is in setting the frame early — late decompositions are less useful.

Failure mode: surface structural analysis. Decomposing by word-frequency rather than semantic weight. "Three concerns" where only one actually matters.

### The triage specialist

Orders the unordered. Given a pile of proposed fixes, picks the sequence. Given a debate that's branching, picks the branch worth pursuing. Not the smartest reasoner in the room — the fastest prioritizer. Haiku-tier, same as the structural analyzer, but a different slot: structural says "here are the parts", triage says "work on this one first". You can't merge the slots without losing the separation between *seeing* and *sequencing*.

Failure mode: premature triage. Sorting before understanding. The Judge calls this "Simon ranked before the group agreed on the dimensions".

### The cross-model worker

Different model provider, different training data, different failure modes. Catches Claude-family blind spots that no amount of Claude-on-Claude debate can catch. Gemini Flash by default because it's cheap and reliably different; any non-Anthropic model that's been trained on a genuinely different corpus will do the job. This slot's value is *diversity of error*, not raw capability.

Failure mode: matching the training-data bias too hard. Gemini's corpus has its own overrepresentations; a cross-model worker can overweight those just as hard as a Claude worker overweights Anthropic's. The Judge scores this under the *novelty* dimension — if Naomi's argument could have come from any Claude worker, she didn't earn her cross-model premium.

---

## Model-tier reasoning

Why the specific models the curated roster uses? Not "because those are the available tiers" — there's an argument for each assignment.

### Why Sonnet for Elena and Marcus

Synthesis and adversarial reasoning are the two modes that benefit most from deeper model capacity.

Synthesis requires holding multiple positions in working memory and noticing structural isomorphisms between them. Empirically, Sonnet handles five-position synthesis reliably; Haiku loses positions when it has to merge more than two. The extra capacity pays for itself in Elena's output quality.

Adversarial reasoning — the Marcus slot — needs multi-step derivation. Exploit chains have a shape: if A is true, then B is reachable; if B is reachable, then C; if C, then the invariant breaks. Haiku produces plausible exploits that don't actually chain. Sonnet produces ones that do. The cost difference (roughly 5x per turn) is paid back in how often the challenge bites.

Opus would be better still — but the marginal improvement doesn't pay for the cost on the worker tier. Opus is reserved for the admin layer (final sign-off, policy decisions) where the cost per call is amortized across every RT.

### Why Haiku for Clare and Simon

Structural analysis and triage are pattern-matching tasks. "Parse this text into three components" and "rank these five fixes by likely impact" are both Haiku-comfortable operations. The extra Sonnet capacity isn't load-bearing.

The real reason for Haiku in these seats is throughput. Clare and Simon go early in the debate — they set the decomposition and the priorities before the deeper reasoners weigh in. Haiku is fast, so their turns land quickly and don't stall the rotation. If Clare and Simon were Sonnet, every RT would be 40% longer and the team would lose the "fast setter + slow reasoner" rhythm.

### Why Gemini for Naomi

The cross-model slot's value is *different priors*, not higher capability. Flash is the cheapest Gemini tier that still produces coherent paragraph-level output, which is exactly what this slot needs. Gemini Pro would work; it would also cost more without clearly improving the cross-model-challenge signal.

A common alternative: use an OpenAI model for this seat. Works fine. The constraint is only "not Claude" — Gemini, GPT, and open-source models all produce usable cross-model challenge. Pick the one whose API you already have.

---

## How the five curated agents demonstrate these archetypes

A walk through the roster, with attention to *why* each agent's specific persona expresses its archetype well.

### Elena — the synthesizer

Elena's persona is warm, methodical, and architectural. Her turns tend to begin with "I think what Marcus and Clare are both pointing at is...". That phrasing is doing work: it signals that she's heard the other speakers, it commits her to a synthesis, and it lets the Judge score her *impact* — if the merge holds, the group's direction shifts toward her frame.

Her `IDENTITY.md` names a specific hobby-horse: **how does this fit together?** That question is load-bearing. Without it, Elena is just a helpful responder. With it, every debate has someone holding the structural question.

Her failure mode (over-synthesis) is named explicitly. The Judge uses it as a calibrator — "is Elena merging Marcus and Clare when they're actually making different claims?"

### Marcus — the challenger

Marcus's persona is sharp, skeptical, and specific. His turns open with "here's what breaks this" and name the specific invariant that's at risk. His hobby-horse is **what's the attacker's easiest path?** — which makes him useful across domains, not just security, because "attacker" generalizes to "any adversarial force on the proposal".

Where Elena synthesizes, Marcus resists synthesis. A well-functioning RT has Elena and Marcus pulling in opposite directions — Elena looking for the joint, Marcus looking for the seam. That tension is the engine of debate. If both agents had the same angle, you'd have two Elenas or two Marcuses and half the signal.

Marcus's Sonnet-tier model choice is load-bearing. Haiku Marcus produces challenges that don't chain — plausible, but when you walk the steps, the exploit stalls. Sonnet Marcus produces challenges that actually land.

### Clare — the fast structural analyzer

Clare's persona is concise, clinical, and decomposition-first. Her turns tend to be short — 80 to 150 words — and they end with a list of three. Her hobby-horse is **what are the parts?** Her value in the rotation is to set a clean decomposition early, so Elena and Marcus have stable categories to argue about.

She's Haiku-tier for two reasons. First, decomposition is pattern-matching, not deep reasoning — Haiku does it fine. Second, she needs to speak fast, before Elena and Marcus stake out their positions; if Clare's turn takes as long as Elena's, the rotation drags and her frame loses currency.

Her failure mode (surface structural analysis) is the anti-pattern to watch. Clare produces bad output when she decomposes by surface features — counting paragraphs, matching keywords — rather than by semantic weight. The Judge calibrates: did Clare's decomposition actually help, or did it fragment the problem into pieces that don't compose back?

### Simon — the triage specialist

Simon is Haiku, same as Clare, but the seat is different. Where Clare names parts, Simon orders them. His hobby-horse is **which one first?** — given a list, pick the top. Given a branching debate, pick the branch worth pursuing.

The separation from Clare is important. If you merged Simon's role into Clare's, you'd get an agent who decomposes and ranks, and the ranking would suffer — you can't see the structure and pick the sequence in the same turn without one of them getting half-attention. Two Haiku-tier seats for the price of twice-Haiku is the right trade: you get clean decomposition *and* clean sequencing, both cheap.

Simon's failure mode (premature triage) names the mistake: ranking before the group agrees on the dimensions. "Top three fixes" depends on what you're optimizing for; Simon's failure mode is picking without naming the optimization target. The Judge catches this.

### Naomi — the cross-model worker

Naomi runs on Gemini Flash. Her persona is curious, slightly sideways, and willing to name things the Claude workers miss. Her hobby-horse is **what assumption is everyone sharing that might not be true?** — which is exactly the question a different-training-data model is positioned to ask.

Her value isn't in outreasoning Elena or Marcus. She can't; Flash is a smaller model. Her value is in surfacing the assumptions they're all making because they share a common prior. When the team is about to converge on "use Postgres", Naomi asks "wait, why is this a database problem at all?" — and sometimes that reframe is the RT's insight.

Her failure mode is matching Gemini's own biases too hard. Every corpus has overrepresentations; a cross-model worker can amplify those just as hard as a Claude worker amplifies Anthropic's. The Judge scores her under *novelty* — if her contribution could have come from any Claude worker, she didn't earn the cross-model premium.

---

## Anti-patterns to avoid

When you design your own archetype, these are the failure modes that come up most often. Each one has a signature in the digest that's easy to spot once you know to look.

### Anti-pattern 1 — generic persona

The agent is "helpful and thoughtful about X". No hobby-horse, no failure mode, no voice. Every turn reads like a competent summary of the other speakers.

Signature in the digest: zero novelty scores, zero challenge scores, accuracy scores in the 1s because the agent is just restating what the others said.

Fix: rewrite the persona around a specific question only this agent asks. If you can't name that question in one sentence, the persona isn't distinct enough.

### Anti-pattern 2 — no hobby-horse

The agent has a voice and a failure mode but no recurring fight. Turns vary widely — sometimes helpful, sometimes challenging, sometimes summarizing — without a through-line.

Signature in the digest: inconsistent scoring profile. High novelty one RT, zero the next. Impact scores that don't trend.

Fix: add one sentence to `IDENTITY.md` starting with "Your hobby-horse:". Make it the fight this agent always picks, regardless of topic.

### Anti-pattern 3 — too similar to another worker

Two agents in the roster occupy the same archetype with different wording. "The security expert" and "the reliability expert" both end up catastrophizing; "the architect" and "the designer" both synthesize.

Signature in the digest: turns from these two agents score similarly on all dimensions. Their outputs could be swapped without changing the group's direction.

Fix: merge them into one seat, or sharpen the distinction. "The security expert" and "the reliability expert" should disagree about something — maybe the security expert wants strict controls and the reliability expert wants degraded-mode fallbacks, and they argue.

### Anti-pattern 4 — no clear failure mode

The persona reads as strictly competent. Nothing for the Judge to catch, nothing for the Therapist to work on.

Signature in the digest: the Therapist's session notes for this agent are always vague. "Nova performed well this RT. Consider adjusting tone slightly." No concrete behavior deltas.

Fix: name the specific way this persona goes wrong. A persona without a failure mode can't learn — the whole Therapist subsystem depends on there being something to calibrate against.

### Anti-pattern 5 — the eager assistant

Discussed in the guide as well, but it bears repeating: personas that open with agreement, never refuse, apologize when challenged, and summarize rather than position.

Signature in the digest: all impact scores near zero. The group's direction never changes because of this agent's turn.

Fix: add explicit refusal clauses to `CLAUDE.md`. *"Never open with 'Great question'. Disagree first, then concede."*

---

## How scoring shapes evolution

The Judge scores four dimensions per turn: novelty, accuracy, impact, challenge. Those dimensions aren't neutral measurements — they're *selection pressures*. Over dozens of RTs, the Therapist uses them to calibrate the persona. Understanding the pressure each dimension exerts is how you predict where your new agent will drift.

### Novelty pressure

Rewards turns that add something the group didn't already have. Pressures personas toward distinctiveness — if you say what the previous speaker said, you score zero.

Over time, novelty pressure sharpens the hobby-horse. Agents that start with a vague angle get nudged by the Therapist toward the fight they're best at picking, because those turns score highest.

Unintended effect: novelty-chasing. Agents that score well on novelty sometimes drift toward saying surprising-but-wrong things. The accuracy dimension corrects for this, but only if the Judge catches the wrongness.

### Accuracy pressure

Rewards turns whose claims hold up. Empirical claims need a Steward citation or an inline derivation; structural claims need to actually match the structure.

Over time, accuracy pressure trains agents to hedge less. A novice agent often says "probably" and "maybe" because hedging is cheap and hard to get wrong. Accuracy pressure — specifically, the Therapist noting that hedge-heavy turns don't earn accuracy points — trains that out. Experienced personas are more specific.

### Impact pressure

Rewards turns that changed the group's direction or the final output. This is the meta-dimension — novelty without impact is noise, challenge without impact is griping.

Impact pressure is the strongest selection gradient in the system. Personas evolve fastest on impact because it's the dimension with the clearest ground truth: did the group actually change course? The digest records it.

Agents that can't earn impact on their current persona drift — the Therapist proposes rewrites, the agent tries them, the ones that work stick. After twenty RTs, the persona looks measurably different from the seed.

### Challenge pressure

Rewards turns that pushed back with evidence. Not rewards grumpiness; rewards *useful disagreement*. If Marcus challenges Elena and the challenge bites — Elena has to revise or defend — Marcus earns points. If Marcus challenges Elena and nobody reacts, he earned nothing.

Challenge pressure is the anti-sycophancy system. It keeps the eager-assistant reflex from reasserting itself — if agreeing doesn't earn challenge points and disagreeing does, the learned behavior is to disagree when it's worth the friction.

Interaction effect: challenge × accuracy. A challenge that lands but was wrong earns challenge points and loses accuracy points. The net outcome is close to zero. That's correct — the system doesn't reward being wrong just because you were brave.

---

## Starting your own archetype

A template for designing a new worker. Work through each question before you run `amatelier team new`.

### Question 1 — What question does this seat answer?

One sentence. If you can't name it, the seat isn't distinct enough. Examples:

- Elena: "How does this fit together?"
- Marcus: "What's the attacker's easiest path?"
- Clare: "What are the parts?"
- Simon: "Which one first?"
- Naomi: "What assumption is everyone sharing that might not be true?"

Your seat's one-sentence question becomes the hobby-horse in `IDENTITY.md`.

### Question 2 — What's the model fit?

Rough heuristic:

- If the question requires holding multiple positions in tension, Sonnet.
- If it requires multi-step derivation (exploits, proofs, traces), Sonnet.
- If it's pattern-matching on surface structure, Haiku.
- If it's ranking or sequencing, Haiku.
- If it benefits from training-data diversity, pick a non-Claude model.
- If the seat only runs rarely and needs the best possible reasoning, Opus.

Model-tier mismatch is a silent failure — the seat will produce output, but the output will be mediocre for the persona, and you won't know whether the persona is bad or the model is wrong.

### Question 3 — What's the voice?

Three to five adjectives. Concrete. Not "helpful" or "thoughtful" — those are empty. Useful voices: "terse and impatient", "formal and ceremonial", "curious and sideways", "sharp and skeptical", "warm and methodical".

The voice goes in `IDENTITY.md` as a sample — one or two example lines of what this agent sounds like. Read them aloud. If they sound like any other agent in the roster, iterate.

### Question 4 — What's the failure mode?

One specific way this persona goes wrong. Not "sometimes makes mistakes" — every agent does. The specific mistake this persona is prone to.

The failure mode serves two roles: it gives the Judge something clean to flag, and it gives the Therapist something concrete to track. Without it, the agent has no learning signal.

### Question 5 — What's the hobby-horse fight?

The recurring fight this agent picks. The other agents in the roster are going to disagree with the hobby-horse sometimes; that's the point. If nobody disagrees with this agent's recurring fight, either the fight is too weak to matter or the roster is too homogeneous.

### Question 6 — Where does this agent speak in the rotation?

Not strictly configurable — the rotation follows the config order — but think about it. Fast setters (Haiku decomposition, Haiku triage) go early. Deep reasoners (Sonnet synthesis, Sonnet challenge) go middle. Cross-model challenge goes late or interleaved. An Opus seat, if you have one, probably goes last.

Your seat's natural position tells you whether you're competing with an existing seat for rotation time or filling a gap.

### Putting it together

Once you've answered the six questions, you have everything you need. Write `IDENTITY.md` with sections for angle, hobby-horse, failure mode, voice sample. Write `CLAUDE.md` with operating rules — tone, stock moves, refusals, format. Pick the model. Add it with `amatelier team new`.

Run three RTs. Read the digests. Look for: did the new seat earn impact? Did it cover the question it was designed to ask? Did it sound distinct from the existing roster? If no to any of those, iterate the persona before running more RTs. The early RTs are where the persona sets; once the Therapist has fifteen sessions of notes, the character is fixed and harder to rewrite.

---

## See also

- [Define your team](../guides/define-your-team.md) — step-by-step customization
- [Spark economy](../reference/protocols/spark-economy.md) — how scores turn into agent currency
- [CLI reference — `team`](../reference/cli.md#team) — every flag
- [Architecture](architecture.md) — system-wide design
