# Scorecard: Month1 AIOps Visualizer Day1

Scorecard ID: `SCORE-M1-AIOPS-VIS-DAY1-20260618`

Date: `2026-06-18`

Owner: `Codex`

Phase: `Month1 Week2 Day1`

Module: `frontend / aiops`

## Scope

Create the reusable `AIOpsVisualizer` frontend class and styles so Week2 Day2 can wire live SSE events without changing backend contracts.

Out of scope:

- real SSE event integration
- backend AIOps protocol changes
- browser smoke for live AIOps visualization
- RAG / rerank / query rewrite defaults

## Criteria

| Dimension | Metric / Check | Target | Evidence | Result |
|---|---|---:|---|---|
| Functionality | `AIOpsVisualizer` exposes `init`, `handleEvent`, `updateStep`, `addToolCall` | pass | `static/js/aiops-visualizer.js` | pass |
| Quality | frontend contract tests pass | pass | `uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov` | pass |
| Performance | DOM-only component, no new network calls | baseline-bound | `static/js/aiops-visualizer.js` | pass |
| Safety | no backend/default/permission changes | pass | changed files are static frontend + docs/tests only | pass |
| Maintainability | resource loading order is explicit | pass | `static/index.html` + frontend contract assertions | pass |

## Candidate Options

| Candidate | Description | Expected Benefit | Risk | Status |
|---|---|---|---|---|
| baseline | keep AIOps as streamed text | no extra frontend module | opaque diagnosis flow | measured |
| standalone_visualizer | new static JS/CSS component loaded before `app.js` | Day2 can wire SSE without changing app architecture | unused until Day2 integration | promoted for Day1 |

## Gate Decision

Decision: `pass`

Reason:

- The visualizer class and styles exist as static resources and are loaded before `app.js`.
- Static contract tests lock the resource references, load order, class, methods, and core CSS selectors.
- JS syntax checks pass.
- The implementation is frontend-only and does not change runtime RAG/AIOps defaults.

Required follow-up:

- Month1 Week2 Day2: wire real AIOps SSE events into `AIOpsVisualizer` and add behavior-level tests or browser smoke.
