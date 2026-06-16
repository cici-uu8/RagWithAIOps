# OpenViking Memory P0 痛点证据

日期: 2026-05-24

## 1. P0 结论

当前结论:

- Gate A.1 real oncall evidence: 未通过。当前没有生产或准生产 oncall session/log/case。
- Gate A.2 pre-launch controlled baseline / product bet: 通过。允许先推进本机可验证的 P1 sidecar memory schema/store，但必须保留“非生产痛点证据”的标签，并在后续真实接入后复评。

本文件不把 synthetic fixture、手写假 session 或 LLM 编造案例当成真实证据。当前 A.2 依据来自本机仓库代码事实、现有 runbook 文档和当前系统缺少跨 session durable memory lookup 的受控基线。

## 2. 已核查范围

本轮核查覆盖:

- `docs/openviking_memory_adaptation_plan.md`
- `docs/memory_fusion_development_record.md`
- `AGENTS.md`
- `PROJECT_STATE.md`
- `app/services/rag_agent_service.py`
- `app/services/aiops_service.py`
- `app/agent/aiops/planner.py`
- `app/agent/aiops/replanner.py`
- `aiops-docs/*.md`
- `tests/*`

代码事实:

- `RagAgentService` 使用 `MemorySaver` 保存 RAG chat 的 thread-scoped message history。
- `RagAgentService.get_session_history(session_id)` 直接解析 `MemorySaver` checkpoint shape，可作为后续 P4 的风险证据，但不是 durable memory 的需求证据。
- `AIOpsService` 使用 `MemorySaver` 保存 Plan-Execute-Replan graph state，并通过 `graph.get_state(config_dict)` 读取最终状态。
- `planner` 已经先调用 `retrieve_knowledge`，再把知识库命中的经验文档放入 `experience_context`。
- `aiops-docs` 已有 HighMemoryUsage / HighDiskUsage / ServiceUnavailable / SlowResponse 等 runbook 类文档，说明文档 KB 已覆盖一部分告警处理经验。

## 3. Gate A.1 real oncall evidence 表

| case_id | occurred_at | alert_or_question | expected_reuse | actual_behavior | document_kb_coverage | memory_saver_enough | code_or_config_solution | why_durable_memory |
|---|---|---|---|---|---|---|---|---|
| P0-CAND-001 | 无真实运行时发生时间；仅为仓库文档样例 | `HighMemoryUsage` / 内存使用率过高 | 如果同类告警重复出现，可能希望复用过去验证过的根因、处理步骤或偏好 | 未找到真实 session、诊断日志或用户反馈证明 agent 第二次仍从零开始 | 已覆盖。`aiops-docs/memory_high_usage.md` 是结构化 runbook，planner 当前会通过 `retrieve_knowledge` 查询经验文档 | 当前证据不足以判断；没有跨 session 对比 | 可以先通过文档 KB / runbook / `retrieve_knowledge` 解决 | 不成立。只有文档样例，没有证明必须新增 durable memory |
| P0-CAND-002 | 无真实运行时发生时间 | 成功诊断计划未复用 | 希望 planner 复用过去成功的 Plan-Execute-Replan 步骤 | 未找到已完成诊断 session 与下一次相似告警的对比记录 | planner 已接入知识库经验文档；是否不足未被样例证明 | `MemorySaver` 能保留当前 session，但没有跨进程持久保证；这只是层级事实，不是痛点证据 | 可以先把成功处理方案写入文档 KB 或 runbook | 不成立。缺少“过去成功计划被忽略”的真实案例 |
| P0-CAND-003 | 无真实运行时发生时间 | 运行时偏好反复重说 | 希望复用用户对语言、引用粒度、报告详细程度的偏好 | 未找到重复偏好输入记录 | 不适用 | 不适用 | 如果偏好稳定，前端配置或请求参数可能更合适 | 不成立。没有反复重说的真实证据 |
| P0-CAND-004 | 无真实运行时发生时间 | 跨 session 运行时上下文丢失 | 希望复用值班人、维护窗口、临时上下文 | 未找到运行时上下文丢失导致错误诊断的案例 | 不适用 | `MemorySaver` 不是 durable store，但没有具体丢失案例 | 对维护窗口等强结构信息，配置或显式请求参数可能更合适 | 不成立。没有非文档型上下文丢失案例 |

## 4. Gate A.2 pre-launch controlled baseline 表

证据类型: `pre_launch_controlled_baseline`

说明: 这些不是生产 oncall 证据。它们说明当前项目在上线前、本机可验证范围内确实没有 durable memory lookup / store / review path，因而 P1 可以作为默认关闭的 sidecar capability 先实现。

