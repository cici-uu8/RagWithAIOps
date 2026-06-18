# Scorecard: Month1 Frontend Trace ID

Scorecard ID: `SCORE-M1-FE-TRACE-20260618`

Date: `2026-06-18`

Owner: `Codex`

Phase: `Month1`

Module: `frontend`

## Scope

Add global frontend trace/request id injection for the main static chat page so all browser `fetch(...)` calls carry `X-Trace-Id` and `X-Request-Id`, while preserving existing backend error parsing and backend-generated trace semantics.

Out of scope:

- backend RequestGateway protocol changes
- enterprise dashboard trace refactor
- admin-console trace UI changes
- RAG / rerank / query rewrite defaults

## Criteria

| Dimension | Metric / Check | Target | Evidence | Result |
|---|---|---:|---|---|
| Functionality | browser request carries `X-Trace-Id` / `X-Request-Id` | pass | Playwright request headers for `/api/auth/me` | pass |
| Quality | JS syntax and frontend static contract pass | pass | `node --check` + `uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov` | pass |
| Performance | no extra network request introduced | pass | `static/js/trace-utils.js` wraps existing fetch only | pass |
| Safety | non-2xx response remains parseable by existing error code | pass | wrapper returns response and does not throw on `!response.ok` | pass |
| Maintainability | trace utility is isolated and loaded before API client | pass | `static/index.html` script order | pass |

## Candidate Options

| Candidate | Description | Expected Benefit | Risk | Status |
|---|---|---|---|---|
| baseline | backend-generated trace ids only for main page | works but less frontend-observable | hard to correlate browser actions | measured |
| global_fetch_wrapper | install `TraceManager` before app scripts and add headers | consistent frontend correlation | can break error parsing if it throws early | promoted with no-throw response policy |

## Gate Decision

Decision: `pass`

Reason:

- real browser request includes `x-trace-id` and `x-request-id`.
- console shows `[trace] METHOD URL` and `[trace] Response status`.
- error card rendering can display `trace_id` extracted from message/error.
- backend protocol remains unchanged.

Required follow-up:

- Continue to Month1 Day5 Week1 acceptance tests after updating Day4 docs.
