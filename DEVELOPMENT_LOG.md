# SuperBizAgent 生产级开发日志

## 项目目标
3个月完整迭代，达到生产级质量

## 执行路径
路径C（完整迭代）

## 开始日期
2026-06-17

---

## 历史记录（开发体系启动前）

### 2026-06-16 至 2026-06-17: 项目最后优化2
**执行周期**: 2天
**状态**: ✅ 完成并验收

**完成任务**:
- ✅ P0a: Memory Operator后端API（7/7 tests passed）
- ✅ P0b: Memory Operator UI（37/37 tests passed）
- ✅ P1: Database Catalog Browser（46/46 tests passed）
- ✅ P2: Ops Dashboard基础版（46/46 tests passed）
- ✅ 数据库v2 Stage 1-4完成（235 tests passed）

**详见**: `历史完成记录.md`

**对生产级开发的影响**:
- Month 2 Week 6部分任务已完成
- 预计节省约5天时间
- 可用作缓冲或加速后续任务

---

## Week 0: 准备周

**开始日期**: 2026-06-17
**目标**: 建立执行保障机制

### 准备工作
- ✅ 2026-06-17: Git仓库初始化
- ✅ 2026-06-17: 创建enterprise3开发分支
- ✅ 2026-06-17: 保存基线commit (496fec9)
- ✅ 2026-06-17: 创建完整开发文档体系（11个文档）
- ✅ 2026-06-17: 同步历史完成记录
- ✅ 2026-06-17: 初始化DEVELOPMENT_LOG.md（本文件）

### Day 1: 外部依赖零信任验证
**日期**: 2026-06-18
**状态**: ✅ 完成

**任务清单**:
- [x] 联系数字化部门确认语料来源: 联系人不可用，记为 `external-blocked`
- [x] 联系工艺部门确认语料来源: 联系人不可用，记为 `external-blocked`
- [x] 公开技术文档license确认: `docs/public_corpus_manifest_week0_20260618.md`
- [x] DashScope API密钥申请和测试: 本地 `.env` 可用，`text-embedding-v4` 和 `qwen3-rerank` smoke 通过
- [x] MCP工具清单确认: fresh discovery 返回 16 tools
- [x] 填写 `docs/external_dependencies.md`

**记录区**:
- `docs/external_blocked_registry.md` 记录联系人、GitHub Projects、API预算 fallback。
- `docs/compare-reports/compare_week0_embedding_rerank_smoke_20260618.md` 记录 embedding/rerank smoke。
- 运行时默认值仍保持 `dense_only / off / false / top_k=3`。

---

### Day 2: 搭建状态外化仪表盘
**日期**: 2026-06-18
**状态**: ✅ 完成

**任务清单**:
- [x] 创建GitHub Projects看板: `SuperBizAgent 生产级开发` 已存在，project id 1
- [x] 添加P0/P1/P2任务卡片: 当前 project 有 4 items；本地清单仍为 source of truth
- [x] 创建 `scripts/weekly_review.py`
- [x] 测试weekly_review脚本

**记录区**:
- `gh project view 1 --owner cici-uu8` 可读。
- latest weekly review: `docs/weekly_reviews/weekly_review_auto_20260618_102347.md`。

---

### Day 3: 定义证据链模板
**日期**: 2026-06-18
**状态**: ✅ 完成

**任务清单**:
- [x] 确认milestone_evidence_template.md可用
- [x] 创建 `docs/code_review_checklist.md`
- [x] 定义Code Review流程

**记录区**:
- scorecard / baseline / compare / weekly review 模板均已建立。
- `docs/scorecards/scorecard_week0_rag_eval_matrix_20260618.md` 明确所有 RAG/frontend/ops 模块都必须有评测体系。

---

### Day 4: 设置纠偏触发器
**日期**: 2026-06-18
**状态**: ✅ 完成

**任务清单**:
- [x] 设置日历提醒（每周五Weekly Review）: Codex 侧以 weekly review 脚本和清单门禁替代
- [x] 创建 `docs/risk_triggers.md`
- [x] 定义红线/黄线触发器

**记录区**:
- compare gate 固定为 baseline -> candidate -> compare -> promote/keep-shadow/reject/rollback/external-blocked。

---

### Day 5: Kickoff准备
**日期**: 2026-06-18
**状态**: ✅ 完成

**任务清单**:
- [x] 打印工作计划（或导出PDF）: 以主控文档 + registry/timeline 作为当前工作台
- [x] 确认开发环境就绪
- [x] 运行测试确认: targeted defaults/rerank tests 通过
- [x] 个人Kickoff（回顾12周计划）: 主线锁定为 Week0 -> Month1 -> Month2 -> Month3

**记录区**:
- `.venv/bin/python --version`: Python 3.13.3。
- `node --version`: v23.11.0。
- Docker/Milvus/Redis healthy。
- `uv run pytest tests/test_checklist2_production_defaults.py tests/test_p3_rerank_service.py -q --no-cov` 8/8。
- `git diff --check` 通过。

---

### Week 0 最终验收
**验收日期**: 2026-06-18
**验收状态**: ✅ 通过

