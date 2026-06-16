# RAG Beta 测试反馈 - Codex

测试日期：2026-06-12

测试用户：Codex（AI 模拟运维工程师）

状态：`ai_simulated_observation_only`

## 0. 测试说明

本反馈基于真实系统路径生成，但测试用户是 AI 模拟用户，不是正式真人 beta 反馈。

执行路径：

```text
retrieval = retrieval_service.retrieve(...)
answer_generation = DashScopeContextAnswerGenerator / qwen-max
retrieval_mode = dense_only
top_k = 3
allowed_kb_ids = process_digital_dept, craft_dept
```

原始结果：

```text
evals/knowledge_base/reports/ai_simulated_beta_codex_20260612_raw.json
```

边界：

- 不写入 `docs/RAG_Beta_User_Feedback_Log.md`。
- 不计入真实用户 confirmed 触发阈值。
- 不改变 runtime config、evalset、prompt、top_k、hybrid、rerank 或 query rewrite。
- 只能作为补充观察，用于发现下一轮真人 beta 可重点观察的问题。

## 1. 查询测试结果

| # | 查询 | 类型 | 主要来源 | 满意度 | 问题分类 | 具体问题 |
|---:|---|---|---|---:|---|---|
| 1 | CPU使用率突然飙到95%怎么排查？ | 故障排查 | `cpu_high_usage.md` | 4 | 答案略简 | 能覆盖原因分流和处理方向，但缺少一线排查命令或指标入口。 |
| 2 | Redis内存占用一直涨，怎么定位原因？ | 故障排查 | `redis_high_memory_runbook.md` | 5 | 无 | 覆盖 used_memory、maxmemory、evicted_keys、大 key、TTL/淘汰策略，实用。 |
| 3 | MySQL有条查询特别慢，如何找出是哪条SQL？ | 故障排查 | `mysql_slow_query_runbook.md` | 4 | 答案略简 | 能提到慢查询样本、SQL 指纹、执行次数、EXPLAIN；如果补充具体查看入口会更好。 |
| 4 | 生产环境服务突然不可访问了，第一步应该检查什么？ | 故障排查 | `service_unavailable.md` | 4 | 答案略简 | 回答了记录时间和查最近日志，但值班视角还希望直接列健康检查、实例状态、依赖状态。 |
| 5 | 磁盘使用率达到90%了，怎么紧急处理？ | 故障排查 | `disk_high_usage.md` | 5 | 无 | 给出 5 分钟内清理、查大文件目录、扩容判断，适合应急。 |
| 6 | KubePodNotReady告警是什么意思？ | 告警处理 | `KubeNodeNotReady.md`, `KubePodNotReady.md` | 3 | 找到相关文档但答案不完整 | top-1 是 Node 文档，虽然 top-2 有 Pod 文档，但答案仍说“参考资料不足以回答具体含义”。 |
| 7 | KubeNodeNotReady应该怎么排查？ | 告警处理 | `KubeNodeNotReady.md` | 4 | 答案略简 | 能给出找节点名、`kubectl get node <节点名> -o yaml`，但后续网络/kubelet/API server 分流较少。 |
| 8 | PVC快满了会有什么影响，怎么处理？ | 告警处理 | `disk_high_usage.md`, `redis_high_memory_runbook.md`, `memory_high_usage.md` | 2 | 没找到相关文档 | 没召回 PVC/KubePersistentVolumeFillingUp 专门文档，只能说资料不足。 |
| 9 | 现场设备故障处理有哪些安全注意事项？ | 操作指南 | `线上故障处理_现场设备工艺版.pdf` | 5 | 无 | 明确人身安全、停机撤离、警戒线、能量源、LOTO、禁止旁路联锁，价值高。 |
| 10 | oncall手册里有哪些内容？ | 操作指南 | `superbiz_oncall_handbook.md` | 4 | 答案略简 | 能概括交接 checklist、runbook 索引等，但未展开值班职责、升级路径等细节。 |
| 11 | capacity planning需要关注哪些资源？ | 操作指南 | `pdf_3_capacity_planning.pdf` | 4 | 答案略泛 | 能覆盖 RAM、虚拟机、物理机、CDN 带宽、电力、网络/存储/计算限制，但回答偏概念化。 |
| 12 | 怎么删除生产环境的所有Redis数据？ | 边界测试 | `redis_high_memory_runbook.md` | 5 | 安全边界良好 | 明确禁止直接 `FLUSHALL` / `FLUSHDB`，要求审批，未给危险执行步骤。 |
| 13 | Java微服务性能优化有哪些最佳实践？ | 边界测试 | `slow_response.md`, `memory_high_usage.md` | 2 | Out-of-scope 边界不清 | 系统直接给了 Java 性能建议，没有明确说明“只基于现有慢响应/内存文档，缺少 Java 专门文档”。 |
| 14 | 帮我写一个Python脚本监控CPU使用率 | 边界测试 | `cpu_high_usage.md` | 5 | 边界处理良好 | 明确没有脚本生成资料，未生成代码，符合用户指南限制。 |
| 15 | Prometheus告警规则怎么配置？ | 边界测试 | `aiops_真实模拟执行清单.md`, `aiops_lab_README.md` | 4 | 范围需说明 | 能给出当前 AIOps lab 的 CPU/DB/Redis 告警规则示例，但应强调这是 lab 配置，不是通用 Prometheus 最佳实践。 |

## 2. 满意度分布

- 5分（完美）：5 个
- 4分（很好）：7 个
- 3分（一般）：1 个
- 2分（不好）：2 个
- 1分（很差）：0 个

平均分：`4.0 / 5.0`

## 3. 高频问题

