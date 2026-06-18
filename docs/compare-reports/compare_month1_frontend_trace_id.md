# Compare Report: Month1 Frontend Trace ID

Compare ID: `CMP-M1-FE-TRACE-20260618`

Date: `2026-06-18`

Phase: `Month1`

Module: `frontend`

## Question

Should the main static frontend install a global trace manager before application scripts so every browser fetch can be correlated with backend audit traces?

## Inputs

| Item | Baseline | Candidate |
|---|---|---|
| commit/config | `pre-Day4 main page without trace-utils` | `static/js/trace-utils.js` loaded before API client |
| evalset/data | static inspection | static contract + Playwright request header smoke |
| command | `rg trace-utils static` | `node --check`, `pytest`, Playwright `request-headers` |

## Results

| Metric | Baseline | Candidate | Delta | Gate |
|---|---:|---:|---:|---|
| primary quality metric | no global main-page trace injector | `x-trace-id` / `x-request-id` present | positive | pass |
| regression metric | existing `readError` parses response payload | wrapper still returns non-2xx response | neutral | pass |
| latency | no wrapper | lightweight header mutation/logging only | negligible | pass |
| cost / external calls | none | none | neutral | pass |
| safety hard gate | backend trace ids accepted | same backend protocol | safe | pass |

## Failure / Regression Analysis

| Case | Baseline Result | Candidate Result | Category | Decision |
|---|---|---|---|---|
| unauthenticated `/api/auth/me` | backend returns 401 with no guaranteed frontend id | request carries frontend trace/request id and response remains 401 | observability improvement | promote |
| error card | trace only when payload/message includes trace_id | trace can also come from `error.traceId` | UX/diagnostic improvement | promote |

## Decision

Decision: `promote`

Reason:

- Playwright request headers showed `x-trace-id: fe-...` and `x-request-id: req-...` on a real browser request.
- Console showed trace-correlated request/response logs.
- Existing response parsing is preserved because the wrapper does not throw on HTTP errors.

Next action:

- Close Month1 Day4 in the execution checklist and continue to Week1 Day5 acceptance.