**验收清单**:
- [x] 外部依赖已验证或有Fallback
- [x] GitHub Projects看板就绪
- [x] weekly_review.py能跑
- [x] 所有模板文档已创建
- [x] Weekly Review机制已建立
- [x] 开发环境就绪

**验收通过**: ✅ 是

**下一步**: Month 1 Week 1 Day 1，从 retrieval defaults baseline / compare gate 开始，不直接改默认值。

---

## Month 1: 紧急止血 + 核心强化

Week0 已通过，Month1 Week1 Day1 已启动。

### Week 1 Day 1: Retrieval compare and coverage baseline
**日期**: 2026-06-18
**状态**: ✅ 本地可执行项完成；远端 CI 触发 external-blocked

**已完成**:
- [x] 写入 `docs/baselines/baseline_month1_retrieval_defaults.md`
- [x] 写入 `docs/scorecards/scorecard_month1_retrieval_strategy.md`
- [x] 写入 `docs/compare-reports/compare_month1_retrieval_candidates.md`
- [x] 创建 `.github/workflows/ci.yml`
- [x] 全量覆盖率基线: `uv run pytest --cov=app --cov-report=html --cov-report=term` 通过，952 passed，coverage 84.45%

**Retrieval compare结论**:
- `dense_only`: 51/54 expected_doc_found，P95 1430ms，继续作为默认基线。
- `sparse_only`: 35/54，速度快但覆盖损失大，不能作为默认。
- `hybrid`: 52/54，有 +1/54 lift，但 P95 3580ms、max 27349ms，keep-shadow。
- `hybrid_rerank`: 36/54，rerank applied=161，但代表性质量下降，不能作为默认。

**external-blocked**:
- GitHub Actions 远端 push/运行验证依赖 GitHub auth/push 条件，已记录为 `EXT-M1-CI-REMOTE`。本地 fallback 是 CI 文件 + 全量 pytest coverage gate。

**下一步**:
- 进入 Month1 Week1 Day2 前端错误提示分级系统。

### Week 1 Day 2: 前端错误提示分级系统
**日期**: 2026-06-18
**状态**: ✅ 完成

**已完成**:
- [x] 新增 `static/js/error-handler.js`，提供 `ErrorHandler.classifyError / normalize / renderError / show`
- [x] 新增 `static/styles_error.css`，提供错误卡片红色、黄色、中性分级样式
- [x] `static/index.html` 接入 `styles_error.css` 和 `error-handler.js`
- [x] `static/app.js` 在 API、登录、上传、聊天、AIOps 错误路径中接入统一错误渲染
- [x] `tests/test_assistant_frontend_optimization.py` 锁定静态资源与错误处理入口

**验证**:
- `node --check static/app.js`
- `node --check static/js/error-handler.js`
- `uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov` 32/32

**下一步**:
- 进入 Month1 Week1 Day3 加载状态优化。

### Week 1 Day 3: 前端加载状态优化
**日期**: 2026-06-18
**状态**: ✅ 完成

**已完成**:
- [x] 新增 `static/js/loading-states.js`，提供 `LoadingStateManager` 和 chat / file_upload / aiops 三类阶段状态
- [x] 新增 `static/styles_loading.css`，提供 loading card、progress bar 和 overlay/compact 样式
- [x] `static/index.html` 接入 `styles_loading.css` 和 `loading-states.js`
- [x] `static/app.js` 在聊天、上传、AIOps 加载路径中接入 `loadingStateManager`
- [x] `tests/test_assistant_frontend_optimization.py` 锁定 loading 静态资源、三类状态和集成入口
- [x] 新增 loading baseline / scorecard / compare 证据:
  - `docs/baselines/baseline_month1_frontend_loading_current_state.md`
  - `docs/scorecards/scorecard_month1_frontend_loading_state.md`
  - `docs/compare-reports/compare_month1_frontend_loading_state.md`

**验证**:
- `node --check static/app.js`
- `node --check static/js/loading-states.js`
- `uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov` 32/32
- `git diff --check`
- Playwright smoke: 页面加载 `loadingStateManager`，chat loading card 从 `30%` 进入 `60%` 阶段并可 stop 清理
- `.venv/bin/python scripts/weekly_review.py` 生成 `docs/weekly_reviews/weekly_review_auto_20260618_111556.md`

**下一步**:
- 进入 Month1 Week1 Day4 trace_id 全局追踪。

### Week 1 Day 4: 前端 trace_id 全局追踪
**日期**: 2026-06-18
**状态**: ✅ 完成

**已完成**:
- [x] 新增 `static/js/trace-utils.js`，提供 `TraceManager`、`X-Trace-Id` / `X-Request-Id` 注入和 console request/response log
- [x] `static/index.html` 在 head 中最先加载 `trace-utils.js`
- [x] `static/app.js` 保存 `traceManager` 引用，错误 normalize 可继承 traceId / requestId
- [x] `static/js/error-handler.js` 支持 `error.traceId` / `error.trace_id`
- [x] `tests/test_assistant_frontend_optimization.py` 锁定 trace 静态资源、加载顺序、header 注入和错误 trace 提取
- [x] 新增 trace baseline / scorecard / compare 证据:
  - `docs/baselines/baseline_month1_frontend_trace_current_state.md`
  - `docs/scorecards/scorecard_month1_frontend_trace_id.md`
  - `docs/compare-reports/compare_month1_frontend_trace_id.md`