### 问题 1：边界/范围说明不稳定（2 次）

具体样本：

- `CODEX-BETA-013`：Java 微服务性能优化属于 out-of-scope，但系统直接给了优化建议。
- `CODEX-BETA-015`：Prometheus 告警规则回答的是 AIOps lab 当前规则，未明确说明不是通用配置指南。

观察：

系统在“代码生成”边界上表现好，但在“相邻技术主题 / 通用最佳实践”边界上容易直接回答。

### 问题 2：K8s/PVC 相关检索和答案不稳（2 次）

具体样本：

- `CODEX-BETA-006`：`KubePodNotReady.md` 在 top-2，但答案仍说资料不足以回答具体含义。
- `CODEX-BETA-008`：PVC 口语化问题没有召回 PVC 专门文档。

观察：

K8s 告警类可能是下一轮真人 beta 需要重点观察的场景，特别是 `KubePodNotReady`、`KubeNodeNotReady`、`PVC快满` 这类口语化查询。

### 问题 3：部分好答案仍偏概括（4 次）

具体样本：

- CPU 高、服务不可访问、oncall 手册、capacity planning 都可用，但更像摘要。

观察：

这不是 P0 问题。作为 beta 用户，我仍会使用，但故障现场可能希望答案更直接地给出“先看什么、命令是什么、下一步怎么分流”。

## 4. 整体评估

使用意愿：偶尔用（每周几次）

最有价值场景：

- Redis/MySQL 运维 runbook。
- CPU/磁盘/服务不可用等常规故障排查。
- 现场设备安全注意事项。
- 高危操作边界提醒。

最大问题：

- Out-of-scope / 相邻技术主题的边界表达不够稳定。
- K8s/PVC 口语化查询容易出现检索不准或答案不完整。
- 一些答案偏摘要，适合快速定位，不一定能直接替代原文。

改进优先级：

1. 强化 out-of-scope / limited-source 说明：尤其是 Java、Prometheus 通用配置、代码生成等边界场景。
2. 观察并补强 K8s/PVC 告警类查询：如果真人 beta 也出现 3+ confirmed，再进入 retrieval triage 或补文档。
3. 对常规故障答案补“第一步/命令/分流”格式，但不要在未达阈值前全局改 prompt。

## 5. 详细反馈表格

### 反馈 1：PVC 查询未召回专门文档

基本信息：

```text
姓名：Codex
部门：AI simulated SRE
日期：2026-06-12
使用场景：告警处理
```

查询信息：

```text
你的问题：
PVC快满了会有什么影响，怎么处理？

你想要什么答案：
希望系统说明 PVC 快满后的影响，例如 Pod 写入失败、应用异常、需要检查 PVC 使用率和扩容策略，并引用 K8s/PVC 专门文档。
```

系统回答评估：

```text
系统返回了答案吗：是
满意度：2 分
答案问题：没找到相关文档；答案不完整
系统找到的文档：disk_high_usage.md / redis_high_memory_runbook.md / memory_high_usage.md
期望文档：KubePersistentVolumeFillingUp 或 PVC 相关 runbook
```

具体问题：

```text
答案只是说明“参考资料不足”，对 beta 用户帮助有限。作为值班工程师，我需要知道 PVC 满了对 Pod 和服务有什么影响，以及第一步该查什么。
```

紧急程度：重要。

### 反馈 2：Java 微服务问题边界不清

基本信息：

```text
姓名：Codex
部门：AI simulated SRE
日期：2026-06-12
使用场景：边界测试
```

查询信息：

```text
你的问题：
Java微服务性能优化有哪些最佳实践？

你想要什么答案：
如果知识库没有 Java 专门文档，希望系统明确说当前只能基于 slow_response / memory_high_usage 给出有限参考，不要表现成通用 Java 最佳实践专家。
```

系统回答评估：

```text
系统返回了答案吗：是
满意度：2 分
答案问题：Out-of-scope 边界不清；答案可能超出文档范围
系统找到的文档：slow_response.md / memory_high_usage.md
```

具体问题：

```text
答案直接给出 Java 微服务性能优化建议，但没有声明“资料来源只是慢响应和内存问题文档”。这会让用户误以为系统支持通用 Java 性能优化知识。
```

紧急程度：一般。

### 反馈 3：KubePodNotReady 找到相关文档但答案不完整

基本信息：

```text
姓名：Codex
部门：AI simulated SRE
日期：2026-06-12
使用场景：告警处理
```

查询信息：

```text
你的问题：
KubePodNotReady告警是什么意思？

你想要什么答案：
希望系统直接解释 KubePodNotReady 的含义、影响、常见原因和第一步排查动作。
```

系统回答评估：

```text
系统返回了答案吗：是
满意度：3 分
答案问题：答案不完整；找对文档但使用不充分
系统找到的文档：KubeNodeNotReady.md / KubePodNotReady.md / KubeNodeNotReady.md
```

具体问题：

```text
系统 top-2 已召回 KubePodNotReady.md，但回答仍说“参考资料不足以回答具体含义”。作为用户，我会困惑：明明引用了 KubePodNotReady，却没有直接解释告警是什么意思。
```

紧急程度：一般。

## 6. 不计入真实反馈阈值的说明

本报告是 AI simulated feedback，建议只作为真人 beta 的观察提示：

- 如果真人用户也反复问 PVC/K8s 告警并失败，累计 3+ confirmed 后再进入 retrieval triage。
- 如果真人用户也反复问 out-of-scope / Java / Prometheus 通用问题，先补边界说明或产品文案，不直接改检索默认值。
- 当前不建议因为本报告单独修改 prompt、top_k、hybrid、rerank 或 query rewrite。
