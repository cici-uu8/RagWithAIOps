# 双参考源码复用记忆系统升级计划

## 0. 开发记录与最终教程产物

本计划关联的所有 memory-system 开发推进，必须单独记录在:

- `docs/memory_fusion_development_record.md`

这份记录是 OpenViking + TencentDB-Agent-Memory 双参考记忆系统升级工作的正式过程记录。它和 `docs/rag_fusion_development_record.md` 分开维护，避免把 memory 运行时能力的证据、决策、schema、评估和 rollout 记录混入 RAG / WeKnora 融合主线。

记录纪律沿用此前 `docs/rag_fusion_development_record.md` 的要求:

- 每完成一个有实质意义的步骤，都要同步更新 `docs/memory_fusion_development_record.md`。
- 记录不是编码完成后的可选整理，而是该阶段完成条件的一部分。
- P0 证据、P0 决策表、P1 schema、P2 检索阈值、P4 candidate/review、P5 prompt 注入、P6 评估和 rollout 调整，都必须留下记录。
- 每条记录至少写清: 为什么现在做、改了哪些文件或模块、暴露了什么风险、如何验证、哪些问题延期、如何在项目复盘或面试中解释。
- 如果计划顺序、范围、假设或技术路线发生变化，必须同时更新本计划和 `docs/memory_fusion_development_record.md`。
- 如果某阶段只是设计或证据收集，没有改运行时代码，也要明确记录“未改 `app/*`”。
- 前一阶段没有完成记录时，不进入后一阶段。

本计划全部完成并通过 P6 closeout 后，必须基于真实实现再写两份教程文件:

- `docs/oncall_agent_memory_enhanced_tutorial.md`
- `docs/oncall_agent_memory_source_code_deep_dive.md`

第一份负责讲清 oncall agent memory 能力、使用路径、边界和典型场景；第二份按源码深挖标准解释关键文件、模型、服务、调用链、验证方式、风险边界和项目复盘口径。两份教程只能在实现和评估完成后写，不能用预期设计冒充已落地能力。

## 1. 目标

本文定义如何借鉴 OpenViking 与 TencentDB-Agent-Memory 的源码和设计，为 SuperBizAgent 升级 agent 记忆系统。

这不是实现命令，而是设计候选。P0 没关闭前，不允许进入 P1 编码。

核心目标:

- 不替换现有 MinerU / WeKnora / Milvus / `RetrievalService` 主链路。
- 不削弱现有文档引用、`SourceRef`、`citation_text` 和 RAG eval 边界。
- 不把 LangGraph `MemorySaver` 当成 durable memory；但允许在独立证据成立后评估当前会话记忆升级。
- 不直接采用 OpenViking server 或 TencentDB-Agent-Memory plugin 作为运行时依赖。
- 每个实现阶段先看两个 clone 下来的参考仓库源码，优先复用可移植思想、接口形态、算法和测试边界，再决定是否写本项目代码。
- 只在证明存在 oncall 运行时痛点后，或在 pre-launch 阶段明确记录为产品下注后，增加跨 session、可审计、可回滚的 durable memory。
- durable memory 主要服务告警模式、根因假设、处理方案、成功诊断计划、运行时偏好和运行时上下文。

一句话边界:

> 当前会话记忆负责一个 `session_id` 内的短期状态与压缩；durable oncall memory 负责跨 session 可复用、可审核、可回滚的结构化经验。

## 2. P0 之前的前置门槛

P0 不是编码阶段。P0 是“到底该不该做”的证据和决策阶段。

在任何 `app/models/memory.py` 或 `app/services/memory_store.py` 代码出现之前，必须先完成两个文档:

- `docs/openviking_memory_p0_pain_evidence.md`
- `docs/openviking_memory_p0_decision_table.md`

如果这两个文件写不出来，就停止在设计阶段。

### 2.1 门槛 A: oncall 运行时痛点证据

不能因为 OpenViking 有 memory 架构，就默认本项目必须移植。必须先证明 SuperBizAgent 运行时存在真实痛点。

Gate A 分两条路径:

- Gate A.1: Real oncall evidence。来自生产或准生产 oncall 流程的真实 session、日志、告警、用户提问或诊断记录。
- Gate A.2: Pre-launch controlled baseline / product bet。产品尚未接入真实 oncall 流量时，可以用当前项目在本机可验证的受控基线推进 P1，但必须显式标注“这不是生产痛点证据”，并设置后续复评和回滚条件。

禁止把 synthetic fixture、手写假 session、假 alert history 或 LLM 编出来的 case 贴进 `pain_evidence.md` 冒充 Gate A.1 证据。测试夹具可以存在，但必须物理隔离在 `tests/fixtures/memory_synthetic/` 等目录，并标注 `design-fixture, NOT real session evidence`。

`docs/openviking_memory_p0_pain_evidence.md` 至少要包含下表字段:

| 字段 | 说明 |
|---|---|
| `case_id` | 案例 ID。 |
| `occurred_at` | 出现时间。 |
| `alert_or_question` | 告警或用户问题。 |
| `expected_reuse` | 本应复用的历史根因、计划、偏好或上下文。 |
| `actual_behavior` | agent 实际表现。 |
| `document_kb_coverage` | 现有文档 KB 是否已覆盖。 |
| `memory_saver_enough` | 当前 `MemorySaver` 会话状态是否足够。 |
| `code_or_config_solution` | 是否能通过代码、配置、请求参数、测试解决。 |
| `why_durable_memory` | 为什么必须是 durable memory。 |

Gate A.1 P1 启动条件:

- 至少有一个明确痛点类别成立。
- 对“重复告警从零开始”或“成功诊断计划未复用”这类核心 oncall 痛点，优先要求 3 个相似案例。
- 如果生产 oncall 量级不足，不能编凑案例。应在 P0 结论里写“证据不足，停止实现”。

Gate A.2 P1 启动条件:

- 明确声明当前是 `pre-launch controlled baseline / product bet`，不是 pain-driven real oncall evidence。
- 至少记录 3 个具体 oncall 场景假设或本机受控基线，每条都要写清:
  - 当前系统如何处理；
  - 为什么现有文档 KB / `MemorySaver` / 配置 / 请求参数不足以表达跨 session 经验复用；
  - 如果未来真实流量不支持该假设，memory 子系统如何复评、降级或回滚。
- 必须设置 `deprecate-if-not-validated` 里程碑，例如首次灰度部署后 30 天，或累计 20 次 AIOps diagnosis 后复评。
- 必须指定复评 owner；暂时无法指定人时，写 `runtime owner TBD`，但不能省略 owner 字段。
- Gate A.2 只允许推进 sidecar memory schema/store/retrieval/artifact 的默认关闭能力；P5 prompt 注入和扩大 rollout 仍必须等 P6 评估与真实复评。
- 当前 code-enforced 状态只覆盖 “20 次 AIOps diagnosis 后复评” 分支；“首次灰度部署后 30 天” 分支在出现可观测 gray deployment 事件源前明确 deferred，不能把整个 `deprecate-if-not-validated` gate 宣称为完全 code-enforced。

可接受的痛点类型:

| 痛点类型 | 需要的证据 | 必须排除的已有机制 |
|---|---|---|
| 重复告警每次从零开始 | 相似告警中 agent 没复用已验证根因模式 | 文档 KB、runbook、`retrieve_knowledge` |
| 成功诊断计划没有复用 | 同类告警中 planner 忽略过去成功排查步骤 | planner 当前经验文档检索路径 |
| 运行时偏好反复重说 | 用户反复要求报告语言、引用粒度、详细程度 | 前端配置、请求参数 |
| 跨 session 运行时上下文丢失 | running agent 需要非文档型上下文 | `MemorySaver`、持久文档、KB |
| 非代码可强制的判断规则丢失 | 某些判断不能用代码或测试固化 | 代码、配置、测试、项目文档 |

### 2.2 门槛 B: 与现有 `MemorySaver` 的分层关系

本项目已经有运行时短期记忆:

- `app/services/rag_agent_service.py` 使用 `MemorySaver` 保存 chat-thread message history。
- `app/services/aiops_service.py` 使用 `MemorySaver` 保存 Plan-Execute-Replan graph state。
- 两条路径都用 `session_id` 作为 LangGraph `thread_id`。
- `RagAgentService.get_session_history(session_id)` 能从 checkpointer 读取消息历史。

