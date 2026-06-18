# Scorecard: Month1 Frontend Loading State

Scorecard ID: `SCORE-M1-FE-LOADING-20260618`

Date: `2026-06-18`

Owner: `Codex`

Phase: `Month1`

Module: `frontend`

## Scope

把聊天 / 上传 / AIOps 的加载反馈从单一转圈或静态文案，提升为可复用的阶段化 loading state 管理器，并保持现有 API、默认值和错误处理不变。

Out of scope:

- 后端协议变更
- RAG defaults 调整
- trace_id 全局追踪
- 任何新的网络请求

## Criteria

| Dimension | Metric / Check | Target | Evidence | Result |
|---|---|---:|---|---|
| Functionality | `loadingStateManager` 可在页面加载并驱动 chat 阶段文案 | pass | `static/js/loading-states.js` + Playwright smoke | pass |
| Quality | JS 语法和前端静态契约通过 | pass | `node --check static/app.js static/js/loading-states.js` + `uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov` | pass |
| Performance | 仅前端 DOM 更新，无额外后端开销 | baseline-bound | `static/app.js` / `static/js/loading-states.js` | pass |
| Safety | 不改任何默认值、路由或权限 | pass | `static/app.js` / `static/index.html` diff | pass |
| Maintainability | 资源拆分、模板与检查点同步 | pass | `docs/*` + `Month1_执行清单.md` + `PROJECT_STATE.md` | pass |

## Candidate Options

| Candidate | Description | Expected Benefit | Risk | Status |
|---|---|---|---|---|
| baseline | spinner / static overlay text only | simple but opaque | no progress semantics | measured |
| phase_loading_manager | `loadingStateManager` + phase card + progress bar | clearer loading feedback | extra DOM complexity | promoted |

## Gate Decision

Decision: `pass`

Reason:

- chat loading now shows staged text and progress.
- upload / AIOps use the same manager path without backend changes.
- browser smoke confirmed the loading card advances from 30% to 60% and removes cleanly.
- targeted JS check and frontend contract test both passed.

Required follow-up:

- Continue to Month1 Day4 `trace_id` global tracking.
