# Baseline: Month1 AIOps Visualizer SSE Day2

Baseline ID: `BASE-M1-AIOPS-VIS-SSE-DAY2-20260618`

Date: `2026-06-18`

Phase: `Month1 Week2 Day2`

Module: `frontend / aiops`

## Environment

| Item | Value |
|---|---|
| Branch | `enterprise3` |
| Starting commit | `7fcc14d` |
| Prior baseline | `BASE-M1-AIOPS-VIS-DAY1-20260618` |
| Runtime | `static HTML/JS frontend` |
| Backend contract source | `/api/aiops` SSE events normalized by `normalize_sse_event(...)` |
| Config defaults | `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3` |

## Baseline Metrics

| Metric | Day1 Value | Day2 Target |
|---|---:|---:|
| visualizer resource loaded | yes | yes |
| visualizer created inside AIOps message | no | yes |
| `plan` events update visualizer | no | yes |
| `step_complete` events update visualizer | no | yes |
| `report` / `complete` events close visualizer | no | yes |
| existing text / Markdown fallback | yes | unchanged |
| backend protocol changes | none | none |

## Backend Event Shapes Used

| Event type | Fields used by frontend | Visualizer mapping |
|---|---|---|
| `plan` | `plan`, `message` | initialize step list |
| `status` | `message`, optional `step_id` | mark next pending step running |
| `tool_call` | `tool_name`, `parameters` | add expandable tool detail |
| `step_complete` | `step_id`, `step_result`, `result`, `message` | mark current step completed |
| `report` | `report`, `diagnosis`, `message` | complete remaining steps |
| `complete` | `response`, `diagnosis`, `message` | complete remaining steps |
| `error` | `error`, `message`, `data` | mark active step failed |

## Known Risks

- Static contract tests prove wiring and syntax, but do not replace Day3 browser smoke.
- Existing `/api/aiops` can emit events without stable `step_id`; Day2 therefore maps missing ids to the current running or first pending visualizer step.
- Completion must lock the visualizer so late or repeated status events do not make a finished flow appear running.

## Repro Commands

```bash
node --check static/app.js
node --check static/js/aiops-visualizer.js
uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov
```

## Notes

- Day2 preserves the current streamed text and final Markdown rendering. The visualizer is added as a sibling container before `.message-content`, so `updateAIOpsStreamContent(...)` only updates text content and does not remove the visualizer.
