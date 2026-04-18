# Briefing: Self-host AI vs use Claude/OpenAI APIs

## Objective

Produce a decision tree for a B2B SaaS founder in 2026 choosing between:

1. **Self-host AI** — run open-weights models (Llama 3.3, DeepSeek, Qwen) on owned or rented GPU infrastructure
2. **Hosted APIs** — Anthropic, OpenAI, Google via pay-per-token

The deliverable is concrete criteria and their flip points, not platitudes about "it depends."

## Context

- Target founder: pre-Series B, 3-20 engineers, building AI features inside a broader SaaS product (not an AI-native product)
- 2026 realities: open-weights models approach hosted frontier performance on many tasks; GPU rental has gotten cheaper; hosted APIs have also gotten cheaper
- Real tradeoffs span: unit economics, margin compression at scale, vendor lock-in, compliance (EU AI Act, sector regs), latency, exit positioning, engineering capability, iteration speed

## Constraints

- Produce a DECISION TREE with quantified thresholds where possible (e.g. "< X calls/day" or "< Y% gross margin")
- Identify the DECISION POINT for each criterion — when does it flip the answer?
- Name specific models, providers, or numbers when useful (the Steward is available for grounding)
- Challenge the false dichotomy where it is false — hybrid architectures are often the real answer

## Success criteria

A digest that a founder could read in 5 minutes and walk away with:

- A 3-5 item decision checklist
- The single most important criterion for their specific stage
- At least one "red flag" signal where the obvious answer would be wrong

## Notes

- Do not invent pricing or benchmark numbers. Use the Steward to ground empirical claims, or explicitly mark them as estimates.
- Naomi: please include the non-US regulatory perspective if relevant (EU AI Act status 2026, non-Western data residency rules).
- Marcus: challenge the "just use the API" default where it deserves challenging — but also call out when the contrarian case is weaker than it sounds.