**验证**:
- `node --check static/js/trace-utils.js`
- `node --check static/app.js`
- `node --check static/js/error-handler.js`
- `uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov` 32/32
- `git diff --check`
- Playwright smoke: `/api/auth/me` 请求头包含 `x-trace-id` / `x-request-id`，console 显示 trace request/response log，错误卡片可显示 trace_id

**下一步**:
- 进入 Month1 Week1 Day5 Week1 验收测试。

### Week 1 Day 5: Week1 本地验收测试
**日期**: 2026-06-18
**状态**: ✅ 本地验收通过

**已完成**:
- [x] 全量本地回归: `uv run pytest -q --no-cov` 通过
- [x] 前端静态语法: `node --check static/app.js static/js/error-handler.js static/js/loading-states.js static/js/trace-utils.js` 通过
- [x] 前端静态契约: `uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov` 32/32
- [x] 桌面技术 smoke: `uv run python smoke_test_desktop_beta.py` 21/21
- [x] 浏览器层 smoke: `output/playwright/month1_week1_day5_smoke/browser_smoke_result.json` 所有布尔检查通过
- [x] 里程碑证据: `docs/milestones/week1_evidence.md`
- [x] Week1 baseline / scorecard / compare:
  - `docs/baselines/baseline_month1_week1_acceptance.md`
  - `docs/scorecards/scorecard_month1_week1_acceptance.md`
  - `docs/compare-reports/compare_month1_week1_acceptance.md`

**Day5发现并修复**:
- 浏览器 smoke 初次发现 `/api/chat` 500 时 trace 文本可见，但 `.error-card` DOM 没有渲染。
- 根因: `renderErrorMessage()` 返回可信内部 HTML，但 `addMessage('assistant', ...)` 会把 assistant 消息统一送入 Markdown 渲染，导致结构化错误卡片退化。
- 修复: `sendMessage()` catch 分支创建空 assistant 消息，并把 `renderErrorMessage(...)` 直接写入该消息的 `.message-content.innerHTML`；普通 assistant 回答仍走 Markdown。
- 复验: `error_card_visible=true`、`error_trace_visible=true`、`trace_header_on_auth_or_chat=true`。

**边界**:
- Remote GitHub Actions 仍为 `EXT-M1-CI-REMOTE` external-blocked。
- RAG 默认值未变更: `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3`。
- `make start-api` / `make restart` 的 FastAPI plain `nohup` 生命周期风险已记录，当前运行态使用 independent session 保持健康；不作为 Week1 产品行为阻塞。

**下一步**:
- 进入 Month1 Week2 Day1 AIOps诊断流程可视化。

### 2026-06-18 评测体系与 top_k/rerank 矩阵补充

**决策**:
- 评测体系固定为统一治理骨架，但指标按模块分层，不把所有任务套同一组指标。
- RAG 策略评测必须拆开 Retrieval / Rerank / Answer / 工程指标。
- Month1 Week3 前置新增 `retrieval_top_k / rerank_top_n / final_context_k` shadow compare gate。
- Month2 Week5 在 100 docs 语料上复跑同类矩阵，避免小语料结论误导。

**边界**:
- 本次只补充计划和门禁，不改变运行时默认值。
- 当前默认仍为 `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3`。

---

## Month 2: 能力扩展 + 质量保证

（待Month 1完成后开始记录）

---

## Month 3: 技术债清理 + 运维化

（待Month 2完成后开始记录）

---

## 里程碑记录

### Milestone 0: Week 0完成
**日期**: 2026-06-18
**状态**: ✅ 完成

### Milestone 1: Month 1完成
**日期**: ____________
**状态**: ⏸️ 待完成

### Milestone 2: Month 2完成
**日期**: ____________
**状态**: ⏸️ 待完成

### Milestone 3: Month 3完成（生产级交付）
**日期**: ____________
**状态**: ⏸️ 待完成

---

## 问题与决策记录

### 遇到的问题
（记录遇到的问题和解决方案）

### 重要决策
- 当前主线只执行 `Week0_准备清单.md -> Month1_执行清单.md -> Month2_执行清单.md -> Month3_执行清单.md`。
- 旧计划只能作为历史证据，不自动执行。
- 无内部语料联系人时使用公开语料 fallback，但必须记录 URL/license/synthetic/import 状态。
- embedding/rerank smoke 只证明可调用，不改变生产默认值。
- Month1 Day1 必须以 baseline/compare 方式评估 dense/sparse/hybrid/hybrid_rerank。

### 教训与改进
（记录教训和改进措施）

---

**最后更新**: 2026-06-18
**当前阶段**: Month 1 in_progress
**下一步**: Month 1 Week 2 Day 1 - AIOps诊断流程可视化