现有 `MemorySaver` 的性质:

- thread-scoped；
- process-local / in-memory；
- message-history / graph-state oriented；
- 适合当前会话连续执行；
- 服务重启后不保证保留；
- 不是跨 session durable product memory。

新增 durable memory 的性质:

- cross-session；
- durable；
- 结构化；
- evidence-backed；
- 面向 oncall 经验复用；
- 不替换 checkpointer。

分层表:

| 层 | owner | 解决的问题 | 本计划关系 |
|---|---|---|---|
| `MemorySaver` | LangGraph runtime | 当前 `session_id` 的短期消息和图状态 | 保留，不替换 |
| 文档 KB | RAG runtime | 文档证据、runbook、经验文档引用 | 保留，不替换 |
| durable oncall memory | SuperBizAgent runtime | 跨 session 告警模式、根因、计划模板、偏好、上下文 | 门槛 A 通过后才做 |

P1 明确不做:

- 不替换 `MemorySaver`。
- 不把完整 raw message history 当 memory 存。
- 不改变 `session_id` / `thread_id` 合约。
- 不改变 `retrieve_knowledge` 默认行为。
- 不改变现有 RAG 检索排序和 citation 语义。

如果唯一痛点只是“当前进程内会话要连续”，继续使用 `MemorySaver`，不做 durable memory。

### 2.3 两层记忆系统的升级路径

本项目允许重新设计 agent 记忆系统，但不能把“当前会话记忆”和“跨 session durable memory”混成一层。

当前建议分成两层:

| 层 | 职责 | 现状 | 可升级方向 |
|---|---|---|---|
| 当前会话记忆 | 管当前 `session_id` 的短期消息、状态、工具链上下文 | `MemorySaver` + `SessionHistoryAccessor` / `AIOpsGraphStateAccessor` | 视会话长度、工具日志膨胀、重启恢复需求再评估更持久的 checkpointer 或 session compaction |
| durable memory | 管跨 session 复用的经验、偏好、计划模板、根因模式 | sidecar 记忆系统 | 继续按 P0-P6 纪律演进，保持 evidence-backed、review-backed、default-off |

这个分层允许两条独立升级线并存:

1. 如果当前会话的消息历史、工具日志或 graph state 压力变大，可以先升级 session memory，不必立刻开放 durable memory。
2. 如果跨 session 经验复用有真实痛点，则再继续推进 durable memory。
3. 两条线的评估证据、存储策略、审计方式都不相同，不能用同一个字段或同一个 DTO 一把梭。

## 3. 当前代码事实

本计划基于当前仓库代码事实，而不是抽象架构想象。

已核实事实:

- `app/agent/aiops/planner.py` 的 `planner_prompt` 已有 `{experience_context}` placeholder。
- `planner.py` 会先调用 `retrieve_knowledge` 查询内部经验文档。
- `planner.py` 会将经验文档注入 `{experience_context}` 后再生成计划。
- `app/agent/aiops/replanner.py` 基于 `plan` / `past_steps` 做 `continue` / `replan` / `respond`。
- `app/services/rag_agent_service.py::get_session_history(session_id)` 目前直接解析 `MemorySaver` checkpoint tuple，属于 fragile internal-shape 依赖。
- `app/services/aiops_service.py` 内部使用 `graph.get_state(config_dict)` 获取最终状态，但没有对外稳定的 AIOps graph-state accessor。

因此:

- P5 可以考虑把 memory guidance 接在 planner 的 `{experience_context}` 附近。
- P4 不能直接依赖 `get_session_history` 的内部解析逻辑，必须先抽 adapter。
- AIOps candidate extraction 必须先有稳定 graph-state accessor。
- 如果后续重启 P4.6 当前会话记忆升级，`get_session_history` 过去解析 checkpoint internals 的 fragility 也必须作为 session-memory pain / risk evidence 之一，而不是只看 token pressure。

## 4. 双参考源码与复用原则

本项目不是“照搬一个记忆框架”，而是“拿两个参考仓库做复用式重设计”。

### 4.1 OpenViking 可借鉴点

OpenViking 对本项目的价值是分层上下文、命名空间、检索轨迹和 session 组织方式，不是整套 server 搬迁。

可借鉴点:

1. 目录化上下文。
   - 把 document resource、user preference、agent experience、session candidate 分开。
   - 防止长期记忆和文档证据混在一起。

2. 分层上下文。
   - 先用 summary 做轻量路由，再按需加载 detail。
   - 本项目可映射成 `summary` / typed payload / document chunk。

3. 内容存储和索引分离。
   - JSON / SQLite / memory store 是 source of truth。
   - embedding index 只能是检索视图。

4. session commit。
   - 不是自动把会话全写入 memory。
   - 应从 `session_id` 对应的消息或 graph state 中抽取候选经验。
   - 候选必须带 evidence，默认 `candidate`，不能直接 active。

5. 检索可观测。
   - memory hit 必须返回独立 artifact。
   - memory artifact 不能复用 `RetrievalResult` 或 `SourceRef`。

### 4.2 TencentDB-Agent-Memory 可借鉴点

TencentDB-Agent-Memory 对本项目的价值是符号化短期记忆、SQLite/FTS/向量混合召回、RRF 融合、分层长期记忆和降级容错。

可借鉴点:

1. 短期上下文卸载。
   - 工具日志、步骤摘要、Mermaid 画布可以把 session 里的重上下文压到更轻的结构。
   - 适合当前会话记忆升级路线，而不一定要进入 durable memory。

2. 长期记忆分层。
   - L0/L1/L2/L3 的思路说明记忆可以从 raw dialogue 逐步抽象到 scenario/persona。
   - 本项目可映射成 alert pattern / plan template / preference / runtime context。

3. SQLite + FTS + vector + RRF。
   - source of truth 仍可 local-first。
   - keyword / semantic / hybrid recall 可以用同一条 store 决策链实现。

4. 降级与非致命行为。
   - 搜索失败、向量失败、检索退化时返回 degraded 结果，而不是把整个系统打死。
   - 这对 oncall runtime 很重要。

5. node_id / result_ref / trace 轨迹。
   - session 压缩和检索结果都要能回到证据。
   - 适合补强当前 memory artifact 的可追踪性。

### 4.3 复用原则

1. 先复用思想，再复用接口形态，最后才考虑代码移植。
2. OpenViking 是 AGPL-3.0，代码级复用要额外看 license 风险；TencentDB-Agent-Memory 是 MIT，代码移植空间更大，但仍要保留归属和适配痕迹。
3. 复用优先顺序:
   - 先看本项目现有代码能不能承载；
   - 再看 TencentDB-Agent-Memory 是否能提供直接可移植的 TS 设计或算法边界；
   - 再看 OpenViking 是否提供更好的上下文组织和 trace 思路。
4. 不因为参考仓库“更全”就直接换架构。当前项目已有 RAG / WeKnora 主链路，memory 只能 sidecar 方式接入。

### 4.4 本地参考源码位置

截至 2026-05-25，两个参考仓库已 clone 到本机父目录，作为只读参考源:

| 仓库 | 本地路径 | 当前 commit | 许可证 | 本项目复用边界 |
|---|---|---|---|---|
| OpenViking | `/Users/cici/oncall agent/OpenViking` | `3c876407` | AGPL-3.0 | 优先 idea-level / architecture-level 复用；代码级复用需单独 license 决策 |
| TencentDB-Agent-Memory | `/Users/cici/oncall agent/TencentDB-Agent-Memory` | `dc34ec5` | MIT (local `LICENSE` body verified 2026-05-25; GitHub metadata may report `NOASSERTION`) | 可作为 SQLite/FTS/vector/RRF、session offload、符号化压缩的代码级参考，移植时保留归属 |

当前重点源码:

| 仓库 | 源码位置 | 参考价值 |
|---|---|---|
| OpenViking | `openviking/core/namespace.py` / `openviking/core/context.py` | namespace、context type、context level |
| OpenViking | `openviking/server/routers/search.py` / `openviking/service/search_service.py` | search level、provenance、trace 思路 |
| OpenViking | `openviking/server/routers/sessions.py` | session/message/part 组织方式 |
| TencentDB-Agent-Memory | `src/core/types.ts` | host-neutral runtime / adapter 抽象 |
| TencentDB-Agent-Memory | `src/core/store/sqlite.ts` / `src/core/store/search-utils.ts` | SQLite、FTS、vector、RRF、degraded fallback |
| TencentDB-Agent-Memory | `src/core/tools/memory-search.ts` / `src/core/tools/conversation-search.ts` / `src/core/hooks/auto-recall.ts` | recall tool、timeout fallback、自动召回边界 |
| TencentDB-Agent-Memory | `src/offload/types.ts` / `src/offload/state-manager.ts` / `src/offload/pipelines/l2-mermaid.ts` | Mermaid short-term memory、`node_id`、`result_ref`、session offload |