| case_id | occurred_at | alert_or_question | expected_reuse | actual_behavior | document_kb_coverage | memory_saver_enough | code_or_config_solution | why_durable_memory |
|---|---|---|---|---|---|---|---|---|
| P0-A2-001 | 2026-05-24 本机代码核查 | 第二次新 session 询问 `HighMemoryUsage` / OOM 类问题 | 如果第一次诊断中已确认根因、处理步骤或现场约束，第二次相似问题应能看到候选经验 | 当前代码没有 durable memory store / lookup；planner 只会重新查 `retrieve_knowledge` 文档经验 | 已有 `aiops-docs/memory_high_usage.md`，覆盖通用 runbook，但不覆盖上一次 session 的现场根因和处理结果 | `MemorySaver` 只按当前 `thread_id` 保存状态，新 session 无法稳定复用旧 session 经验 | 把每次成功诊断都写回 runbook 太重，且会混淆文档事实与运行时经验 | 需要 sidecar memory 记录候选 alert pattern / plan template，默认 candidate，后续人工 review |
| P0-A2-002 | 2026-05-24 本机代码核查 | 新 session 询问 `SlowResponse` / 延迟升高类问题 | 过去成功排查顺序，如先查指标再查日志再判定限流/下游依赖，应作为 plan template 候选 | 当前 planner 只能读取文档 KB 的通用经验，不会读取过去 session 的成功计划 | `aiops-docs` 可提供 runbook，但不表达“本项目上次成功计划” | `AIOpsService` 的 graph state 在当前 `thread_id` 内可用，但没有稳定对外 accessor 或跨 session durable record | 可以把成熟 runbook 写入文档 KB，但 session 级成功计划仍会丢失 | 需要结构化 `plan_template` memory，并带 evidence_refs 和 candidate review |
| P0-A2-003 | 2026-05-24 本机代码核查 | 用户反复要求诊断报告用中文、简洁、列证据边界 | 新 session 应复用运行时偏好，而不是每次重说 | 当前 RAG system prompt 是通用助手提示，AIOps 诊断 prompt 有固定格式；没有 user preference store | 文档 KB 不适合记录临时或团队级运行时偏好 | `MemorySaver` 只能覆盖当前会话 | 如果偏好是全局产品规则，可写配置；但团队/owner 级偏好需要 owner-scoped sidecar | 需要 `preference` memory，但 P5 prompt 注入必须默认关闭并等后续评估 |

## 5. Gate A 判定

Gate A.1 未通过。

原因:

- 没有 3 个相似重复告警案例证明“重复告警每次从零开始”。
- 没有真实 completed diagnosis session 证明“成功诊断计划没有复用”。
- 没有重复用户偏好或跨 session runtime context 丢失的证据。
- 当前可见的告警经验主要存在于 `aiops-docs` 文档 KB，现有 planner 已有 `retrieve_knowledge` 路径。

Gate A.2 通过。

理由:

- 当前产品处于 pre-launch / 本机开发阶段，不能等待生产 oncall 流量作为唯一开工条件。
- 本机代码事实已经证明当前没有跨 session durable memory store / retrieval / review path。
- P1 只实现 sidecar schema/store，不接默认 agent prompt，不改变 `retrieve_knowledge` 和文档 citation。
- 后续必须在首次灰度部署后 30 天，或累计 20 次 AIOps diagnosis 后复评；复评 owner: `runtime owner TBD`。
- 复评不过时，应 deprecated / rollback memory 子系统，而不是继续扩大 rollout。

## 6. Gate B 分层关系核查

Gate B 的代码事实成立:

| 层 | 当前事实 | P0 判断 |
|---|---|---|
| `MemorySaver` | RAG chat 与 AIOps graph 都使用 LangGraph `MemorySaver`，按 `session_id` / `thread_id` 管当前会话状态 | 保留，不替换 |
| 文档 KB | planner 先查 `retrieve_knowledge` 并注入 `experience_context` | 保留，不改变默认检索 |
| durable oncall memory | 当前未实现 | 只有 Gate A 通过后才允许实现 |

## 7. 后续补真实证据的条件

后续如果要把 Gate A.1 从“未通过”改为“通过”，至少需要追加以下任一种真实材料:

1. 3 个相似告警的 session_id / 日志 / 输出对比，证明 agent 没有复用过去已验证根因或计划。
2. 已完成诊断的 plan / past_steps / response，以及下一次相似告警中 planner 忽略该成功计划的证据。
3. 多次用户偏好输入记录，且该偏好不适合做前端配置、请求参数或项目文档。
4. 跨 session runtime context 丢失导致错误诊断、错误计划或重复追问的记录。

没有这些材料时，durable memory 可以继续作为 Gate A.2 下的 pre-launch product bet 推进本机 sidecar 能力，但不能声称已经被真实生产 oncall 痛点证明。
