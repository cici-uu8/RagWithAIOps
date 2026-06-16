# 双参考 Memory P0 决策表

日期: 2026-05-24

最近更新: 2026-05-25

## 1. P0 总体决策

当前 P0 verdict:

- Gate A.1 real oncall evidence 未通过。
- Gate A.2 pre-launch controlled baseline / product bet 通过。
- 允许推进默认关闭的 sidecar memory schema/store/retrieval/artifact/candidate-extraction 能力，但不接 agent prompt，不改变 `retrieve_knowledge` / `RetrievalService` / citation 语义。
- 2026-05-25 更新: 记忆系统升级从 OpenViking 单参考改为 OpenViking + TencentDB-Agent-Memory 双参考源码复用策略；两个参考仓库已 clone 到父目录，后续实现优先看源码和 license 边界再写本项目代码。

原因见 `docs/openviking_memory_p0_pain_evidence.md`: 本仓库当前没有生产或准生产 oncall 证据，但本机代码事实足以证明当前系统没有跨 session durable memory lookup / store / review path。该结论只能支撑 pre-launch product bet，不能冒充真实痛点证据。

## 2. 必填决策表

| 决策项 | 当前决策 | 影响 |
|---|---|---|
| 参考源码复用策略 | 2026-05-25 更新: 双参考；OpenViking 用于 namespace/context level/retrieval trace 思路，TencentDB-Agent-Memory 用于 SQLite/FTS/vector/RRF、symbolic session offload、degraded fallback 工程参考 | 后续 P2.6/P4.6/P4.7 不从空白处生成方案；先查 `/Users/cici/oncall agent/OpenViking` 与 `/Users/cici/oncall agent/TencentDB-Agent-Memory` 的源码 |
| license 边界 | OpenViking 为 AGPL-3.0，默认 idea-level / architecture-level 复用；TencentDB-Agent-Memory local `LICENSE` body 于 2026-05-25 核实为 MIT，`package.json` 也写 MIT；GitHub metadata 如返回 `NOASSERTION`，不覆盖本地 LICENSE 结论 | 不在 license 决策没说清前复制 OpenViking 代码；Tencent TS->Python port 仍要最小适配、注明来源，并在真正代码移植 PR 里再次核对 pinned commit 的 LICENSE |
| 当前会话记忆升级路线 | 2026-05-25 更新: 当前保持 `MemorySaver` + accessor；如果出现 token pressure、工具日志膨胀、重启恢复痛点，再单独评估 persistent checkpointer 或 Tencent-style Mermaid symbolic offload | 这条路线不等于 durable memory；不能拿 session compression 结果冒充 reviewed active memory |
| durable memory 检索路线 | 当前已完成 lexical sidecar retrieval；P2.6 增加 Tencent-style hybrid retrieval 候选，但不自动启动 | 只有真实/灰度召回不稳、active memory 增长或 shadow 证据需要时，才引入 FTS/vector/RRF；仍不动 RAG citation |
| P4 首期范围 | 2026-05-24 更新: 覆盖 RAG chat + AIOps diagnosis，但保持 operator 显式触发、sidecar-only | RAG 只生成 `candidate_summary` 并通过 `SessionHistoryAccessor` 去掉 raw checkpoint 依赖；AIOps 生成 `plan_template` candidate。两者都不进默认 prompt，不改变 `retrieve_knowledge` / citation |
| candidate extraction 时机 | operator 显式触发；本机 CLI 已支持 normalized JSON snapshot | 最可控；不增加用户请求延迟；不引入后台任务重启窗口；`extract-rag-session` / `extract-aiops-session` 只读取 operator-provided snapshot，不读取 live cross-process `MemorySaver`；生产 session/log source 和后台页面仍待后续定义 |
| 存储层 | P1 使用 SQLite | Python 标准库可用；比裸 JSON `read -> modify -> write_text` 更适合 review / promote / conflict 状态写入；embedding index 仍只能是检索视图 |
| owner_id 来源 | 初期固定 `"default"` | 单租户阶段最小化接口改动；字段必须保留，后续可迁移到 tenant / team / user |
| review/promotion | P4.5 已实现本地 operator workflow + CLI；不做 admin endpoint | `approve` 必须带 `reviewer_id` + `decision_note` 并写入 review audit；`candidate_summary` 不能 promote；没有认证 / 权限设计前，不开放后台管理接口；candidate 不能自动 active |
| P2 词面召回阈值 | 10 条 query 中至少 7 条召回预期 active memory | 低于阈值则停止 P2，触发 P2.5 判定，并默认进入 P2.6 Tencent-style hybrid retrieval 设计；embedding-only 只允许做受控 spike，不能直接接 P3/P4/P5 |
| active memory audit 阈值 | 每个 owner active memory > 100 条时要求人工 audit；> 200 条时停止自动 promote | 防止长期记忆池无限膨胀；P5 扩大 rollout 前必须可观测 |
| A/B rollout | 默认 off；P2/P3 后 shadow；P6 后指定 owner/session 小范围开启 | durable memory 不能默认进 prompt；必须先证明不污染 citation 和新证据判断 |
| P5 首期集成模式 | 若 P5 重新打开，首个 production-affecting slice 固定为 AIOps planner labeled memory guidance，接在 `{experience_context}` 附近；RAG chat memory tool 保持后续候选 | 不同时打开 RAG prompt guidance 和默认 memory tool；P5 flag-on 必须 owner/session scoped，并带 memory label、`updated_at`、`evidence_refs`、`status` |
| P6 judge 协议 | 进入 P6 前必须为 repeated alert / plan reuse / stale override 冻结固定规则或人工评审协议 | 未冻结 judge 协议前，相关 success_rate 只能是候选指标，不能作为 flag-on gate |
| deprecate-if-not-validated | 2026-05-25 修订: code-enforced 分支只有累计 20 次 AIOps diagnosis 后复评；已实现 SQLite 计数和 CLI status / record 入口，并补充 owner-scoped rollback helper。首次灰度部署后 30 天分支明确 deferred，直到有 gray deployment 事件源 | 若复评没有真实复用价值证据，应 deprecated / rollback memory 子系统，不扩大 rollout；当前 rollback 是非删除式状态标记 + review audit，不删除 SQLite，不清空 policy events；不能把 30 天分支算作已 code-enforced |
| 复评 owner | `runtime owner TBD` | 进入 P5/P6 前必须替换成真实 owner |