## 5. 明确不做

第一轮实现禁止做这些事:

- 不替换 `RetrievalService`。
- 不改变 `retrieve_knowledge` 默认行为。
- 不把 memory 混入文档 citation。
- 不新增平行 RAG 框架。
- 不新增新向量数据库作为 source of truth。
- 不直接移植 OpenViking 的 AGFS / RAGFS / VLM / session engine。
- 不把 OpenViking 或 TencentDB-Agent-Memory 的运行时当成黑盒依赖接进来。
- 不把 TencentDB-Agent-Memory 的自动每 N 轮提取规则、OpenViking 的 server/session 管理，原封不动塞进当前 oncall runtime。
- 不在 license 决策没说清前做 OpenViking AGPL 代码级拷贝。
- 不把代码已经强制的行为写成 memory。
- 不把 `PROJECT_STATE.md` 这类 repo truth 改由 memory 承担。
- 不替换或绕过 `MemorySaver`。
- 不把 `MemorySaver` 误写成 durable memory。
- P0 没有 closeout 前，不启动 P1。

## 6. 命名空间模型

命名空间使用 URI-like 格式，但只作为本项目本地约定。

| Namespace | 用途 | 示例 |
|---|---|---|
| `memory://oncall/alert-patterns` | 告警模式 -> 根因 -> 处理方案 | `CPUHigh` + service A + 日志 B 通常指向 leak C |
| `memory://oncall/plan-templates` | 成功 Plan-Execute-Replan 调查模板 | 磁盘告警先查 mount、近期发布、日志写放大、清理安全性 |
| `memory://runtime/user-preferences` | 不适合做配置项的用户偏好 | 某团队偏好中文简洁报告，并显式列证据边界 |
| `memory://runtime/context` | 非文档型运行时上下文 | 临时值班负责人、短期维护窗口 |
| `memory://candidate/session` | 从 session 提取但未审核的候选记忆 | 某次诊断 run 的候选 alert pattern |
| `resource://knowledge/documents` | 现有文档 KB 和 artifact | MinerU chunks、`SourceRef`、`artifact_manifest.json` |

边界:

- `memory://...` 只能指导 agent。
- `resource://...` 才能支撑文档事实引用。
- memory 不能生成伪 citation。

## 7. P1 数据模型

P1 的目标不是召回效果，而是把 durable memory contract 锁住。

### 7.1 `MemoryRecord`

建议字段:

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `memory_id` | `str` | 是 | 稳定 ID |
| `schema_version` | `int` | 是 | schema 版本，初始为 `1` |
| `owner_id` | `str` | 是 | 租户 / 用户 / 团队隔离字段，单租户阶段填 `"default"` |
| `namespace` | `str` | 是 | URI-like namespace |
| `memory_type` | `str` | 是 | `alert_pattern` / `plan_template` / `preference` / `runtime_context` / `candidate_summary` |
| `content` | `str` | 是 | 人类可读文本 |
| `summary` | `str` | 是 | 检索路由用摘要 |
| `payload` | typed model | 是 | 类型化结构，不允许裸 `dict` 长期存在 |
| `source` | `str` | 是 | 来源 |
| `evidence` | `dict` | 是 | 证据，包含 session、工具调用、文档、时间等 |
| `status` | `str` | 是 | `active` / `candidate` / `conflict` / `deprecated` |
| `candidate_review_deadline` | `datetime | None` | 否 | candidate 审核截止时间，过期可自动 deprecated |
| `tags` | `list[str]` | 否 | 检索和过滤标签 |
| `last_accessed_at` | `datetime | None` | 否 | 最近使用时间 |
| `access_count` | `int` | 是 | 使用次数，初始 `0` |
| `created_at` | `datetime` | 是 | 创建时间 |
| `updated_at` | `datetime` | 是 | 更新时间 |

P1 不加入 `confidence: float`。

原因:

- 谁打分不明确。
- LLM 置信度不可靠。
- 用户不应该手动校准分数。
- `status + evidence + review` 足以表达生命周期。

### 7.2 typed payload schema

P1 必须定义 typed payload。不能只存 `payload: dict | None`。

如果 P1 不实现 typed payload，则 P2 不允许启动。

当前实现使用 `MemoryPayload` union，并在 `MemoryRecord.validate_memory_contract()` 中按 `memory_type` 校验 payload 实际类型。后续如果需要更强的 schema 演化和自动解析，可以把它升级为 Pydantic discriminated union；但不允许退回裸 `dict`。

#### `AlertPatternPayload`

必需字段:

- `alert_name: str`
- `service: str | None`
- `severity: str | None`
- `signal_keys: list[str]`
- `metric_patterns: list[str]`
- `log_patterns: list[str]`
- `root_cause: str`
- `fix: str | None`
- `evidence_refs: list[dict]`

#### `PlanTemplatePayload`

必需字段:

- `alert_type: str`
- `plan_steps: list[str]`
- `tool_hints: list[dict]`
- `success_criteria: list[str]`
- `stop_conditions: list[str]`
- `evidence_refs: list[dict]`

#### `PreferencePayload`

必需字段:

- `preference_scope: str`
- `preference: str`
- `applies_to: list[str]`
- `source_event: dict`

#### `RuntimeContextPayload`

必需字段:

- `context_key: str`
- `context_value: str`
- `expires_at: datetime | None`
- `evidence_refs: list[dict]`

### 7.3 单租户与多租户

当前计划按 single-tenant runtime 启动。

但 P1 仍必须保留 `owner_id`:

- 初期统一写 `"default"`。
- 后续多租户时按 tenant / team / user 拆。
- 不允许等 P5 后再补 owner 字段。

### 7.4 生命周期字段

P1 只保留字段，不实现完整 GC。

必须先存:

- `last_accessed_at`
- `access_count`
- `candidate_review_deadline`

延后决定:

- 几天未命中进入 deprecated；
- active memory 数量超过多少触发 audit；
- candidate 过期后自动 deprecated 的具体时间窗。

## 8. 存储策略

P1 可以从 JSON store 开始，但必须受 P0 决策约束。

规则:

- 如果 P0 选择同步写入、单进程、无后台 candidate extraction，JSON store 可以接受。
- 如果 P0 选择 async extraction 或存在 promote/review 并发写入，禁止裸 JSON `read -> modify -> write_text`。
- async 场景下，P1 必须选择:
  - file lock + atomic replace；
  - 或 SQLite；
  - 或其他明确支持并发写的持久层。

JSON 是实现细节，不是架构承诺。

source of truth 可以是 JSON 或 SQLite；embedding index 永远只是检索视图。

## 9. 检索与 prompt 流程

目标流程:

```text
用户问题 / 告警
  -> memory prefetch
       -> user preference
       -> alert pattern
       -> plan template
       -> runtime context
  -> 需要文档证据时继续走 retrieve_knowledge
  -> context composer
       -> memory guidance: 明确标注为非文档证据
       -> document context: 文档引用证据
  -> LLM 输出
       -> memory artifact
       -> retrieval artifact
```

prompt 规则:

- memory 进入 LLM 前必须标注为 guidance。
- memory 的 `updated_at`、`evidence_refs` 必须随文本一起暴露。
- replanner 必须知道 memory 的时间和证据，才能判断新工具证据是否推翻旧 memory。
- 文档事实只能引用 `resource://knowledge/documents`。
- 如果 memory 与实时工具结果或文档证据冲突，以新证据为准。

示例 prompt 包装:

```text
运行时记忆指导:
- 以下内容是用户偏好、处理经验或运行时上下文。
- 它们不是文档来源，不能作为文档 citation。
- 每条记忆包含 updated_at 和 evidence_refs。
- 如果新工具证据与旧记忆冲突，以新证据为准，并将旧记忆标记为 candidate/conflict。
```

