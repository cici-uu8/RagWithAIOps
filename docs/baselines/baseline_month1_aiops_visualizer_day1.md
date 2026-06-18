# Baseline: Month1 AIOps Visualizer Day1

Baseline ID: `BASE-M1-AIOPS-VIS-DAY1-20260618`

Date: `2026-06-18`

Phase: `Month1 Week2 Day1`

Module: `frontend / aiops`

## Environment

| Item | Value |
|---|---|
| Branch | `enterprise3` |
| Commit | `7fcc14d` starting point |
| Runtime | `static HTML/JS frontend` |
| Data source / evalset | `static/index.html`, `static/app.js`, `tests/test_assistant_frontend_optimization.py` |
| Config defaults | `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3` |

## Baseline Metrics

| Metric | Value | Evidence |
|---|---:|---|
| dedicated AIOps visualizer module | absent | `static/js/aiops-visualizer.js` did not exist before Day1 |
| dedicated AIOps visualizer styles | absent | `static/styles_aiops.css` did not exist before Day1 |
| frontend asset loading | error/loading/trace only | `static/index.html` pre-Day1 |
| AIOps SSE handling | text-only message updates | `static/app.js::sendAIOpsRequest` / `updateAIOpsStreamContent` |
| visualizer contract tests | absent | frontend contract did not assert `AIOpsVisualizer` |

## Known Risks

- AIOps streaming content was still opaque text, so users could not inspect a structured diagnosis flow.
- Day1 creates the reusable visualizer only; Day2 must wire real SSE events before claiming runtime AIOps flow visualization.
- The visualizer must stay frontend-only and must not alter AIOps backend protocol or RAG defaults.

## Repro Command

```bash
rg -n "AIOpsVisualizer|styles_aiops|aiops-visualizer" static tests
```

## Notes

- This baseline is for Month1 Week2 Day1. It does not claim Day2 SSE event integration or Day3 browser smoke completion.
