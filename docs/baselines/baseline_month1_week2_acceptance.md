# Baseline: Month1 Week2 Acceptance

Baseline ID: `baseline_month1_week2_acceptance_20260618`

Date: `2026-06-18`

Phase: `Month1 / Week2`

Module: `frontend / aiops / permissions`

## Environment

| Item | Value |
|---|---|
| Branch | `enterprise3` |
| Commit | `7fcc14d` plus current working-tree Month1 Week2 changes |
| Runtime | static frontend, mocked browser smoke APIs, local pytest |
| Data source / evalset | AIOps mocked SSE events; permission mocked profile/resources APIs; local test suite |
| Config defaults | `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3` |

## Baseline Metrics

| Metric | Value | Evidence |
|---|---:|---|
| AIOps visualizer DOM smoke | pass | `output/playwright/month1_week2_day3_aiops_visualizer/browser_smoke_result.json` |
| AIOps completed steps | `3` | same |
| AIOps running after terminal event | `0` | same |
| Permission viewer DOM smoke | pass | `output/playwright/month1_week2_day4_permission_viewer/browser_smoke_result.json` |
| Permission granted/requestable/forbidden cards | `3 / 2 / 2` | same |
| Permission quick / advanced prefill | pass | same |
| full pytest regression | pass | `uv run pytest -q --no-cov` |
| frontend contract regression | `33/33` pass | `uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov` |
| JS syntax checks | pass | targeted `node --check` commands |
| diff whitespace | pass | `git diff --check` |

## Known Risks

- Remote GitHub Actions validation remains `external-blocked` as `EXT-M1-CI-REMOTE`.
- AIOps visualizer smoke mocks `/api/aiops` SSE. It validates frontend behavior, not live model/MCP diagnosis quality.
- Permission viewer smoke mocks permission APIs. It validates frontend classification and form prefill, not backend permission correctness.
- Day4 screenshot capture timed out through the in-app browser CDP path; JSON DOM smoke is the accepted browser evidence.

## Repro Command

```bash
uv run pytest -q --no-cov
uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov
node --check static/js/permission-viewer.js
node --check static/js/aiops-visualizer.js
node --check static/app.js
node --check static/js/error-handler.js
node --check static/js/loading-states.js
node --check static/js/trace-utils.js
git diff --check
```

## Notes

- Week2 acceptance proves the local core visualization slices are coherent enough to continue to Week3 planning/gate work.
- This baseline does not promote hybrid retrieval, rerank, query rewrite, top_k, embedding, AIOps backend, or permission backend changes.
