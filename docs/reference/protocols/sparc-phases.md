# SPARC Phases Protocol

Five phases. Every significant task goes through all five. Small tasks can compress phases but never skip them.

## Phase 1: Specification

**Question: What are we solving?**

- Define the problem in one sentence
- List functional requirements (must-have)
- List constraints (budget, platform, compatibility)
- Identify edge cases and failure modes upfront
- Define acceptance criteria — what does "done" look like?
- Output: a spec that any team member can read and build from

**In roundtable:** This is the first discussion topic. Workers propose requirements, challenge assumptions, identify missing constraints.

## Phase 2: Architecture

**Question: How will we build it?**

- System design: components, boundaries, interfaces
- Data flow: what moves where, in what format
- Dependency map: what depends on what
- Technology choices with justification (see Research protocol)
- Identify the riskiest component — plan to de-risk it first
- Output: architecture diagram or structured description

**In roundtable:** Workers propose competing architectures. Compare trade-offs. Adversarial thinking applies here — try to break each proposal.

## Phase 3: Refinement

**Question: Does it actually work?**

- TDD thinking: write test expectations BEFORE implementation
- Implement incrementally — smallest working unit first
- Refactor continuously as patterns emerge
- Performance considerations at hot paths only (no premature optimization)
- Error handling for every external boundary
- Output: working, tested code

**In roundtable:** If discussing implementation approach, workers propose test cases and implementation strategies. Not the code itself — the approach.

## Phase 4: Review

**Question: Did we get it right?**

- Cross-model review: a DIFFERENT model/agent reviews the work
- Check against Phase 1 spec — does it meet all acceptance criteria?
- Verification protocol scoring (see verification.md):
  - Correctness, Best Practices, Security, Performance, Documentation
- Flag anything that scores below 0.85
- Output: review report with pass/fail and specific issues

**In roundtable:** This is where Naomi's cross-model perspective is most valuable. She catches Claude-specific blind spots.

## Phase 5: Completion

**Question: Is it ready to ship?**

- Integration testing: does it work with the rest of the system?
- Final assembly of all components
- Documentation: what a future reader needs to understand the work
- Skill distillation: CAPTURE/FIX/DERIVE from the session (see distillation.md)
- Debrief scheduling: flag for Therapist review if significant
- Output: merged, tested, documented deliverable

## Phase Compression

For small tasks (single-file changes, minor fixes):
- Phases 1-2 can be a single internal thought
- Phase 3 is still mandatory (test your change)
- Phase 4 can be self-review if no other model is available
- Phase 5 is still mandatory (verify integration)

Never skip Phase 3 or Phase 5.

## Handoff Format Between Phases

```
PHASE [N] COMPLETE
Summary: [one sentence]
Output: [what was produced]
Open Questions: [anything unresolved]
Next Phase Needs: [what Phase N+1 should focus on]
```
