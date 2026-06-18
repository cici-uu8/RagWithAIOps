# Compare Report: Month1 Week2 Acceptance

Compare ID: `compare_month1_week2_acceptance_20260618`

Date: `2026-06-18`

Phase: `Month1 / Week2`

Module: `frontend / aiops / permissions`

## Question

What decision does this compare report support?

- Whether Month1 Week2 local core visualization work is sufficiently verified to close Week2 and prepare for Week3 without starting Week3 in the same gate.

## Inputs

| Item | Baseline | Candidate |
|---|---|---|
| frontend state | Week1 UX repair frontend | Week2 AIOps visualizer + PermissionViewer |
| evalset/data | Week1 browser smoke and tests | Day3 AIOps browser smoke, Day4 permission browser DOM smoke, full pytest |
| command | Week1 checks | `uv run pytest -q --no-cov`, frontend contract 33/33, targeted JS checks, `git diff --check` |

## Results

| Metric | Baseline | Candidate | Delta | Gate |
|---|---:|---:|---:|---|
| AIOps visualizer visibility | absent | visible | positive | pass |
| AIOps terminal state | absent | running=0 after complete | positive | pass |
| AIOps final report fallback | existing text path | preserved | neutral | pass |
| Permission granted visibility | profile rows only | 3 cards | positive | pass |
| Permission requestable visibility | forms only | 2 cards + buttons | positive | pass |
| Permission forbidden visibility | unavailable row only | 2 cards with reasons | positive | pass |
| Permission request flow | manual form fill | prefill existing forms | positive | pass |
| full local pytest | pass in Week1 | pass in Week2 | preserved | pass |
| frontend contract tests | 32/32 | 33/33 | expanded coverage | pass |
| RAG defaults | unchanged | unchanged | neutral | pass |
| backend permission authority | unchanged | unchanged | neutral | pass |

## Failure / Regression Analysis

| Case | Baseline Result | Candidate Result | Category | Decision |
|---|---|---|---|---|
| AIOps live model/MCP quality | not in Week1 scope | not in Week2 UI scope | out of scope | defer |
| Permission backend correctness | existing backend authority | unchanged | safety | pass |
| Day4 screenshot | not required | CDP screenshot timed out | evidence capture | accept JSON DOM evidence |
| Remote CI | external-blocked | external-blocked | external dependency | keep blocked |

## Decision

Decision: `promote`

Reason:

- Candidate improves AIOps and permission visibility while preserving existing fallback and authority boundaries.
- Local regression and frontend checks are green.
- Evidence is sufficient to close Week2 locally.

Next action:

- Mark Month1 Week2 complete locally.
- Prepare for Month1 Week3 Day0 top_k/rerank shadow compare gate, but do not change defaults or start Week3 work inside this Week2 closeout.
