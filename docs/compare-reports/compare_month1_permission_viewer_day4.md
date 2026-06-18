# Compare Report: Month1 Permission Viewer Day4

Compare ID: `CMP-M1-PERMISSION-VIEWER-DAY4-20260618`

Date: `2026-06-18`

Phase: `Month1 Week2 Day4`

Module: `frontend / permissions`

## Question

Should Week2 Day4 promote the permission-state visualization into the existing `我的权限` modal?

## Inputs

| Item | Baseline | Candidate |
|---|---|---|
| implementation | request forms + request list + database confirmations | `PermissionViewer` plus existing forms |
| data source | `/me/profile`, `/permission-requests/resources`, `/permission-requests/mine`, `/database/confirmations` | same |
| command | frontend static tests | JS syntax, frontend static tests, browser DOM smoke |
| artifacts | existing permission modal | Day4 baseline/scorecard/compare and browser smoke JSON |

## Results

| Metric | Baseline | Candidate | Delta | Gate |
|---|---:|---:|---:|---|
| granted capability visibility | absent | 3 cards | positive | pass |
| requestable capability visibility | form-only | 2 cards + buttons | positive | pass |
| forbidden capability visibility | profile row only | 2 cards with reason | positive | pass |
| quick KB request path | manual selection | card button prefill | positive | pass |
| advanced request path | manual selection | card button prefill | positive | pass |
| existing forms | present | present | neutral | pass |
| database confirmations | present | present | neutral | pass |
| backend permission behavior | unchanged | unchanged | neutral | pass |

## Failure / Regression Analysis

| Case | Baseline Result | Candidate Result | Category | Decision |
|---|---|---|---|---|
| screenshot evidence | not required | CDP screenshot timed out | evidence capture | accept JSON DOM evidence |
| unavailable features | profile row text only | red cards with reasons | UX clarity | promote |
| request flow | users fill form manually | viewer pre-fills same form | workflow | promote |
| permission authority | backend APIs authoritative | backend APIs still authoritative | security | promote |

## Decision

Decision: `promote`

Reason:

- The candidate improves capability visibility without widening backend authority.
- The browser DOM smoke proves the three visual states and request prefill behavior.
- The implementation preserves existing permission request and database confirmation flows.

Next action:

- Execute Month1 Week2 Day5 acceptance gate and close Week2 only if all Day1-Day4 evidence remains green.
