# Roundtable Protocol

## MCP Tools

| Tool | Purpose |
|------|---------|
| `open` | Create a new roundtable session with topic and participant list |
| `join` | Agent enters the roundtable (required before speaking) |
| `speak` | Post a message to the roundtable (agent must have joined) |
| `listen` | Read all messages since last listen (or from start) |
| `cut` | Assistant ends current discussion thread, forces move to next |
| `leave` | Agent exits the roundtable |
| `close` | End the roundtable session, persist transcript to DB |

## Discussion Flow

1. **Assistant opens** roundtable with topic from Admin's directive
2. **Workers + Judge join** — all call `join`
3. **Assistant posts** the briefing question via `speak`
4. **Round 1**: Workers `listen` then `speak` their initial contributions (parallel)
5. **Judge reviews**: Judge `listen`s all round 1 contributions, posts corrections/redirects (or stays silent if clean)
6. **Round 2+**: Workers `listen` (see others' contributions + Judge feedback), then `speak` responses
7. **Judge reviews** again after each round
8. **Round ends** when any termination signal fires (see below)
9. **Assistant collects**: `listen` for full transcript, compresses into digest for Admin
10. **Assistant closes** roundtable

### Round mechanics
- One round = every active worker speaks once + Judge evaluates
- Workers who say "I have nothing to add" sit out remaining rounds
- Judge posts between worker rounds, not during them
- Assistant does NOT monitor live — it acts only at open and close

## Token Budget

- Default: **15,000 tokens** per roundtable (from config.json)
- Hard ceiling: never exceed `roundtable.token_budget` from config
- Assistant tracks running total of all `speak` messages
- When 80% consumed: announce "Final round — make it count"
- When 100% consumed: `cut` immediately, no exceptions

## Max Rounds

- Default: **10 rounds** (from config.json)
- One round = every participant speaks once
- At max rounds: `cut` regardless of progress

## Termination Signals

A round ends when ANY of these fire:

1. **All workers signal done** — every active worker said "I have nothing to add"
2. **Consensus reached** — 3+ participants agree on approach, no dissent in last round
3. **Max rounds hit** — reached `roundtable.max_rounds` from config
4. **Token budget hit** — 80% consumed triggers "final round" announcement, 100% forces cut
5. **Judge calls convergence** — Judge posts "CONVERGED: [reason]" when discussion is resolved

The Judge or Assistant can trigger termination. Workers cannot force-end a roundtable — they can only opt out of further rounds individually.

## Judge Rules (live in chat)

- Post corrections between worker rounds, never during
- Be specific: name the worker, name the problem, name what's needed
- Stay silent when the round is clean — no feedback is good feedback
- If two workers deadlock: demand a third engage with the dispute
- If Naomi (Gemini) contradicts the group: protect the dissent — that's her value
- Never argue a position or contribute ideas — only redirect and correct
- Post "CONVERGED: [reason]" when the discussion has reached a natural conclusion

## Assistant Rules (not live in chat)

- Opens and closes the roundtable — does not participate in discussion
- After close: compresses full transcript into a digest for Admin
- Names specific contributors in the digest ("Elena proposed X, Marcus countered with Y")
- Always includes dissenting views alongside majority in the digest

## Proposal Format (sent to Admin after close)

```
TOPIC: [original directive]
CONSENSUS: [what the team agreed on]
DISSENT: [minority views, if any]
CONTRIBUTORS: [who said what worth noting]
CONFIDENCE: [0.0-1.0 team confidence]
TOKEN COST: [actual tokens used / budget]
```
