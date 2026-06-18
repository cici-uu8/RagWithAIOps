# Baseline: Month1 Permission Viewer Day4

Baseline ID: `BASE-M1-PERMISSION-VIEWER-DAY4-20260618`

Date: `2026-06-18`

Phase: `Month1 Week2 Day4`

Module: `frontend / permissions`

## Environment

| Item | Value |
|---|---|
| Branch | `enterprise3` |
| Starting commit | `7fcc14d` |
| Runtime | static page + mock `/api` browser smoke |
| Data source / evalset | `/me/profile`, `/permission-requests/resources`, `/permission-requests/mine`, `/database/confirmations` mocked through a local static server |
| Config defaults | `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3` |

## Baseline Metrics

| Metric | Before Day4 | Day4 Target |
|---|---:|---:|
| visible permission capability summary | absent | present |
| granted / requestable / forbidden groups | absent | present |
| granted capability cards | unmeasured | `>= 1` |
| requestable capability cards | unmeasured | `>= 1` |
| forbidden capability cards | unmeasured | `>= 1` |
| request button behavior | only manual form selection | prefill existing quick / advanced forms |
| existing permission request forms | present | preserved |
| database confirmations section | present | preserved |

## Evidence

- `static/js/permission-viewer.js`
- `static/app.js`
- `static/index.html`
- `static/styles.css`
- `tests/test_assistant_frontend_optimization.py::AssistantFrontendOptimizationTests::test_permission_viewer_renders_three_color_capability_states`
- `output/playwright/month1_week2_day4_permission_viewer/browser_smoke_result.json`

## Browser Smoke Summary

| Check | Result |
|---|---:|
| viewer visible | `true` |
| granted cards | `3` |
| requestable cards | `2` |
| forbidden cards | `2` |
| request buttons | `2` |
| quick KB prefill | `guide` |
| advanced resource prefill | `database_demo.list_tables` |
| advanced action prefill | `use` |
| error cards | `0` |
| console errors | `0` |

## Known Risks

- The smoke uses mocked profile/resources payloads to verify the frontend consumer and DOM behavior. It is not a live backend permission quality proof.
- Browser screenshot capture timed out twice through the in-app browser CDP path. The JSON DOM smoke was written successfully and is the Day4 browser evidence.
- The component is intentionally read-only from a permission authority perspective; backend `PermissionService` and existing request APIs remain authoritative.

## Repro Summary

Start a local static server that serves `static/index.html` and mocked permission APIs, login through the real page, open `我的权限`, then verify `.permission-viewer`, `.permission-capability-card[data-tone]`, and existing request forms.
