# Week 1 Evidence: Month1 User Experience Repair

**里程碑名称**: Month1 Week1 用户体验修复 P0
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
# c6d4211
```

Week1 当前仍在本地工作树中，尚未创建新的里程碑 commit。

### 变更文件清单

- `static/js/error-handler.js`: 前端错误分类、normalize、error-card 渲染。
- `static/styles_error.css`: error-card 样式。
- `static/js/loading-states.js`: chat / file_upload / aiops loading states。
- `static/styles_loading.css`: loading card、progress bar、overlay loading 样式。
- `static/js/trace-utils.js`: frontend trace/request id 注入与 console log。
- `static/index.html`: 新增 error/loading/trace 静态资源加载。
- `static/app.js`: 接入 error/loading/trace，并修复 Day5 发现的错误卡片浏览器渲染退化。
- `tests/test_assistant_frontend_optimization.py`: 静态前端契约覆盖 error/loading/trace 和错误卡片渲染路径。

### 代码审查清单

参考 `docs/code_review_checklist.md`:

- [x] 功能性: Week1 P0 需求点已落地。
- [x] 代码质量: 保持静态前端既有结构，没有引入新的前端框架。
- [x] 测试: 静态契约测试和浏览器 smoke 覆盖新增路径。
- [x] 文档: baseline / scorecard / compare / evidence 已补齐。

**Review结论**: Local acceptance passed; external review not performed.

---

## 2. 功能验证证据

### 2.1 手动 / 浏览器测试

浏览器 smoke 产物:

- `output/playwright/month1_week1_day5_smoke/browser_smoke_result.json`
- `output/playwright/month1_week1_day5_smoke/browser_smoke_cli_output.md`
- `output/playwright/month1_week1_day5_smoke/01_home.png`
- `output/playwright/month1_week1_day5_smoke/02_logged_in.png`
- `output/playwright/month1_week1_day5_smoke/03_file_manager.png`
- `output/playwright/month1_week1_day5_smoke/04_chat_loading_success.png`
- `output/playwright/month1_week1_day5_smoke/05_error_trace.png`

关键结果:

- [x] 首页输入框可见。
- [x] demo 用户登录后用户名可见。
- [x] 用户菜单包含文件管理。
- [x] 文件管理弹窗可见。
- [x] chat loading state 在请求期间可见。
- [x] chat 请求完成后 loading state 清理。
- [x] 500 错误渲染 `.error-card`。
- [x] 错误卡片显示 `trace-browser-error`。
- [x] `/api/auth/me` 和 `/api/chat` 请求带 `x-trace-id` / `x-request-id`。
- [x] 无非预期 console error；故意触发的 500 error 已从异常计数中排除。

### 2.2 自动化测试

全量本地回归:

```bash
uv run pytest -q --no-cov
# passed, no failures
```

前端静态契约:

```bash
uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov
# 32/32 passed
```

JS 语法:

```bash
node --check static/app.js
node --check static/js/error-handler.js
node --check static/js/loading-states.js
node --check static/js/trace-utils.js
# all passed
```

### 2.3 21 场景桌面技术 smoke

```bash
uv run python smoke_test_desktop_beta.py
# 总计: 21/21 通过 (100.0%)
```

报告:

- `output/smoke_test/普通用户任务_smoke_test.json`: `11/11`
- `output/smoke_test/Admin任务_smoke_test.json`: `8/8`
- `output/smoke_test/观察员任务_smoke_test.json`: `2/2`

### 2.4 RAG Baseline / Compare

Week1 不改变 RAG 默认值。检索候选对比证据:

- `docs/baselines/baseline_month1_retrieval_defaults.md`
- `docs/scorecards/scorecard_month1_retrieval_strategy.md`
- `docs/compare-reports/compare_month1_retrieval_candidates.md`

门禁检查:

- [x] 默认值仍为 `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3`。
- [x] hybrid / hybrid_rerank 未提升为默认。
- [x] retrieval compare 已给出 keep-shadow / reject 决策。

---

## 3. 回归测试证据

### 3.1 现有测试套件

```bash
uv run pytest -q --no-cov
# passed
```

### 3.2 前端 Smoke 测试

**21个场景结果**: 21/21 Pass

- 普通用户任务: 11/11
- Admin 任务: 8/8
- 观察员任务: 2/2

### 3.3 Day5 发现并修复的问题

问题: 浏览器模拟 `/api/chat` 500 时，trace 文本可见，但 `.error-card` DOM 没有出现。

根因: `renderErrorMessage()` 返回可信内部 HTML，但 `addMessage('assistant', ...)` 会把 assistant 内容统一送入 Markdown 渲染，导致结构化 error-card 被降级。

修复: `sendMessage()` catch 分支创建空 assistant 消息，然后直接将 `renderErrorMessage(...)` 写入该消息的 `.message-content.innerHTML`。普通 assistant 回答仍走 Markdown 渲染。

复验: `browser_smoke_result.json` 中 `error_card_visible=true`、`error_trace_visible=true`。

---

## 4. 文档同步证据

- [x] `Month1_执行清单.md` 已更新。
- [x] `PROJECT_STATE.md` 已更新。
- [x] `DEVELOPMENT_LOG.md` 已更新。
- [x] `task_plan.md` / `findings.md` / `progress.md` 已更新。
- [x] `docs/plan_registry.md` / `docs/plan_timeline_report.md` 已更新。
- [x] `docs/baselines/baseline_month1_week1_acceptance.md` 已创建。
- [x] `docs/scorecards/scorecard_month1_week1_acceptance.md` 已创建。
- [x] `docs/compare-reports/compare_month1_week1_acceptance.md` 已创建。

---

## 5. 风险与遗留问题

### 5.1 已知问题

**问题1**: Remote GitHub Actions 未在远端执行。

- 影响范围: 远程 CI 状态。
- 严重程度: P2。
- 状态: `external-blocked`，记录为 `EXT-M1-CI-REMOTE`。

**问题2**: `make start-api` / `make restart` 的 FastAPI 启动仍使用 plain `nohup`。

- 影响范围: 当前命令运行器中的本地服务生命周期。
- 严重程度: P2。
- 当前处理: 本轮用 independent session 启动并复验 `/health`。
- 后续建议: 若 Week2/后续 smoke 依赖频繁重启，应把 FastAPI 启动迁移到与 `scripts/mcp_service.py` 类似的 session 管理器。

### 5.2 技术债务

- Week1 前端仍是静态 HTML/CSS/JS 架构；Month3 已规划前端模块化重构，不在 Week1 临时扩大重构面。
- Browser smoke 的 chat success/error 使用 route mock 验证前端行为；真实 LLM answer quality 由 RAG/Answer 评测体系覆盖，不在 Week1 frontend P0 gate 内。