## 3. P2 词面召回冻结样例

第一组 P2 lexical gate 先围绕 `HighMemoryUsage` / `HighCPUUsage` 类告警冻结。示例 query:

| query_id | query | expected memory |
|---|---|---|
| Q01 | `HighMemoryUsage` | memory usage alert pattern |
| Q02 | `内存使用率过高告警` | memory usage alert pattern |
| Q03 | `memory usage above 85 percent` | memory usage alert pattern |
| Q04 | `OOM 之后怎么排查` | memory usage alert pattern / plan template |
| Q05 | `GC overhead 导致服务变慢` | memory usage alert pattern |
| Q06 | `HighCPUUsage` | cpu alert pattern |
| Q07 | `CPU 利用率告警` | cpu alert pattern |
| Q08 | `CPU 使用率过高` | cpu alert pattern |
| Q09 | `service A CPU spike` | cpu alert pattern |
| Q10 | `频繁 GC 伴随 CPU 飙高` | cpu / memory related alert pattern |

通过标准:

- 至少 7/10 命中预期 memory。
- 命中结果必须是独立 `MemoryRetrievalResult`，不能伪装成文档 `RetrievalResult` 或 `SourceRef`。
- 如果只命中文档 KB，不计入 memory lexical gate。

2026-05-24 explicit run:

- fixture: `tests/fixtures/memory_synthetic/p2_lexical_recall_cases.json`
- source: `design-fixture, NOT real session evidence`
- result: 10/10 expected hits (`mem_alert_cpu_high`)
- verdict: P2 lexical gate passed; P2.5 embedding retrieval not triggered under the frozen synthetic gate.

## 4. P1 schema 对齐要求

P1 schema 必须继续满足:

- `MemoryRecord.schema_version = 1`
- `owner_id` 必填，初期为 `"default"`
- typed payload 必填，不允许长期裸 `dict`
- `status` 只允许 `active` / `candidate` / `conflict` / `deprecated`
- `evidence` 必填
- `candidate_review_deadline`、`last_accessed_at`、`access_count` 必须存在
- 不存 raw `MemorySaver` history
- 不修改 `RetrievalService`
- 不修改 `retrieve_knowledge` 默认行为

## 5. 当前边界

本轮 P0 决策允许推进默认关闭的 sidecar memory 能力；截至 2026-05-24 已完成 P1-P4.5 本机实现，补齐 P4 operator extraction CLI 的 normalized snapshot 入口，并把 Gate A.2 的 20 次 AIOps diagnosis 复评条件落成 operator-only SQLite 计数 / status 可观测入口。复评失败时可由 operator 显式执行 owner-scoped deprecation helper，把非 deprecated memory 记录标记为 `deprecated` 并留下 review audit；该 helper 不自动触发、不删除数据、不打开 prompt 或 production rollout。

2026-05-25 双参考更新后的额外边界:

- 允许把 `/Users/cici/oncall agent/OpenViking` 和 `/Users/cici/oncall agent/TencentDB-Agent-Memory` 作为只读源码参考。
- 允许在计划层新增 P2.6 hybrid recall、P4.6 current-session memory upgrade、P4.7 symbolic session compression 候选。
- 不允许直接接入 OpenViking server/session engine。
- 不允许直接把 TencentDB-Agent-Memory 作为 OpenClaw/Hermes plugin 运行在本项目里。
- 不允许绕过当前 `MemoryStore` / review / candidate / P5 default-off 边界。

允许新增:

- `app/models/memory.py`
- `app/models/memory_candidate.py`
- `app/services/memory_store.py`
- `app/services/memory_retrieval_service.py`
- `app/services/session_history_accessor.py`
- `app/services/memory_candidate_service.py`
- `app/cli/memory_operator.py`
- `app/tools/memory_tool.py`
- `tests/test_memory_store.py`
- `tests/test_memory_retrieval_service.py`
- `tests/test_memory_tool.py`
- `tests/test_memory_candidate_service.py`
- `tests/test_memory_operator_cli.py`
- 明确标注的 `tests/fixtures/memory_synthetic/` 测试夹具

禁止在当前证据状态下新增:

- 默认 agent prompt 注入逻辑
- 改变 `retrieve_knowledge` 默认行为
- 改变 `RetrievalService` / `RetrievalResult` / `SourceRef` citation 语义
- 把 synthetic fixture 写进 Gate A.1 real evidence

后续如果提供真实生产或准生产案例，应追加到 `docs/openviking_memory_p0_pain_evidence.md` 的 Gate A.1 区域，并保留 2026-05-24 A.2 product-bet 记录。