## 10. P0: 关闭条件与决策表

P0 必须输出两个文件:

- `docs/openviking_memory_p0_pain_evidence.md`
- `docs/openviking_memory_p0_decision_table.md`

### 10.1 `pain_evidence.md`

必须证明门槛 A，不允许“我估计有”。

如果拿不出案例，P0 结论写:

```text
证据不足，停止实现 durable memory。保留设计文档，不进入 P1。
```

### 10.2 `decision_table.md`

必须列出这些决策:

| 决策项 | 可选项 | 必须写清的影响 |
|---|---|---|
| 参考源码复用策略 | OpenViking only / Tencent only / 双参考 / 不复用 | 影响 license、实现边界、代码移植还是 idea-level adaptation |
| license 决策 | OpenViking idea-only / AGPL code accepted / Tencent MIT code-port / no direct copy | 影响是否允许直接搬运源码、NOTICE、后续商业化风险 |
| 当前会话记忆升级路线 | 保留 `MemorySaver` / persistent checkpointer / Tencent-style symbolic offload | 影响 session state、工具日志压缩、重启恢复，不等同 durable memory |
| durable memory 检索路线 | lexical only / FTS / embedding / hybrid RRF | 影响 P2.5/P2.6 是否启动、检索 trace、degraded fallback |
| P4 首期范围 | RAG chat / AIOps diagnosis / 两者 | 影响 session accessor、payload 字段、评测集 |
| candidate extraction 时机 | 同步 / 异步 / operator 显式触发 | 影响延迟、重启窗口、并发写风险 |
| 存储层 | JSON + lock / SQLite / 其他 | 影响并发、迁移、测试 |
| owner_id 来源 | 固定 default / request header / session metadata | 影响多租户隔离 |
| review/promotion | 手动 JSON / admin endpoint / CLI / operator workflow | 影响权限和审计 |
| P2 词面召回阈值 | 例如 10 条中至少 7 条命中预期 memory | 影响是否触发 P2.5 |
| active memory audit 阈值 | 例如 active count > N | 影响长期运营 |
| A/B rollout | 默认 off / 实验开启 / 全量开启 | 影响 P6 后上线 |

P1 schema 必须和 `decision_table.md` 对齐。

如果 P0 决策会改变 P1 字段，而字段没写进 schema，不能开 P1。

## 11. P1: 记忆模型与存储

P1 只做最小持久模型和 store。

预期文件:

- `app/models/memory.py`
- `app/services/memory_store.py`
- `tests/test_memory_store.py`

必须覆盖:

- `MemoryRecord`
- typed payload models
- `schema_version`
- `owner_id`
- `candidate_review_deadline`
- `last_accessed_at`
- `access_count`
- evidence 必填
- status 生命周期
- 按 namespace 查询
- 按 memory_type 查询
- active / candidate / conflict / deprecated 状态更新
- 不存 raw `MemorySaver` history

验证:

```bash
python -m unittest tests/test_memory_store.py
```

停止条件:

- payload 仍是无 schema 的裸 dict，停止。
- store 会存 raw checkpointer history，停止。
- P0 选择 async 但 P1 仍用无锁 JSON 覆盖写，停止。
- 需要修改 `app/models/knowledge.py` 才能建 memory model，停止并隔离模型。

## 12. P2: 旁路记忆检索

P2 只做旁路检索，不接默认 agent 路径。

预期文件:

- `app/services/memory_retrieval_service.py`
- `tests/test_memory_retrieval_service.py`

当前状态 (2026-05-24):

- P2 已完成本机 sidecar lexical retrieval slice。
- 实现只查 active memory，并在排序前按 `owner_id` / `namespace` / `memory_type` 过滤。
- 返回独立 `MemoryRetrievalResult`，不复用 RAG `RetrievalResult` / `SourceRef` / `citation_text`。
- 未接默认 agent path，未改 `retrieve_knowledge` / `RetrievalService` / planner prompt。

行为:

- 只查 active memory。
- owner_id / namespace / memory_type 先过滤。
- alert pattern 和 plan template 是一等过滤条件。
- 先实现词面匹配，但不能无门槛进入后续阶段。
- 返回独立 `MemoryRetrievalResult`，不复用 `RetrievalResult`。

验证:

```bash
python -m unittest tests/test_memory_retrieval_service.py
python -m unittest tests/test_retrieval_service.py
```

### 12.1 词面召回冻结门槛

P2 开工前冻结:

- 同义词集合；
- expected hit；
- 阈值。

本机冻结门槛 (2026-05-24):

- fixture: `tests/fixtures/memory_synthetic/p2_lexical_recall_cases.json`
- source: `design-fixture, NOT real session evidence`
- expected hit: 10 条 CPUHigh/CPU 使用率/处理器负载/processor saturation 等中英同义 query 应召回 `mem_alert_cpu_high`
- threshold: 10 条中至少 7 条命中 expected memory
- verification: `python -m unittest tests/test_memory_retrieval_service.py`
- latest explicit run (2026-05-24): 10/10 passed，P2.5 embedding retrieval 不触发。该结果仍是 synthetic design-fixture gate，只证明 lexical retrieval code path 达标，不作为 Gate A.1 真实痛点证据。

示例:

```text
10 条中英文同义告警 query，至少 7 条必须召回预期 memory。
```

示例 query:

- `CPUHigh`
- `CPU 利用率告警`
- `CPU 使用率过高`
- `service A CPU spike`
- 服务别名表达

如果达不到冻结阈值:

- 停止 P2。
- 启动 P2.5 embedding retrieval。
- 不允许 P3/P4/P5 建在不可靠 lexical-only 之上。

2026-05-24 explicit run 结果:

| query_id | query | expected | actual | result |
|---|---|---|---|---|
| Q01 | `CPUHigh` | `mem_alert_cpu_high` | `mem_alert_cpu_high` | pass |
| Q02 | `CPU 利用率告警` | `mem_alert_cpu_high` | `mem_alert_cpu_high` | pass |
| Q03 | `CPU 使用率过高` | `mem_alert_cpu_high` | `mem_alert_cpu_high` | pass |
| Q04 | `service A CPU spike` | `mem_alert_cpu_high` | `mem_alert_cpu_high` | pass |
| Q05 | `服务A处理器飙高` | `mem_alert_cpu_high` | `mem_alert_cpu_high` | pass |
| Q06 | `处理器负载过高` | `mem_alert_cpu_high` | `mem_alert_cpu_high` | pass |
| Q07 | `processor saturation` | `mem_alert_cpu_high` | `mem_alert_cpu_high` | pass |
| Q08 | `cpu load high after deploy` | `mem_alert_cpu_high` | `mem_alert_cpu_high` | pass |
| Q09 | `计算资源打满` | `mem_alert_cpu_high` | `mem_alert_cpu_high` | pass |
| Q10 | `用户服务 CPU 飙升` | `mem_alert_cpu_high` | `mem_alert_cpu_high` | pass |

## 13. P2.5: embedding retrieval 触发项

P2.5 是触发判定，不再作为独立默认实现路线。

只有 P2 词面召回门槛不过时才触发 P2.5。触发后默认进入 P2.6 Tencent-style hybrid memory retrieval 设计，而不是直接做一个 embedding-only 分支。

embedding-only 只允许作为受控实验或最小 spike:

- 可以用于测 semantic recall 是否能补 lexical 漏召；
- 不能直接接 P3/P4/P5；
- 不能绕过 FTS / RRF / degraded fallback 的设计评估；
- 不能把 embedding index 当 source of truth。

规则:

- JSON / SQLite 仍是 source of truth。
- embedding index 只存检索视图。
- 必须索引:
  - `memory_id`
  - `owner_id`
  - `namespace`
  - `memory_type`
  - `summary`
  - selected typed payload fields
- 先 exact filter，再 semantic rank。
- 不改变文档 RAG 检索。

验证:

```bash
python -m unittest tests/test_memory_retrieval_service.py
python -m unittest tests/test_retrieval_service.py
```

### 13.1 P2.6: Tencent-style hybrid memory retrieval

P2.5 解决“是否需要从 lexical-only 升级”；P2.6 是升级后的默认设计路线。

P2.6 不自动启动。触发条件:

- 真实或灰度 query 里出现 lexical-only 召回不稳；
- 或 P5 shadow 模式发现 memory 命中需要可解释的 keyword + semantic fusion；
- 或 active memory 数量增长到 lexical scoring 难以稳定排序。

