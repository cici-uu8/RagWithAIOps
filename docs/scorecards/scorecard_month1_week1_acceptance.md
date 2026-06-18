# Scorecard: Month1 Week1 Acceptance

Scorecard ID: `scorecard_month1_week1_acceptance_20260618`

Date: `2026-06-18`

Owner: `Codex local execution`

Phase: `Month1 / Week1`

Module: `frontend / retrieval / governance`

## Scope

What is being judged:

- Week1 P0 user-experience repair completion: retrieval default safety, frontend error cards, loading states, trace_id/request_id, desktop smoke, and local regression tests.

Out of scope:

- Month1 Week2 AIOps visualization.
- Month1 Week3 corpus expansion to 50 docs.
- Month2 RAG 100 docs / rerank production candidate.
- Remote GitHub Actions execution, which is tracked separately as `external-blocked`.

## Criteria

| Dimension | Metric / Check | Target | Evidence | Result |
|---|---|---:|---|---|
| Functionality | Login/chat/file-manager/user-menu/browser frontend smoke | pass | `output/playwright/month1_week1_day5_smoke/browser_smoke_result.json` | pass |
| Functionality | Desktop technical smoke | `21/21` | `output/smoke_test/*_smoke_test.json` | pass |
| Quality | Full local pytest | pass | `uv run pytest -q --no-cov` | pass |
| Quality | Static frontend contract tests | `32/32` | `uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov` | pass |
| Quality | JS syntax checks | pass | `node --check static/app.js static/js/*.js` targeted commands | pass |
| Safety | RAG defaults unchanged | pass | `app/config.py`, `docs/compare-reports/compare_month1_retrieval_candidates.md` | pass |
| Safety | Error card exposes trace_id without losing structured UI | pass | `error_card_visible=true`, `error_trace_visible=true` | pass |
| Maintainability | baseline/scorecard/compare/evidence docs updated | pass | `docs/baselines/`, `docs/scorecards/`, `docs/compare-reports/`, `docs/milestones/` | pass |

## Candidate Options

| Candidate | Description | Expected Benefit | Risk | Status |
|---|---|---|---|---|
| baseline | Day1-Day4 implemented slices before Day5 acceptance | Existing unit/static checks pass | Browser error-card behavior was not proven end-to-end | measured |
| candidate_a | Day5 acceptance with browser regression fix in `static/app.js` | Proves visible `.error-card` and trace_id in browser | Small trusted-HTML injection path must stay limited to internal error renderer | accepted |

## Gate Decision

Decision: `pass`

Reason:

- Full local pytest passed.
- 21/21 desktop technical smoke passed.
- Browser smoke passed for home/login/user menu/file manager/chat loading/error card/trace headers.
- The only remote CI gap is already tracked as external-blocked and does not block local Month1 work.

Required follow-up:

- Continue to `Month1_执行清单.md` Week2 Day1.
- Track the FastAPI `nohup` lifecycle issue as a launcher robustness task if future local start/restart gates depend on `make restart`.
