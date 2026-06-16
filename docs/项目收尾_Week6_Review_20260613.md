# 项目收尾 Week 6 Review

日期：2026-06-13

## 1. 结论

P0 文件管理闭环和 P1 Trace 浏览器核心功能已经完成。Week 6 触发条件审计结论是：当前不启动 P2 数据库查看 UI，不启动 P3 Memory 可见性，不启动成本控制 dashboard、路由 promote、AIOps 生产级升级或 Skill 工程。

当前项目进入维护 / Beta 支持状态：继续观察真实 Beta 反馈，按月复核触发条件，保持默认配置 `dense_only / off / false` 不变。

## 2. P0/P1 完成状态

| 项目 | 状态 | 证据 |
|---|---|---|
| P0a 文件管理台 | 已完成基础版 | `/api/documents` 分页、状态、失败原因、trace 字段；前端文件管理入口和轮询 |
| P0b 上传后健康检查 | 已完成基础版 | indexed 后非阻塞健康检查；retrieval/source_ref/PDF 诊断；健康度 UI 和误报记录 |
| P1.1 Trace 基础版 | 已完成基础版 | `GET /api/admin/traces/{trace_id}` 聚合 routing + retrieval，缺失来源显示 `not_recorded` |
| P1.2 Trace 完整版 | 已完成基础版 | trace_id/request_id 查询、8 类来源聚合、source_ref 状态、脱敏、过滤、复制和 `GET /api/admin/traces/compare` |

## 3. Beta 数据

当前 `docs/RAG_Beta_User_Feedback_Log.md` 只有 Week 1 真人反馈记录：

| 指标 | 当前值 |
|---|---:|
| beta 用户角色 | 3 |
| total queries | 11 |
| retrieval success | 9/11 (81.8%) |
| average satisfaction | 4.09/5 |
| source_ref issues | 0 |
| permission/scope issues | 0 |

Week 2-4 尚无正式真人反馈记录。当前 Week 1 问题类型都没有达到同类 confirmed >= 3 的专项优化触发线。

## 4. P2/P3 前置条件

### P2 数据库查看 UI

结论：不启动。

原因：

- 当前 `enterprise_mysql_enabled=False`。
- `docs/database_operation_capability_plan.md` 仍将真实企业库接入放在 DB-P2 之后。
- 已有能力是 sandbox / database-demo / 非生产 smoke，不等于真实只读业务库。
- 缺少已确认的真实只读数据源、read-only account、data owner、permission owner、allowlist、masking 规则和 safety smoke 计划。

### P3 Memory 可见性

结论：不启动。

原因：

- 当前 `rag_session_memory_mode="off"`。
- 现有 shadow / synthetic active candidate 只能证明链路可观测，不是生产 active 批准。
- 缺少真实长会话 evidence、active 审批和生产 rollback / cleanup / capacity 运行记录。

## 5. 延后项触发条件

| 延后项 | 触发条件 | 当前状态 | 结论 |
|---|---|---|---|
| 成本控制 dashboard | Beta >= 20 人，运行 >= 1 月，且有明确成本/延迟问题 | Week 1 仅 3 个角色 / 11 queries，无成本投诉 | 未触发 |
| 路由 promote | shadow >= 1000 样本，准确率 >= 95%，规则路由误判 >= 3 次 | 无 1000 样本和 95% 准确率证据 | 未触发 |
| AIOps 生产级升级 | lab >= 100 次，稳定性 >= 90%，owner 要求接入生产监控 | 无 owner 接入生产监控要求 | 未触发 |
| Skill 工程 | 用户手写 >= 3 个自定义技能 | 无该证据 | 未触发 |

## 6. 长期运行边界复核

| 边界 | 当前证据 | 结论 |
|---|---|---|
| audit / trace 存储 | `logs/enterprise_audit.sqlite` 18M，`logs/enterprise_audit.jsonl` 15M；27026 events，4464 trace_id，4592 request_id | 低于 100MB 本地压缩/归档触发线 |
| trace 时间跨度 | 2026-05-30 到 2026-06-13 | 仍在 30 天 Review 窗口内 |
| 健康检查结果存储 | 默认路径 `uploads/_metadata/document_health_checks.json`，当前本地未发现结果文件 | 机制已接入；运行样本仍需 Beta 上传后积累 |
| 健康检查队列 | `max_queue_size=100`，`max_concurrent=10` | 第一版限流边界已落地 |
| Trace 权限/脱敏 | Admin API scope 过滤，敏感字段脱敏，database/memory/SSE 原文摘要化 | 第一版权限审计边界已落地 |
| 默认配置漂移 | `tests/test_checklist2_production_defaults.py` 通过 | 当前未发现默认配置漂移 |

## 7. 决策

1. P0/P1 进入维护和 Beta 支持，不继续扩大当前范围。
2. P2 只在真实只读数据库源、owner、allowlist、masking、audit 和 safety smoke 计划齐备后启动。
3. P3 只在 Memory active 审批、真实长会话 evidence、rollback、cleanup/capacity 记录齐备后启动。
4. 延后项继续按触发条件月度 Review，不因能力存在而启动产品面。
5. 默认配置继续锁定：`rag_default_retrieval_mode=dense_only`、`rag_query_rewrite_mode=off`、`rerank_enabled=False`、`rag_session_memory_mode=off`、`tool_result_offload_enabled=False`、`pdf_agent_tools_enabled=False`。

## 8. 下一步

- 继续 Beta 真实反馈收集，按 `docs/RAG_Internal_Beta_Runbook_20260612.md` 周度 Review。
- 每月复核 P2/P3/延后项触发条件。
- 若出现真实数据库 owner 和只读源，先补 P2 API/UI contract，不直接做完整 UI。
- 若出现 Memory active 申请，先补 active enablement / rollback / cleanup / capacity 记录，不直接做用户可见 Memory 面板。