设计候选:

| 能力 | TencentDB-Agent-Memory 参考 | 本项目落点 |
|---|---|---|
| FTS keyword recall | `src/core/store/sqlite.ts` 的 FTS5 path | 在 `MemoryStore` 的 SQLite source of truth 上加 FTS 表或 FTS 查询视图 |
| vector recall | `sqlite-vec` / embedding search | 只作为检索视图，不替代 `MemoryRecord` |
| RRF fusion | `src/core/store/search-utils.ts` | `MemoryRetrievalService` 增加 fusion trace，不复用 RAG result DTO |
| degraded fallback | sqlite/vector/embedding failure 返回空或 keyword-only | memory 召回失败不能影响主 RAG / AIOps 执行 |
| recall trace | memory-search / conversation-search 的 debug 信息 | `MemoryRetrievalResult.trace` 标明 keyword hit、vector hit、fusion rank |

停止条件:

- 如果需要改 `RetrievalService` 才能做 memory hybrid recall，停止。
- 如果 memory hybrid result 出现 `SourceRef` / `citation_text` 字段，停止。
- 如果 embedding index 被当成 source of truth，停止。
- 如果不能说明 timeout / degraded fallback 行为，停止。

## 14. P3: memory artifact 边界

P3 目标是可观测，不是默认接入 agent。

当前状态 (2026-05-24):

- P3 已完成本机 sidecar memory artifact slice。
- 新增 `app/tools/memory_tool.py`，提供显式 `retrieve_memory` tool，`response_format="content_and_artifact"`。
- 新增 `tests/test_memory_tool.py`，锁定非空 artifact、空结果 artifact，以及默认 RAG agent tools 不包含 `retrieve_memory`。
- artifact 使用 memory 专属字段，不复用 RAG `RetrievalResult`、`SourceRef` 或 `citation_text`。
- 未改 `app/tools/__init__.py`，未把 memory tool 加入 `RagAgentService.tools`，未接 planner prompt / AIOps graph。
- P3 完成后仍保持 P5 默认关闭；memory 命中只是可观测 artifact，不是文档 citation。

预期文件:

- `app/tools/memory_tool.py`
- `tests/test_memory_tool.py`

artifact 字段:

- `query`
- `owner_id`
- `memory_results`
- `namespaces`
- `memory_types`
- `status`
- `trace`
- `empty_message`

验证:

```bash
python -m unittest tests/test_memory_tool.py
python -m unittest tests/test_memory_retrieval_service.py
python -m unittest tests/test_retrieval_service.py
python -m compileall app tests
python -m unittest discover tests
```

2026-05-24 本机验证:

- `tests.test_memory_tool`: 3/3 passed。
- `tests.test_memory_tool tests.test_memory_retrieval_service tests.test_retrieval_service`: 13/13 passed。
- `compileall app tests`: passed。
- `unittest discover tests`: 217/217 passed。

停止条件:

- 如果 artifact 复用 `RetrievalResult` 或 `SourceRef`，停止。
- 如果 memory 结果看起来像文档 citation，停止。

## 15. P4: 从 `session_id` 提取 candidate memory

P4 不另造 session 概念。

当前状态 (2026-05-24):

- P4 已完成本机 sidecar candidate extraction slice。
- 首期范围覆盖 RAG chat + AIOps diagnosis，但只支持 operator 显式触发，不在用户请求链路里同步/异步自动抽取。
- RAG chat 通过 `SessionHistoryAccessor` 读取并规范化 history；`RagAgentService.get_session_history(session_id)` 已委托给该 accessor，避免业务代码继续散落解析 `MemorySaver` checkpoint shape。
- AIOps diagnosis 通过 `AIOpsGraphStateAccessor` / `AIOpsService.get_session_state(session_id)` 读取规范化 Plan-Execute-Replan state，不要求 caller 直接碰 `graph.get_state(config_dict)`。
- 新增 `app/models/memory_candidate.py`，定义 `SessionHistoryMessage`、`AIOpsSessionState`、`AIOpsPastStep` 和 `MemoryCandidateExtractionResult`。
- 新增 `app/services/memory_candidate_service.py`，提供 operator-triggered `extract_from_rag_session(...)`、`extract_from_aiops_session(...)` 和 `store_candidate(...)`。
- RAG chat 只生成 `candidate_summary`，用于“这次 session 可能有可复盘经验”的候选摘要，不直接变成 `active` 经验。
- AIOps diagnosis 首期生成 `plan_template` candidate；`payload.plan_steps` 来自规范化 state 的 `plan_steps`，缺失时才从 `past_steps.step` 回退；`payload.evidence_refs` 只存字段引用，不存 raw graph state。
- `source evidence` 存在 `MemoryRecord.evidence` 与 typed payload `evidence_refs` 中；字段包括 `session_id`、`source_type`、`message_refs` 或 `state_refs`，明确不存 `raw_messages` / `raw_memory_saver_history`。
- 去重/冲突判定已落为代码函数 `dedup_key(record)`、`conflict_key(record)`、`is_conflict(existing, candidate)`。
- P4.5 已补本地 operator review workflow: `MemoryReviewService` + `python -m app.cli.memory_operator`。没有 admin endpoint；promotion 必须显式提供 `reviewer_id` 和 `decision_note`。
- P4 operator extraction CLI 已补: `python -m app.cli.memory_operator extract-rag-session|extract-aiops-session`。命令读取 operator 提供的 normalized JSON snapshot (`--history-json` / `--state-json`)，然后调用同一套 `MemoryCandidateService`；它不跨进程读取 live `MemorySaver`，不接生产日志源，也不自动 active。
- `candidate_summary` 不能直接 promote 为 `active`；RAG chat 摘要只能作为 review 队列线索，不能冒充可复用 oncall 经验。
- `store_candidate(...)` 会强制未审核记录保持 `candidate`；如果同 key 但根因/修复等冲突，则写成 `conflict` 并记录 `conflicts_with`。
- 未改 `retrieve_knowledge`、`RetrievalService`、`RetrievalResult`、`SourceRef`、`citation_text`、planner/replanner prompt，也未把 `retrieve_memory` 加入默认 `RagAgentService.tools`。

2026-05-24 本机验证:

- `tests.test_memory_candidate_service`: 9/9 passed。
- `tests.test_memory_candidate_service tests.test_memory_tool tests.test_memory_retrieval_service tests.test_retrieval_service`: 22/22 passed。
- `compileall app tests`: passed。
- `unittest discover tests`: 226/226 passed。
- P4.5 targeted review workflow: `tests.test_memory_review_service`: 6/6 passed。
- P4.5 memory/RAG bundle: `tests.test_memory_store tests.test_memory_candidate_service tests.test_memory_review_service tests.test_memory_tool tests.test_memory_retrieval_service tests.test_retrieval_service`: 33/33 passed。
- P4.5 full verification: `compileall app tests` passed；`unittest discover tests`: 232/232 passed。
- P4 extraction CLI targeted workflow: `tests.test_memory_operator_cli`: 2/2 passed。
- P4 extraction CLI + review bundle: `tests.test_memory_candidate_service tests.test_memory_review_service tests.test_memory_operator_cli`: 17/17 passed。
- P4 memory/RAG bundle after extraction CLI: `tests.test_memory_store tests.test_memory_candidate_service tests.test_memory_review_service tests.test_memory_operator_cli tests.test_memory_tool tests.test_memory_retrieval_service tests.test_retrieval_service`: 35/35 passed。
- P4 extraction CLI full verification: `compileall app tests` passed；`unittest discover tests`: 234/234 passed。

P4 从现有 `session_id` 出发:

- RAG chat: 通过 `SessionHistoryAccessor` 读取 history。
- AIOps: 通过稳定 graph-state accessor 读取 Plan-Execute-Replan state。

预期文件:

- `app/services/session_history_accessor.py`
- `app/models/memory_candidate.py`
- `app/services/memory_candidate_service.py`
- `app/cli/memory_operator.py`
- `tests/test_memory_candidate_service.py`
- `tests/test_memory_operator_cli.py`

P4 前置决策:

