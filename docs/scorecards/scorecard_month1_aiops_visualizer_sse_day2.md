# Scorecard: Month1 AIOps Visualizer SSE Day2

Scorecard ID: `SCORE-M1-AIOPS-VIS-SSE-DAY2-20260618`

Date: `2026-06-18`

Owner: `Codex`

Phase: `Month1 Week2 Day2`

Module: `frontend / aiops`

## Scope

Wire `/api/aiops` SSE payloads into `AIOpsVisualizer` while keeping the existing AIOps streamed text and final Markdown response path intact.

Out of scope:

- backend AIOps protocol changes
- AIOps planner / executor / replanner behavior changes
- real browser smoke completion for Week2 Day3
- RAG retrieval, rerank, query rewrite, or top_k defaults

## Criteria

| Dimension | Metric / Check | Target | Evidence | Result |
|---|---|---:|---|---|
| Functionality | `sendAIOpsRequest(...)` attaches visualizer before reading SSE | pass | `static/app.js` | pass |
| Functionality | every parsed SSE object is forwarded to `updateAIOpsVisualizer(...)` | pass | `static/app.js` | pass |
| Functionality | `step_complete` maps missing `step_id` to next active step | pass | `static/app.js` | pass |
| Functionality | terminal events close remaining steps | pass | `static/js/aiops-visualizer.js` | pass |
| Regression | streamed text fallback remains `.message-content.textContent = content` | pass | `static/app.js` | pass |
| Quality | frontend contract tests include Day2 wiring | pass | `tests/test_assistant_frontend_optimization.py` | pending fresh run |
| Safety | no backend/default/permission changes | pass | changed files are frontend + docs/tests only | pass |

## Candidate Options

| Candidate | Description | Expected Benefit | Risk | Status |
|---|---|---|---|---|
| text_only | keep AIOps as streamed text only | no UI risk | opaque diagnostic flow | baseline |
| visualizer_shadow | render visualizer alongside existing text fallback | structured flow with rollback-friendly path | static contract only until browser smoke | selected |
| replace_text_flow | replace text fallback with visualizer only | cleaner UI | high regression risk for final report rendering | rejected |

## Gate Decision

Decision: `pass-after-verification`

Reason:

- Day2 uses `visualizer_shadow`, so existing text and final Markdown rendering remain the fallback.
- Backend event shapes are consumed as-is; no AIOps protocol or runtime default is changed.
- Terminal event locking prevents completed flows from being reopened by late status events.

Required follow-up:

- Run fresh syntax and frontend contract checks.
- Week2 Day3 should do browser smoke or equivalent DOM-level verification before claiming user-visible visual polish complete.
