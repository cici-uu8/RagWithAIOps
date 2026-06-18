# Scorecard: Month1 AIOps Visualizer Day3 Smoke

Scorecard ID: `SCORE-M1-AIOPS-VIS-DAY3-SMOKE-20260618`

Date: `2026-06-18`

Owner: `Codex`

Phase: `Month1 Week2 Day3`

Module: `frontend / aiops`

## Scope

Verify the AIOps visualizer in a real browser using the actual static page and mocked `/api/aiops` SSE events, then apply the minimal layout style needed for the visualizer container.

Out of scope:

- live AIOps model / MCP / alert-lab diagnosis
- backend protocol changes
- RAG retrieval, rerank, query rewrite, or top_k defaults
- Week2 Day4 permission visualization

## Criteria

| Dimension | Metric / Check | Target | Evidence | Result |
|---|---|---:|---|---|
| Functionality | visualizer container visible | pass | Playwright smoke | pass |
| Functionality | flow container visible | pass | Playwright smoke | pass |
| Functionality | completed step count | `3` | `browser_smoke_result.json` | pass |
| Functionality | running steps after late status | `0` | `browser_smoke_result.json` | pass |
| Functionality | tool call details visible | pass | Playwright smoke | pass |
| Functionality | progress reaches `100%` | pass | Playwright smoke | pass |
| Regression | final report fallback visible | pass | Playwright smoke | pass |
| Layout | visualizer non-zero box | pass | `1100 x 555` | pass |
| Safety | no backend/default/permission changes | pass | frontend-only diff | pass |

## Candidate Options

| Candidate | Description | Expected Benefit | Risk | Status |
|---|---|---|---|---|
| static_only | stop after Day2 static contract | fast but no browser evidence | layout regressions can slip | rejected |
| browser_mock_sse | real page plus mocked `/api/aiops` SSE | verifies DOM without model/MCP noise | not a live AIOps quality proof | promoted |
| live_aiops_e2e | real page plus live model/MCP diagnosis | highest realism | slow/flaky for visualizer-only Day3 | deferred to later AIOps acceptance |

## Gate Decision

Decision: `pass`

Reason:

- The visualizer rendered in the real page and reached a completed state.
- The late status event did not reopen running state.
- The final text/Markdown fallback remained visible.
- The layout had a non-zero browser box and no unexpected console errors.

Required follow-up:

- Continue to Month1 Week2 Day4 `PermissionViewer` / permission-state three-color visualization.
