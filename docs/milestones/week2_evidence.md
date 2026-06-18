# Week 2 Evidence: Month1 Core Capability Visualization

**里程碑名称**: Month1 Week2 核心能力可视化
**完成日期**: 2026-06-18
**负责人**: Codex local execution

---

## 1. 代码变更证据

### PR链接

- PR: 未创建
- 状态: local working tree
- Review者: 未进行外部 review
- Review状态: pending

### Git Commit

当前基础 commit:

```bash
git rev-parse --short HEAD
# 7fcc14d
```

Week2 当前仍在本地工作树中，尚未创建新的里程碑 commit。

### 变更文件清单

- `static/js/aiops-visualizer.js`: AIOps 诊断流程可视化组件。
- `static/styles_aiops.css`: AIOps visualizer 样式。
- `static/js/permission-viewer.js`: 权限状态三色可视化组件。
- `static/styles.css`: 权限三色卡片样式。
- `static/index.html`: 加载 AIOps visualizer 和 PermissionViewer 静态资源。
- `static/app.js`: 接入 AIOps SSE visualizer 和权限 viewer。
- `tests/test_assistant_frontend_optimization.py`: 静态前端契约覆盖 AIOps visualizer 和 PermissionViewer。

### 代码审查清单

参考 `docs/code_review_checklist.md`:

- [x] 功能性: Week2 Day1-Day4 需求点已落地。
- [x] 代码质量: 保持静态前端既有结构，没有引入新的前端框架。
- [x] 测试: 静态契约、JS 语法、浏览器 DOM smoke 和全量本地回归已覆盖。
- [x] 文档: baseline / scorecard / compare / evidence 已补齐。

**Review结论**: Local acceptance passed; external review not performed.

---

## 2. 功能验证证据

### 2.1 AIOps Visualizer 浏览器 Smoke

浏览器 smoke 产物:

- `output/playwright/month1_week2_day3_aiops_visualizer/browser_smoke_result.json`
- `output/playwright/month1_week2_day3_aiops_visualizer/01_home_before_aiops.png`
- `output/playwright/month1_week2_day3_aiops_visualizer/02_aiops_visualizer_complete.png`

关键结果:

- [x] visualizer container 可见。
- [x] flow container 可见。
- [x] completed steps = `3`。
- [x] running steps after completion = `0`。
- [x] failed steps = `0`。
- [x] tool call visible = `true`。
- [x] progress text = `100%`。
- [x] final report visible = `true`。
- [x] late status after completion did not reopen running state。
- [x] no unexpected console error。

### 2.2 Permission Viewer 浏览器 DOM Smoke

浏览器 smoke 产物:

- `output/playwright/month1_week2_day4_permission_viewer/browser_smoke_result.json`

关键结果:

- [x] viewer visible = `true`。
- [x] granted cards = `3`。
- [x] requestable cards = `2`。
- [x] forbidden cards = `2`。
- [x] request buttons = `2`。
- [x] quick KB prefill = `guide`。
- [x] advanced resource prefill = `database_demo.list_tables`。
- [x] advanced action prefill = `use`。
- [x] error cards = `0`。
- [x] console errors = `0`。

说明: Day4 截图接口在 in-app browser CDP 路径连续超时，因此 Day4 浏览器证据以 JSON DOM smoke 为准。

### 2.3 自动化测试

全量本地回归:

```bash
uv run pytest -q --no-cov
# exit 0, passed
```

前端静态契约:

```bash
uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov
# 33/33 passed
```

JS 语法:

```bash
node --check static/js/permission-viewer.js
node --check static/js/aiops-visualizer.js
node --check static/app.js
node --check static/js/error-handler.js
node --check static/js/loading-states.js
node --check static/js/trace-utils.js
# all passed
```

Diff whitespace:

```bash
git diff --check
# passed
```

---

## 3. 回归测试证据

### 3.1 现有测试套件

```bash
uv run pytest -q --no-cov
# exit 0
```

### 3.2 前端 Smoke / Contract

- AIOps visualizer: browser smoke JSON pass。
- Permission viewer: browser DOM smoke JSON pass。
- Frontend static contract: 33/33 pass。

### 3.3 RAG / Permission / AIOps 边界

- RAG 默认值保持 `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3`。
- Day2/Day3 AIOps visualizer 不改变 `/api/aiops` 后端协议、planner/executor/replanner 或 live MCP 诊断质量。
- Day4 PermissionViewer 不改变后端 `PermissionService`、grant、审批队列、ToolGateway 或数据库权限链路。

---

## 4. 文档同步证据

- [x] `Month1_执行清单.md` 已更新。
- [x] `PROJECT_STATE.md` 已更新。
- [x] `DEVELOPMENT_LOG.md` 已更新。
- [x] `task_plan.md` / `findings.md` / `progress.md` 已更新。
- [x] `docs/rag_fusion_development_record.md` 已更新。
- [x] `docs/baselines/baseline_month1_week2_acceptance.md` 已创建。
- [x] `docs/scorecards/scorecard_month1_week2_acceptance.md` 已创建。
- [x] `docs/compare-reports/compare_month1_week2_acceptance.md` 已创建。

---

## 5. 风险与遗留问题

### 5.1 已知问题

**问题1**: Remote GitHub Actions 未在远端执行。

- 影响范围: 远程 CI 状态。
- 严重程度: P2。
- 状态: `external-blocked`，记录为 `EXT-M1-CI-REMOTE`。

**问题2**: Day4 permission viewer 截图未生成。

- 影响范围: 视觉 PNG 证据。
- 严重程度: P3。
- 当前处理: JSON DOM smoke 已落盘并覆盖功能状态、预填行为和 console error。

### 5.2 技术债务

- Week2 前端仍是静态 HTML/CSS/JS 架构；Month3 已规划前端模块化重构，不在 Week2 临时扩大重构面。
- AIOps visualizer 的 live AIOps 诊断质量仍需后续 AIOps 质量验收覆盖；Week2 只证明前端 consumer / DOM 行为。
