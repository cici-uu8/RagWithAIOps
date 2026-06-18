# Baseline: Month1 Frontend Trace Current State

Baseline ID: `BASE-M1-FE-TRACE-20260618`

Date: `2026-06-18`

Phase: `Month1`

Module: `frontend`

## Environment

| Item | Value |
|---|---|
| Branch | `enterprise3` |
| Commit | `working tree` |
| Runtime | `FastAPI 127.0.0.1:9900 + Playwright browser smoke` |
| Data source / evalset | `static/index.html + static/app.js + GatewayRequest.from_headers` |
| Config defaults | `backend accepts X-Trace-Id / X-Request-Id; main page had no global frontend trace injector` |

## Baseline Metrics

| Metric | Value | Evidence |
|---|---:|---|
| backend trace support | present | `app/enterprise/gateway/models.py` reads `X-Trace-Id` / `X-Request-Id` |
| main page global trace injector | absent | `static/js/trace-utils.js` absent before Day4 |
| main page request trace headers | not guaranteed | `static/app.js` used normal `fetch` / `EnterpriseApiClient.rawRequest` |
| console trace log | absent | no frontend trace logger on main page |
| error card trace display | partial | `ErrorHandler.extractTraceId(...)` parsed payload/message trace_id only |
| dashboard trace headers | present separately | `static/enterprise-dashboard.js` already builds explicit trace/request ids |

## Known Risks

- Main chat page requests could rely on backend-generated ids, making frontend-side troubleshooting harder.
- Error cards could miss a frontend-generated trace id when the backend response had no JSON payload.
- Adding a global fetch wrapper must not break `EnterpriseApiClient.readError(...)` by throwing before response parsing.

## Repro Command

```bash
rg -n "X-Trace-Id|X-Request-Id|trace-utils|traceManager" static app/enterprise/gateway/models.py
```

## Notes

- This baseline applies to the main static chat page. `static/enterprise-dashboard.js` already has a separate explicit trace header path and is not changed in Day4.