- 首期覆盖: RAG chat + AIOps diagnosis。
- candidate extraction 时机: operator 显式触发；不在 chat / diagnosis 请求中自动执行。
- source evidence 存储: `MemoryRecord.evidence` + typed payload `evidence_refs`，只存稳定引用，不存 raw history / raw graph state。
- `payload.plan_steps`: 从 `AIOpsSessionState.plan_steps` 读取；若 final state plan 已清空，则从 `past_steps.step` 回退。
- `payload.root_cause`: P4.0 不从非结构化 LLM response 自动抽 alert pattern root_cause；如 operator 提供结构化 `alert_pattern` candidate，则使用同一 `store_candidate(...)` 去重/冲突规则。自动 root-cause parser 延期到有真实 AIOps 样例后再做。
- `payload.evidence_refs`: RAG 使用 `session_message_ref`；AIOps 使用 `graph_state_field_ref`，字段为 `input` / `response` / `plan_steps[i]`。
- review / promotion: P4.5 采用本地 CLI / operator workflow；不做 admin endpoint。
- promote 权限: 当前只用显式 `reviewer_id` + `decision_note` 形成审计记录，不声明生产权限模型；进入 P5/P6 或后台页面前必须补真实认证/授权设计。

### 15.1 去重与冲突判定

P4 写代码前必须定义 per-memory_type 判定。

建议函数签名:

```python
def dedup_key(record: MemoryRecord) -> tuple: ...
def conflict_key(record: MemoryRecord) -> tuple: ...
def is_conflict(existing: MemoryRecord, candidate: MemoryRecord) -> bool: ...
```

初始建议:

| memory_type | dedup key | conflict 初始规则 |
|---|---|---|
| `alert_pattern` | `owner_id + alert_name + service + sorted(signal_keys)` | key 相同但 `root_cause` 或 `fix` 不同 |
| `plan_template` | `owner_id + alert_type + hash(plan_steps)` | alert_type 相同但 stop_conditions / tool_hints 明显冲突 |
| `preference` | `owner_id + preference_scope + applies_to` | 同 scope 下 preference 互斥 |
| `runtime_context` | `owner_id + context_key` | 同 key 不同 value 且未过期 |
| `candidate_summary` | `owner_id + session_id + hash(summary)` | 不做自动 conflict，只作为 review 队列摘要 |

P4 已实现这些判定函数。后续新增 memory_type 时必须先补判定函数和测试，再允许 extraction。

### 15.2 review / promotion

当前状态 (2026-05-24 P4.5):

- 已新增 `MemoryReviewDecision` / `MemoryReview` 到 `app/models/memory.py`，用于记录 operator review 审计字段。
- 已新增 `app/services/memory_review_service.py`，提供 `list_review_queue(...)`、`approve_candidate(...)`、`reject_candidate(...)`。
- 已新增 `app/cli/memory_operator.py`，可通过 `python -m app.cli.memory_operator list|show|approve|reject` 在本机操作 SQLite memory store。
- 同一 CLI 也提供 `extract-rag-session` / `extract-aiops-session`，从 operator 导出的 normalized JSON snapshot 创建 reviewed-later candidate，不读取 raw history，不直接 promote。
- 同一 CLI 也提供 `status` / `record-aiops-diagnosis`，把 Gate A.2 的 `deprecate-if-not-validated` 20 次 AIOps diagnosis 复评条件落成 SQLite 可观测计数。
- 同一 CLI 也提供 `preview-deprecate-owner-memories` / `deprecate-owner-memories`，用于复评失败时按 owner 显式标记 memory 记录为 `deprecated`；这是非删除式 rollback helper，保留 SQLite 记录和 review audit。
- `approve_candidate(...)` 只允许 `candidate` -> `active`，且必须提供非空 `reviewer_id` 和 `decision_note`；`conflict` 不能直接 approve，需先人工解决冲突。
- `reject_candidate(...)` 将 `candidate` / `conflict` 标记为 `deprecated`，同时留下 review 审计。
- `deprecate_owner_memories(...)` 将指定 owner 下所有 `active` / `candidate` / `conflict` 记录标记为 `deprecated`，要求非空 `reviewer_id` 和 `decision_note`，并把每条记录的 `previous_status` 写入 review audit。
- `candidate_summary` 明确禁止 promote 为 `active`，防止 RAG chat 摘要被误当成稳定 oncall 经验。
- CLI 的 `decision_source` 写为 `operator-cli`；服务层默认写为 `operator-workflow`。
- 仍然没有 admin endpoint，没有默认自动 promote，没有 prompt 注入，没有 `retrieve_knowledge` 或 citation 变更。

示例:

```bash
python -m app.cli.memory_operator --store-path ./uploads/_metadata/oncall_memory.sqlite3 list
python -m app.cli.memory_operator --store-path ./uploads/_metadata/oncall_memory.sqlite3 show <memory_id>
python -m app.cli.memory_operator --store-path ./uploads/_metadata/oncall_memory.sqlite3 extract-rag-session <session_id> --history-json <normalized_history.json>
python -m app.cli.memory_operator --store-path ./uploads/_metadata/oncall_memory.sqlite3 extract-aiops-session <session_id> --state-json <normalized_state.json>
python -m app.cli.memory_operator --store-path ./uploads/_metadata/oncall_memory.sqlite3 status --owner-id <owner>
python -m app.cli.memory_operator --store-path ./uploads/_metadata/oncall_memory.sqlite3 record-aiops-diagnosis <diagnosis_id> --owner-id <owner> --note "<operator note>"
python -m app.cli.memory_operator --store-path ./uploads/_metadata/oncall_memory.sqlite3 preview-deprecate-owner-memories --owner-id <owner>
python -m app.cli.memory_operator --store-path ./uploads/_metadata/oncall_memory.sqlite3 deprecate-owner-memories --owner-id <owner> --confirm-owner-id <owner> --reviewer-id <operator> --note "<failed validation reason>"
python -m app.cli.memory_operator --store-path ./uploads/_metadata/oncall_memory.sqlite3 approve <memory_id> --reviewer-id <operator> --note "<why approved>"
python -m app.cli.memory_operator --store-path ./uploads/_metadata/oncall_memory.sqlite3 reject <memory_id> --reviewer-id <operator> --note "<why rejected>"
```

默认:

- candidate 不能自动 active。
- admin 权限模型仍未定义，因此不做 admin endpoint。
- `candidate_review_deadline` 字段保留；P4.5 review 时会清空已审核记录的 deadline，但仍不自动设置过期时间，也不自动 deprecated；候选过期策略延期到 P6 评估前定义。

可选 review 方式:

- 手动编辑 JSON；
- admin endpoint；
- CLI / operator command；
- 后台管理页面。

认证 / 权限没定义时，不做 admin endpoint。

### 15.3 extraction timing

必须在 P4 前决定:

| 方式 | 好处 | 风险 |
|---|---|---|
| 同步抽取 | run 完成前必有 candidate | 增加响应延迟 |
| 异步抽取 | 不阻塞用户 | 服务重启窗口可能丢 state |
| operator 显式触发 | 最可控 | UX 和运营成本高 |

如果选择异步抽取:

- P1 store 不能用无锁 JSON 覆盖写。
- 必须有重启窗口说明。

P4 实际选择 operator 显式触发:

- 好处: 不增加 chat / diagnosis 响应延迟，不引入后台任务重启窗口。
- 当前处理: 已补 `extract-rag-session` / `extract-aiops-session` 本地 CLI，输入为 operator 导出的 normalized JSON snapshot。
- 风险: 该 CLI 不是生产 session/log-source 集成；单独 CLI 进程也不能读取另一个服务进程里的 live in-memory `MemorySaver`。生产或准生产接入仍需要后续稳定 session/log source、后台页面或同进程 operator hook。
- 仍不做: 用户请求链路自动抽取、后台任务自动抽取、prompt 注入、admin endpoint。

### 15.4 deprecate-if-not-validated 复评计数观测

当前状态 (2026-05-24):

