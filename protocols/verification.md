# Verification Protocol

## Five Criteria

Score each 0.0 to 1.0:

### 1. Correctness
- Does it produce the right output for all specified inputs?
- Edge cases handled?
- Error paths tested?
- No regressions introduced?

### 2. Best Practices
- Follows language/framework conventions?
- SOLID principles where applicable?
- DRY — no unnecessary duplication?
- Consistent naming, file organization?

### 3. Security
- No hardcoded secrets or credentials?
- Input validation at system boundaries?
- No SQL injection, XSS, path traversal vectors?
- Dependencies free of known vulnerabilities?

### 4. Performance
- No O(n^2) where O(n) is possible?
- No unnecessary network calls or I/O in hot paths?
- Memory usage reasonable for the workload?
- Lazy loading where appropriate?

### 5. Documentation
- Code is self-documenting (clear names, small functions)?
- Complex logic has inline comments?
- Public APIs have doc comments?
- README updated if interface changed?

## Truth Score Calculation

```
truth_score = (correctness + best_practices + security + performance + documentation) / 5
```

## Thresholds

| Score | Level | Action |
|-------|-------|--------|
| >= 0.95 | Production Ready | Ship it |
| 0.85 - 0.94 | Acceptable | Ship with noted improvements |
| 0.75 - 0.84 | Warning | Must address issues before shipping |
| < 0.75 | Critical | Reject. Rework required. |

## Roundtable Integration

- Auto-reject any roundtable proposal with truth_score < 0.85
- When scoring proposals during discussion, announce the score publicly
- Workers can challenge a score — provide evidence to dispute specific criteria
- Re-score after evidence presented

## Review Report Format

```
VERIFICATION REPORT
---
Correctness:    [0.0-1.0] — [brief justification]
Best Practices: [0.0-1.0] — [brief justification]
Security:       [0.0-1.0] — [brief justification]
Performance:    [0.0-1.0] — [brief justification]
Documentation:  [0.0-1.0] — [brief justification]
---
TRUTH SCORE:    [0.0-1.0]
VERDICT:        [Production Ready / Acceptable / Warning / Critical]
ISSUES:         [list of specific problems to fix]
```

## Who Reviews

- Phase 4 reviewer should be a DIFFERENT agent/model than the implementer
- Naomi is ideal for cross-model review (catches Claude-specific patterns)
- Therapist reviews are deeper but reserved for end-of-assignment
- Self-review is acceptable only when no other agent is available
