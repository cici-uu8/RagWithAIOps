# Compare Report: Month1 Frontend Loading State

Compare ID: `CMP-M1-FE-LOADING-20260618`

Date: `2026-06-18`

Phase: `Month1`

Module: `frontend`

## Question

Should the Month1 loading UX be promoted from spinner/static overlay text to a reusable phase-based loading state manager?

## Inputs

| Item | Baseline | Candidate |
|---|---|---|
| commit/config | `pre-Day3 spinner/static overlay` | `enterprise3 working tree with loadingStateManager` |
| evalset/data | `Month1 Day3 current frontend flow` | `Playwright smoke + static contract` |
| command | `pre-change app.js inspection` | `node --check`, `pytest`, `Playwright eval` |

## Results

| Metric | Baseline | Candidate | Delta | Gate |
|---|---:|---:|---:|---|
| primary quality metric | 1 static loading message | 3 chat phases with progress | positive | pass |
| regression metric | no removable phase state | card stops and is removed | neutral | pass |
| latency | no measured stage feedback | local DOM-only updates | neutral | pass |
| cost / external calls | none | none | neutral | pass |
| safety hard gate | no default / route changes | no default / route changes | safe | pass |

## Failure / Regression Analysis

| Case | Baseline Result | Candidate Result | Category | Decision |
|---|---|---|---|---|
| chat loading | opaque spinner | 30% -> 60% -> 90% stage card | UX improvement | promote |
| upload loading | static overlay text | shared manager path present | UX improvement | promote |
| aiops loading | static overlay text | shared manager path present | UX improvement | promote |

## Decision

Decision: `promote`

Reason:

- `loadingStateManager` loads in the browser and renders staged text.
- Playwright smoke confirmed the phase card advances and is removed after stop.
- `static/app.js` keeps the change local to frontend state handling.
- no RAG / backend / default-value behavior changed.

Next action:

- Move to Month1 Day4 `trace_id` global tracking.