- 已在 `app/services/memory_store.py` 增加 `memory_policy_events` SQLite 表，按 `owner_id + event_type + event_ref` 去重记录 operator 确认过的 AIOps diagnosis 事件。
- `MemoryStore.get_validation_policy_status(owner_id=...)` 返回 Gate A.1 / A.2 状态、20 次 diagnosis 阈值、当前计数、剩余次数、是否达到 diagnosis-count 复评条件、`review_owner`、以及 P5 仍 blocked/default-off 的状态。
- `MemoryStore.record_aiops_diagnosis(diagnosis_id, owner_id=..., note=...)` 只记录唯一 diagnosis id；重复执行不会把计数顶高。
- `app/cli/memory_operator.py` 新增 `status` 和 `record-aiops-diagnosis` 两个本地 operator 子命令。
- `app/services/memory_review_service.py` 新增 owner-scoped deprecation preview / apply helper，复评失败时可以非删除式 rollback 到 `deprecated` 状态。
- `app/cli/memory_operator.py` 新增 `preview-deprecate-owner-memories` 和 `deprecate-owner-memories`；执行命令必须提供 `--confirm-owner-id`，避免误操作到错误 owner。
- 这覆盖“累计 20 次 AIOps diagnosis 后复评”的本机可观测条件，以及复评失败时的本机 operator rollback/deprecation helper；“首次灰度部署后 30 天”的部署时间锚点和自动提醒仍未实现。
- 计数达到阈值只表示必须复评，不表示 Gate A.1 自动通过，也不表示 P5 可以打开。

验证 (2026-05-24):

- TDD red: `tests.test_memory_operator_cli` 先失败在缺少 `status` / `record-aiops-diagnosis` 子命令。
- Targeted: `tests.test_memory_store tests.test_memory_operator_cli`: 10/10 passed。
- Memory/RAG bundle: `tests.test_memory_store tests.test_memory_candidate_service tests.test_memory_review_service tests.test_memory_operator_cli tests.test_memory_tool tests.test_memory_retrieval_service tests.test_retrieval_service`: 38/38 passed。
- `compileall app tests`: passed。
- Full: `unittest discover tests`: 237/237 passed。

2026-05-24 rollback/deprecation helper 追加验证:

- TDD red: `tests.test_memory_review_service tests.test_memory_operator_cli` 先失败在缺少 `build_owner_deprecation_plan` / `deprecate_owner_memories` 和两个 CLI 子命令。
- Targeted: `tests.test_memory_review_service tests.test_memory_operator_cli`: 14/14 passed。
- Memory/RAG bundle: `tests.test_memory_store tests.test_memory_candidate_service tests.test_memory_review_service tests.test_memory_operator_cli tests.test_memory_tool tests.test_memory_retrieval_service tests.test_retrieval_service`: 42/42 passed。
- `compileall app tests`: passed。
- Full: `unittest discover tests`: 241/241 passed。

边界:

- 不自动 deprecated memory 记录；只允许 operator 显式执行 owner-scoped deprecation。
- 不自动 rollback memory 子系统。
- rollback helper 不删除 SQLite 文件、不删除记录、不清空 `memory_policy_events`，只把指定 owner 下非 deprecated memory 记录标记为 `deprecated` 并写 review audit。
- 不创建 admin endpoint。
- 不修改 prompt、`retrieve_knowledge`、`RetrievalService` 或 citation 语义。
- 不把 synthetic fixture、operator note 或本地计数当作 Gate A.1 real oncall evidence。

### 15.5 P4.6: 当前会话记忆升级设计

P4.6 不是 durable memory 的继续写入阶段，而是单独评估当前会话记忆是否需要升级。

当前状态:

- `MemorySaver` 是 LangGraph 进程内 checkpointer。
- `SessionHistoryAccessor` / `AIOpsGraphStateAccessor` 已经把读取边界收束成 adapter。
- operator extraction CLI 只读 normalized JSON snapshot，不跨进程读 live `MemorySaver`。

P4.6 可选路线:

| 路线 | 适用痛点 | 风险 |
|---|---|---|
| 继续 `MemorySaver` | 会话短、工具日志可控、无需重启恢复 | 最小改动 |
| persistent checkpointer | 服务重启后还要恢复当前 session | 需要确认 LangGraph checkpointer API 和迁移策略 |
| Tencent-style symbolic offload | 工具日志 / 中间步骤过长，prompt 压力明显 | 需要 node_id/result_ref 证据链，不能丢 raw 追溯 |

P4.6 启动证据:

- session tool log / graph state 已经造成 token pressure；
- 或服务重启导致当前诊断流程中断且业务不可接受；
- 或 AIOps Plan-Execute-Replan 长链需要 resume / drill-down。
- 或当前会话历史 / graph-state 读取仍暴露 fragile checkpoint-internal shape 依赖，且 accessor 已无法把风险局部化。

禁止:

- 不能把 session compression 结果直接 promote 到 active durable memory。
- 不能把当前会话的 raw history 全量写入 `MemoryRecord`。
- 不能用 session memory 升级替代 Gate A.1 durable memory 证据。

### 15.6 P4.7: Tencent-style symbolic session compression 候选

如果 P4.6 证明 session memory 需要压缩，可以借鉴 TencentDB-Agent-Memory 的 Mermaid canvas / `node_id` / `result_ref` 思路。

候选设计:

1. raw 工具输出仍存外部 reference，不进 prompt。
2. step summary 存成可读 JSONL 或 SQLite row。
3. prompt 中只放 Mermaid / compact graph。
4. 每个 Mermaid node 带 `node_id`，可追溯到 `result_ref`。
5. LLM 需要细节时由 tool 或 operator 显式下钻。

停止条件:

- 如果没有 token pressure 或 resume pain，不做。
- 如果 Mermaid 节点不能回到 raw evidence，不做。
- 如果压缩摘要会被 durable memory 当成已审核经验，不做。

## 16. P5: agent 集成

P5 默认关闭。

集成方式:

- RAG chat:
  - 首期不做默认 prompt guidance；
  - `retrieve_memory` 继续保持显式 sidecar tool / artifact 候选，只有 P5 重新打开并选择 tool 模式后才可加入默认 tools；
  - 不改变 `retrieve_knowledge` 默认行为。
- AIOps:
  - 首个 production-affecting P5 候选固定为 labeled memory guidance，接在 `planner.py` 现有 `{experience_context}` 附近；
  - replanner 只能把 memory 当可推翻 guidance；
  - 新工具证据可以推翻旧 memory。

P5 首期集成模式决策:

- 先选 AIOps planner labeled guidance，原因是 oncall memory 的核心价值在 alert pattern / plan template，最贴近 AIOps planner。
- 不同时打开 RAG chat prompt guidance 和默认 memory tool。
- RAG chat memory tool 保持后续候选，不能作为 P5 首期默认行为。
- 任何 P5 flag-on 都必须是 owner/session 小范围开启，且 memory 文本必须带 guidance 标签、`updated_at`、`evidence_refs`、`status`。

P5 prompt 必须包含:

- memory `updated_at`
- memory `evidence_refs`
- memory `status`
- memory 是 guidance，不是 document source

停止条件:

- 如果 LLM 可能把 memory 当 citation，停止。
- 如果 replanner 看不到 memory 时间和证据，停止。
- 如果现有 RAG tests 回归，停止。

### 16.1 rollout 计划

默认关闭是安全默认值，但不能永远关闭。

P5/P6 之间必须增加 A/B rollout 计划:

| 阶段 | 条件 | 行为 |
|---|---|---|
| 关闭 | 默认 | memory 不进 prompt |
| 影子模式 | P2/P3 通过 | 只记录 memory 命中，不影响回答 |
| 小范围开启 | P6 样例通过 | 指定 owner_id / session 开启 |
| 扩大开启 | 真实负载观察通过 | 扩大开启范围 |

P6 通过后，必须明确 flag-on 条件。

## 17. P6: 评估

P6 不能只证明“没破 RAG”。

`retrieval_drift_bytes = 0` 只是健康检查，不是 memory 价值证明。

真正的 P6 门槛应该来自 oncall 场景:

| 案例 | 期望 | 是否门槛 |
|---|---|---|
| repeated alert pattern | 第二次相似告警能召回旧根因假设，并仍执行 fresh checks | 是 |
| plan reuse | planner 被过去成功 plan template 引导 | 是 |
| replanner override | 新证据能推翻 stale memory | 是 |
| stale root cause | 旧根因进入 conflict / candidate，不静默 active | 是 |
| preference query | 非配置型偏好能命中 | 观察或门槛 |
| document factual query | 文档事实仍由 RAG citation 支撑 | 健康检查 |
| mixed query | memory 控制风格，RAG 提供证据 | 门槛 |

### 17.1 P6 judge 协议冻结要求

下表的门槛指标在 judge 协议冻结前只是候选指标，不能用于 P5 flag-on。

