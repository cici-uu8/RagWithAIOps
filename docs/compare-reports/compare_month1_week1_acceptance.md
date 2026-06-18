# Compare Report: Month1 Week1 Acceptance

Compare ID: `compare_month1_week1_acceptance_20260618`

Date: `2026-06-18`

Phase: `Month1 / Week1`

Module: `frontend / retrieval / governance`

## Question

What decision does this compare report support?

- Whether Month1 Week1 local P0 work is sufficiently verified to continue to Week2.

## Inputs

| Item | Baseline | Candidate |
|---|---|---|
| commit/config | Day1-Day4 Month1 working tree, defaults locked | Day5 working tree with browser error-card regression fix |
| evalset/data | Retrieval 54q compare; frontend static tests | Full pytest, 21/21 desktop smoke, browser smoke |
| command | `uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov` | `uv run pytest -q --no-cov`; `uv run python smoke_test_desktop_beta.py`; Playwright CLI browser smoke |

## Results

| Metric | Baseline | Candidate | Delta | Gate |
|---|---:|---:|---:|---|
| full local pytest | not rerun at Day4 closeout | pass | stronger evidence | pass |
| desktop technical smoke | not rerun at Day4 closeout | `21/21` | +21 checked scenes | pass |
| browser loading state | observed Day3 | pass | preserved | pass |
| browser trace headers | observed Day4 | pass | preserved | pass |
| browser error card | initial Day5 smoke `error_card_visible=false` | `error_card_visible=true` | fixed regression | pass |
| RAG default change | none | none | no change | pass |
| remote CI | external-blocked | external-blocked | unchanged | external-blocked |

## Failure / Regression Analysis

| Case | Baseline Result | Candidate Result | Category | Decision |
|---|---|---|---|---|
| `/api/chat` 500 browser path | trace text visible, `.error-card` missing | `.error-card` visible and trace_id visible | frontend error rendering | fixed |
| Playwright CLI script attempt 1 | shell expanded `${...}` | abandoned | tooling error | no product impact |
| Playwright CLI script attempt 2 | CLI expected function expression | corrected to `async page => ...` | tooling error | no product impact |
| Playwright CLI script attempt 3 | `require` unavailable in CLI runtime | switched to CLI result + outer extraction | tooling error | no product impact |

## Decision

Decision: `promote`

Reason:

- Candidate fixes the only browser-level Week1 acceptance regression found during Day5.
- Local product smoke and regression tests are green.
- No retrieval/rerank/query rewrite default was changed.

Next action:

- Mark Month1 Week1 complete locally.
- Continue to Month1 Week2, while keeping remote CI and launcher robustness risks visible.
