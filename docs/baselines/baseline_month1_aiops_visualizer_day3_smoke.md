# Baseline: Month1 AIOps Visualizer Day3 Smoke

Baseline ID: `BASE-M1-AIOPS-VIS-DAY3-SMOKE-20260618`

Date: `2026-06-18`

Phase: `Month1 Week2 Day3`

Module: `frontend / aiops`

## Environment

| Item | Value |
|---|---|
| Branch | `enterprise3` |
| Starting commit | `7fcc14d` |
| Runtime | `FastAPI 127.0.0.1:9900 + Playwright browser smoke` |
| Data source / evalset | mocked `/api/aiops` SSE events on the real static page |
| Config defaults | `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3` |

## Baseline Metrics

| Metric | Day2 Contract | Day3 Browser Target |
|---|---:|---:|
| visualizer attached to AIOps message | static contract | visible DOM |
| plan / step / tool / report events | static contract | browser-observed state |
| completed steps | not browser-measured | `3` |
| running steps after completion | not browser-measured | `0` |
| progress text | not browser-measured | `100%` |
| final report text | existing fallback | visible |
| visualizer dimensions | not measured | non-zero box |

## Evidence

- `output/playwright/month1_week2_day3_aiops_visualizer/browser_smoke_result.json`
- `output/playwright/month1_week2_day3_aiops_visualizer/01_home_before_aiops.png`
- `output/playwright/month1_week2_day3_aiops_visualizer/02_aiops_visualizer_complete.png`

## Known Risks

- This is a frontend smoke with mocked `/api/aiops` SSE. It verifies the browser consumer and visualizer DOM, not live AIOps model/MCP diagnosis quality.
- Full Week2 acceptance still needs Day4 permission-state visualization and Day5 Week2 gate.

## Repro Summary

Use Playwright CLI session `month1w2day3`, route `**/api/aiops` to a short `text/event-stream` body with `plan`, `status`, `step_complete`, `tool_call`, `report`, `complete`, and a late `status` event.