P6 开跑前必须为每个门槛指标二选一:

| judge 类型 | 要求 |
|---|---|
| 固定规则 | 写清输入字段、success 条件、failure 条件、tie-breaker，并用 fixture 证明规则可重复 |
| 人工评判 | 写清评审人数、评审表、blind / non-blind、分歧处理、最终 owner，不允许单人事后口头裁决 |

默认建议:

- `repeated_alert_success_rate`: 优先固定规则，检查是否召回预期 alert pattern、是否仍执行 fresh checks、是否没有把 memory 当 citation。
- `plan_reuse_success_rate`: 优先固定规则，检查 planner 输出是否覆盖预期 plan steps，同时允许按新证据 replan。
- `stale_override_success_rate`: 优先固定规则，检查新工具证据是否推翻旧 memory，并把旧 memory 标记为 conflict/candidate。

如果固定规则无法覆盖真实案例，再切到人工评判，但必须在跑前冻结评审表和分歧处理规则。

指标分层:

| 指标 | 角色 | 说明 |
|---|---|---|
| `retrieval_drift_bytes` | 健康检查 | 期望 0，只证明没动 retrieval |
| `answer_text_diff_rate` | 软观察 | LLM 输出漂动，不做硬门 |
| `repeated_alert_success_rate` | 候选门槛 | judge 协议冻结后才可作为门槛 |
| `plan_reuse_success_rate` | 候选门槛 | judge 协议冻结后才可作为门槛 |
| `stale_override_success_rate` | 候选门槛 | judge 协议冻结后才可作为门槛 |
| `token_overhead` | 门槛或观察 | 超阈值则不能扩大 rollout |

`wrong-memory injection rate` 暂不做门槛。

只有具备以下条件时才能升级为门槛:

- 有错误 / 过期 memory 标注集；
- 每条样例有 expected behavior；
- 有人工或指定 judge；
- 阈值跑前冻结。

P6 closeout 后还必须完成最终文档交付:

- `docs/oncall_agent_memory_enhanced_tutorial.md`
- `docs/oncall_agent_memory_source_code_deep_dive.md`

这两份教程必须引用实际代码、测试和评估结果，不能只复述本计划。

## 18. 运营与治理

### 18.1 active memory 数量上限

P0 必须给出 active memory audit 阈值。

示例:

```text
当 active memory 数量 > N 时，记录告警或要求人工 audit。
```

N 的具体值可在 P0 决策表中填写。

如果没有阈值，P5 不能进入扩大开启阶段。

### 18.2 GC 策略

P1 只留字段:

- `last_accessed_at`
- `access_count`
- `candidate_review_deadline`

P4/P5 之后再决定:

- candidate 过期时间；
- active memory 长期未命中的 deprecated 规则；
- conflict memory 的保留周期。

### 18.3 schema 演化

P1 必须加 `schema_version`。

后续 payload schema 改动必须:

- 增加 schema version；
- 提供兼容读取；
- 不静默丢弃旧 payload。

## 19. 第一段可执行实现

只有 P0 closeout 通过后，第一段才是 P1。

P1 最小切片:

1. 新增 `MemoryRecord`。
2. 新增 typed payload models。
3. 新增 `MemoryStore`。
4. 新增 `schema_version`、`owner_id`、`last_accessed_at`、`access_count`、`candidate_review_deadline`。
5. 根据 P0 决策选择 JSON+lock 或 SQLite。
6. 写 `tests/test_memory_store.py`。
7. 不加 embedding。
8. 不接 agent。
9. 不改 `RetrievalService`。
10. 不改 `retrieve_knowledge`。
11. 不持久化 raw `MemorySaver` history。

验证:

```bash
python -m unittest tests/test_memory_store.py
python -m unittest tests/test_retrieval_service.py
```

## 20. P0 closeout checklist

P0 完成必须能勾选:

- [x] `docs/memory_fusion_development_record.md` 已创建，并记录当前 P0/P1/P2/P3/P4 状态。
- [x] 双参考源码已 clone 到本机父目录，并记录 OpenViking / TencentDB-Agent-Memory 的本地路径、commit 和 license 边界。
- [x] `docs/openviking_memory_p0_pain_evidence.md` 已写。
- [x] Gate A.1 真实痛点证据未通过，且没有用 synthetic fixture / 手写假 session 冒充。
- [x] Gate A.2 pre-launch controlled baseline / product bet 已显式记录。
- [x] `docs/openviking_memory_p0_decision_table.md` 已写，并在 2026-05-24 同步 P4 首期范围更新。
- [x] P4 范围已定: RAG chat + AIOps diagnosis，sidecar-only。
- [x] candidate extraction 时机已定: operator 显式触发。
- [x] 存储层已定: SQLite source of truth。
- [x] owner_id 来源已定: 初期固定 `"default"`。
- [x] review/promotion 工作流已定并完成 P4.5 本机实现: operator workflow + CLI；未定义认证/权限前不做 admin endpoint，不允许自动 active，`candidate_summary` 不允许 promote。
- [x] P2 词面召回同义词集合和阈值已冻结。
- [x] active memory audit 阈值已定。
- [x] 当前会话记忆升级路线已单独分层，不把 `MemorySaver` 和 durable memory 混成一层。
- [x] Tencent-style hybrid retrieval / symbolic session compression 只作为后续候选，不与 durable memory 主线混写。
- [x] Gate A.2 的 20 次 AIOps diagnosis 复评条件已有本地 SQLite 计数和 CLI status 可观测入口；复评失败时的本机 owner-scoped rollback/deprecation helper 已完成。
- [x] Gate A.2 的 30 天灰度时间锚点明确标注为 deferred；在有 gray deployment 事件源之前，不把 `deprecate-if-not-validated` 整体宣称为完全 code-enforced。
- [x] A/B rollout 条件已定。
- [x] P1 schema 与决策表一致。

## 21. 面试解释

**为什么不是直接照搬 OpenViking?**

> 本项目已有稳定 RAG 主链路，包括 MinerU artifact、Milvus 检索、结构化 citation 和 doc-level 上下文控制。OpenViking 对这里最有价值的是“分层、命名空间化、可审计的长期上下文”思想，而不是替换现有向量库或文档入库系统。所以我们只做 sidecar durable memory，并且必须先证明 oncall runtime 有真实痛点。

**为什么不是直接接 TencentDB-Agent-Memory?**

> TencentDB-Agent-Memory 是 OpenClaw / Hermes 插件，语言和运行时形态与当前 Python + LangGraph oncall agent 不同。它最值得复用的是 SQLite/FTS/vector/RRF 的混合召回、Mermaid 符号化短期记忆、node_id/result_ref 证据链和 degraded fallback 纪律。直接把插件跑起来会绕过现有 `MemoryStore`、operator review、Gate A.1/A.2、P5 default-off 边界，所以本项目采用源码参考和定向移植，而不是黑盒依赖。

**现有项目不是已经有 memory 了吗?**

> 现有 `MemorySaver` 是 LangGraph checkpointer，服务当前 `session_id` 的短期消息和图状态，而且是进程内的。它解决当前会话连续执行。durable oncall memory 解决另一个层级: 同类告警第二次出现时，agent 能不能复用过去验证过的 alert pattern、root cause、fix 和 plan template。两层并存，不互相替代。

**如果 MemorySaver 不够好，为什么不能换?**

> 可以换，但这是“当前会话记忆升级”，不是“durable memory 自动成立”。如果真实痛点是重启恢复、长工具日志压缩或 session resume，就评估 persistent checkpointer 或 Tencent-style symbolic offload；如果真实痛点是跨 session 经验复用，才继续 durable memory。两条线可以都升级，但 evidence、存储、评估和 rollback 都要分开。

**为什么 P1 就要 typed payload?**

> oncall memory 的价值在结构化经验，而不是存一段文本。alert pattern、plan template、preference 的字段完全不同。如果 P1 只放任意 dict，P2 排序、P4 去重/冲突检测、P5 prompt 组装都会退化成字符串猜测。

**为什么词面召回过不了就要 P2.5 embedding?**

> oncall 告警经常有英文缩写、中文描述和服务别名，例如 `CPUHigh` / `CPU 利用率告警` / `CPU 使用率过高`。如果只靠词面匹配召回不了这些同义表达，去重、冲突检测和计划复用都会建立在错误基础上。
