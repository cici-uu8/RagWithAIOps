# Risk Triggers

Generated: 2026-06-18

## Red Lines

If a red line triggers, stop new feature work in the affected area, create or update a compare report, and fix or roll back before continuing that area.

| Trigger | Threshold | Action |
|---|---:|---|
| RAG retrieval baseline regression | more than 3 percentage points on a comparable evalset | triage, compare candidate paths, rollback candidate if needed |
| Permission/scope/source_ref issue | any confirmed leak or missing hard gate | treat as security bug; no rollout |
| Answer hallucination on hard safety marker | any confirmed hard-gate failure | block promotion; triage before feature work |
| P95 latency regression | more than 50 percent vs baseline on comparable smoke/perf run | performance triage before rollout |
| Test coverage or targeted regression failure | required checks fail | do not mark task complete |
| Frontend functional smoke regression | core workflow fails | block phase gate |

## Yellow Lines

Yellow lines require a review decision, not necessarily a stop.

| Trigger | Threshold | Action |
|---|---:|---|
| Baseline no lift after two candidate batches | 2 comparable compare reports with no meaningful lift | reconsider candidate strategy |
| External dependency unavailable | one working batch blocked | mark `external-blocked`, continue fallback |
| Single task exceeds estimate | more than 2x planned effort | split scope and update checklist |
| API cost or latency concern | cost estimate exceeds plan or timeout/error rate appears | reduce API use and compare local fallback |

## Compare Gate Rule

Every risky change follows:

1. Record baseline.
2. Run candidate.
3. Produce compare report.
4. Decide: promote, keep shadow, reject, or rollback.
5. Update active checklist and `PROJECT_STATE.md`.
