# Week 0: 执行准备清单

**目标**: 在开始 Month 1 之前，建立生产级开发的治理、评测、证据链和外部依赖 fallback 机制。

**周期**: 5 个工作日。

**当前状态**: in_progress。

**硬规则**:

- 只服务当前主线: `Week0_准备清单.md` -> `Month1_执行清单.md` -> `Month2_执行清单.md` -> `Month3_执行清单.md`。
- 旧计划只可作为历史证据或参考，不可直接执行。
- 外部依赖、人工确认、权限不足统一标记 `external-blocked`，并继续推进本地 fallback。
- 任何 RAG 默认值、rerank、query rewrite、retrieval 策略、前端架构变更都必须经过 baseline -> compare -> gate。

---

## Day 1: 外部依赖与当前基线确认

### 任务 1.1: 语料来源验证与 fallback

**当前决策**: 联系人信息不可用时不等待内部语料，直接使用公开语料 fallback。

**验收清单**:

- [x] 创建 `docs/external_dependencies.md`
- [x] 创建 `docs/external_blocked_registry.md`
- [x] 内部语料联系人不可用时标记 `external-blocked`
- [x] 明确公开语料 fallback: SRE / Kubernetes / Redis / MySQL / Prometheus / incident runbook
- [x] 创建公开语料 manifest 模板或首批 manifest: `docs/public_corpus_manifest_week0_20260618.md`
- [x] 每个公开语料记录 source URL、license、collected_at、domain、synthetic 标记

**不得做**:

- 不得把 license 不清楚的网页直接导入生产级 corpus。
- 不得用 synthetic docs 冒充真实企业语料。

### 任务 1.2: API 依赖验证

**当前决策**:

- 使用本地 `.env` 中的 `DASHSCOPE_API_KEY`。
- Embedding 继续按项目既有 `text-embedding-v4` 路线验证。
- Rerank 对比使用本地 lexical 与百炼文本 rerank 候选，不直接改默认值。
- 百炼文本 rerank 优先候选: `qwen3-rerank`；旧 `gte-rerank-hybrid` 只作为知识库/Retrieve API 历史参数参考，不作为直接文本 rerank 首选。

**验收清单**:

- [x] 本地环境可读取 `DASHSCOPE_API_KEY`
- [x] text-embedding-v4 smoke 或现有 embedding 配置验证通过
- [x] 百炼 rerank smoke 验证通过或记录失败
- [x] `docs/compare-reports/` 中记录 local lexical vs Bailian rerank 的对比计划或结果: `compare_week0_embedding_rerank_smoke_20260618.md`
- [x] API 失败 fallback: local lexical rerank

**external-blocked 处理**:

- 费用预算、人为审批、账号套餐限制不能本地确认时，记录到 `docs/external_blocked_registry.md`，但不阻塞本地 lexical baseline。

### 任务 1.3: 当前服务与 MCP 基线

**验收清单**:

- [x] FastAPI 本地服务健康: `http://127.0.0.1:9900/health`
- [x] MCP CLS 端口就绪: `127.0.0.1:8003`
- [x] MCP Monitor 端口就绪: `127.0.0.1:8004`
- [x] 明确裸 `GET /mcp` 返回 406 不等于 FastMCP streamable-http 失败
- [x] 运行真实 MCP tool discovery 或保留到 Month1 本地任务: 2026-06-14 已有真实 `get_mcp_tools` 返回 16 工具记录；本轮 `make start` + 端口状态确认可用

---

## Day 2: 计划治理与状态外化

### 任务 2.1: 当前主线注册

**验收清单**:

- [x] 生成 `docs/plan_adoption_report.md`
- [x] 创建 `docs/plan_registry.md`
- [x] 创建 `docs/plan_timeline_report.md`
- [x] 明确当前权威主线为 Week0 -> Month1 -> Month2 -> Month3
- [x] 明确旧计划默认不进入当前执行线
- [ ] 每次计划生命周期变化后刷新 registry/timeline

### 任务 2.2: GitHub Projects 或本地 fallback

**当前状态**:

- GitHub remote: `git@github.com:cici-uu8/agent.git`
- `gh auth` 当前账号具备 `project` scope。

**验收清单**:

- [x] 如 GitHub Projects 可写，创建或同步项目看板: `gh project view 1 --owner cici-uu8` 可读，项目 `SuperBizAgent 生产级开发` 已存在且有 4 items
- [x] 如 GitHub Projects 不可用，使用 `docs/plan_registry.md`、执行清单、weekly review 作为本地 source of truth
- [x] GitHub Projects 不可用不得阻塞 Week0/Month1 本地任务

### 任务 2.3: 自动化进度报告脚本

**验收清单**:

- [x] 创建 `scripts/weekly_review.py`
- [x] 运行 `.venv/bin/python scripts/weekly_review.py`
- [x] 生成 `docs/weekly_reviews/weekly_review_auto_*.md`
- [x] 报告包含治理文件、主线 checklist、证据目录、服务健康和 git snapshot

---

## Day 3: 评测体系与证据链模板

### 任务 3.1: 评测目录结构

**验收清单**:

- [x] 创建 `docs/scorecards/`
- [x] 创建 `docs/baselines/`
- [x] 创建 `docs/compare-reports/`
- [x] 创建 `docs/weekly_reviews/`
- [x] 创建 `docs/milestones/`

### 任务 3.2: 模板文件

**验收清单**:

- [x] 创建 `docs/scorecards/scorecard_template.md`
- [x] 创建 `docs/baselines/baseline_template.md`
- [x] 创建 `docs/compare-reports/compare_template.md`
- [x] 创建 `docs/weekly_reviews/weekly_review_template.md`
- [x] 确认 `docs/milestone_evidence_template.md` 存在
- [x] 创建 `docs/code_review_checklist.md`

### 任务 3.3: Week0 首批证据

**验收清单**:

- [x] 创建 `docs/scorecards/scorecard_week0_governance_20260618.md`
- [x] 创建 `docs/baselines/baseline_week0_current_state_20260618.md`
- [x] 创建 `docs/compare-reports/compare_week0_plan_alignment_20260618.md`
- [x] 创建 `docs/scorecards/scorecard_week0_rag_eval_matrix_20260618.md`
- [x] 创建 `docs/compare-reports/compare_week0_embedding_rerank_smoke_20260618.md`
- [x] Week0 scorecard 从 pending 更新为 pass/fail

### 任务 3.4: RAG 全链路评测原则

所有后续 RAG 功能必须分别建立 baseline、候选方案和 compare gate：

- [x] embedding: text-embedding-v4 当前配置、企业语料覆盖、失败样本分布、是否需要微调/继续预训练的证据
- [x] retrieval: dense / sparse / hybrid / residual chunk probe 对比
- [x] rerank: local lexical / Bailian qwen3-rerank / fallback 对比
- [x] query rewrite: off / rule-based / LLM intent/rewrite shadow 对比
- [x] answer: deterministic hard gate + 可选 LLM judge shadow，不替代主 gate
- [x] frontend: 架构、交互、错误、加载、trace、可维护性 scorecard
- [x] ops: 性能、长期运行、日志增长、备份恢复、限流降级 scorecard

**Week0 证据**: `docs/scorecards/scorecard_week0_rag_eval_matrix_20260618.md` 定义所有模块评测矩阵；Month1/Month2 执行时再分别落具体 baseline 和 compare。

---

## Day 4: 风险触发器与 compare gate

### 任务 4.1: 风险触发器

**验收清单**:

- [x] 创建 `docs/risk_triggers.md`
- [x] 定义 red line / yellow line
- [x] 明确安全硬门禁: permission / scope / source_ref 失败立即阻断推广
- [x] 明确 RAG 质量 regression 触发 compare/rollback

### 任务 4.2: Compare Gate 流程

固定流程:

1. 记录 baseline。
2. 跑候选方案。
3. 生成 compare report。
4. 判定 promote / keep-shadow / reject / rollback / external-blocked。
5. 更新 active checklist、`PROJECT_STATE.md`、weekly review。

**验收清单**:

- [x] compare 模板已创建
- [x] Week0 plan alignment compare 已创建
- [x] Month1 Day1 默认值 gate 已改为候选对比，而不是直接启用 hybrid

---

## Day 5: Kickoff 与进入 Month1 条件

### 任务 5.1: 环境准备

**验收清单**:

- [x] Python 版本确认
- [x] Node 版本确认
- [x] Docker / Milvus 当前状态确认
- [x] `.venv/bin/python scripts/weekly_review.py` 通过
- [x] 关键默认值测试通过: `tests/test_checklist2_production_defaults.py`
- [x] 文档静态检查或 `git diff --check` 通过

### 任务 5.2: Week0 最终验收

Week0 进入 Month1 的最低条件:

- [x] 当前主线 registry/timeline 已建立
- [x] old plans 不会被当作当前执行线
- [x] scorecard / baseline / compare / weekly review 模板已建立
- [x] external-blocked 机制已建立
- [x] weekly review 脚本能跑并生成报告
- [x] Month1 Day1 已改成 evidence-first，不再要求直接启用 hybrid 默认
- [x] `PROJECT_STATE.md` 记录当前主线和下一步
- [x] `DEVELOPMENT_LOG.md` 记录 Week0 落地结果

**通过后执行**:

```bash
.venv/bin/python scripts/weekly_review.py
git diff --check
```

**下一步**: 打开 `Month1_执行清单.md`，从 Week 1 Day 1 的 baseline / compare gate 开始，不直接更改生产默认值。
