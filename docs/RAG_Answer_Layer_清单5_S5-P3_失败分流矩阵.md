# RAG Answer Layer 清单5 S5-P3 失败分流矩阵

状态：`s5_p31_eval_standard_repaired_answer_pilot_still_failed`

生成日期：2026-06-11

## 1. 范围

本文件只做 S5-P2 Answer Pilot 20q baseline 的失败分流。它不是新的 evalset，不是 prompt 改动方案，也不是 retrieval 默认切换依据。

输入：

- Evalset: `evals/knowledge_base/evalsets/department_rag_answer_pilot_20q.jsonl`
- Baseline report: `evals/knowledge_base/reports/department_rag_answer_pilot_20q_baseline_20260611.json`
- 只读复核：对 18 个失败样本重新跑 `dense_only` top-3/top-10 retrieval，查看 top-3 context 和 expected doc/chunk 排名

边界：

- 不创建 RAGAS / LLM-as-judge 门禁
- 不进入 agent_behavior 层
- 不调整 answer prompt
- 不修改 `rag_default_retrieval_mode`
- 不修改 `rag_query_rewrite_mode`
- 不修改 `rerank_enabled`
- 不修改 `app/config.py` 或 `.env`

## 2. S5-P2 基线事实

| 指标 | 数值 |
|---|---:|
| total | 20 |
| passed | 2 |
| failed | 18 |
| not_ready | 0 |
| context_missing_facts | 16 |
| answer_missing_facts | 2 |
| citation_required_but_missing | 0 |
| unsupported_claim_count | 0 |
| permission_leak_count | 0 |
| source_ref_unresolvable_count | 0 |
| retrieval_layer_failed_count | 0 |

解释：安全、引用、权限、source_ref 和 retrieval hard boundary 没有退化。S5-P2 的失败主要不是“模型乱编”或“越权”，而是 required facts 与当前 top-3 context / deterministic fact matcher 的关系需要进一步拆开看。

## 3. 分流结果

| 分流类别 | 样本数 | 含义 |
|---|---:|---|
| `eval_fact_granularity_review` | 13 | 需要人工复核 `must_include_facts` 是否过细、过度摘要、跨语言语义匹配过严，或 source_support/chunk 定位是否需要修正 |
| `answer_prompt_policy_candidate` | 2 | top-3 context 已包含 required facts，但 qwen-max 答案漏掉部分事实 |
| `top_k_candidate` | 1 | 目标排查步骤 chunk 在 top-10 但不在 top-3，较像 top-k/context 覆盖不足 |
| `mixed_context_gap` | 1 | 同时存在 context policy/top-k/fact 粒度问题 |
| `mixed_context_and_answer_gap` | 1 | 同时存在 context 缺口、答案漏写和 fact 粒度问题 |

按原因看：

- `top_k`: 1 个明确候选
- `chunk`: 0 个明确候选
- `context-policy`: 2 个混合候选
- `eval-fact-粒度`: 13 个主要候选，另有 2 个混合候选也需要 fact 粒度复核
- `answer-prompt/policy`: 2 个主要候选，另有 1 个混合候选涉及答案漏写

当前结论：不能直接说“检索坏了”，也不能直接调 prompt。多数失败先要人工 review `must_include_facts` 和 source_support/chunk 定位。

## 4. 逐题矩阵

| sample_id | S5-P2 失败类型 | Top-3 context 摘要 | 缺失 facts | 原因分类 | 下一步 |
|---|---|---|---|---|---|
| `S5P1-MD-001` | `answer_missing_facts` | `cpu_high_usage.md` 的问题描述、常见原因、排查步骤均在 top-3 | 答案漏写 `cpu_usage > 80/service_name`，漏写结合应用日志判断死循环、流量突增、定时任务或慢 SQL | `answer-prompt/policy` | 记录为 prompt/policy 候选；先不全局调 prompt，等 fact 粒度复核后做小样本 shadow |
| `S5P1-MD-002` | `context_missing_facts` | top-3 是 `service_unavailable.md` 常见原因、问题描述、参考文档；`排查步骤` 在 top-10 rank 4 | 最近 15 分钟 `application-logs`、`ERROR/FATAL/status:500`、`restart/crash/oom_kill` 和依赖服务状态 | `top_k` | 明确 top-k 候选；人工 review 后可单独试 `top_k=5` 或 doc-level aggregation，仍不改默认 |
| `S5P1-MD-004` | `context_missing_facts` | top-3 包含 `KubePodNotReady.md` Meaning/Impact，也混入 `KubeNodeNotReady.md` Meaning | 15 分钟 non-ready、readiness probe、Pending 到 namespace/node | `eval-fact-粒度` | 复核中文 fact 与英文原文的 deterministic 匹配；必要时改成更贴近原文的 atomic facts |
| `S5P1-MD-005` | `context_missing_facts` | top-3 包含 `KubeNodeNotReady.md` Diagnosis/Meaning/Mitigation | 通知详情中的 node、API 或 kubelet timeout 等原因 | `eval-fact-粒度` | 复核 `must_include_facts` 是否把示例/原因写得过细；不先改 chunk |
| `S5P1-MD-006` | `context_missing_facts` | top-3 包含 `KubePersistentVolumeFillingUp.md` Impact/Diagnosis/Meaning | volume filling up、原因很多、runbook 不覆盖应用特定原因 | `eval-fact-粒度` | 复核英文原文到中文 fact 的粒度；必要时拆成可稳定匹配的短 fact |
| `S5P1-MD-007` | `answer_missing_facts` | 人民网中车长客数字化转型文档 top-3 命中，包含产线、AI 视觉、业数融合等内容 | 答案漏写 AI 视觉关键工序管控、数据中心贯通多平台数据 | `answer-prompt/policy` | 记录为 prompt/policy 候选；后续只在小样本 shadow 验证“必须覆盖事实点”提示是否有效 |
| `S5P1-MD-008` | `context_missing_facts` | top-3 是 oncall handbook 头部、Runbook 索引、Quick Links | context 缺告警分级/SLA、升级矩阵/IC/checklist；答案漏值班轮换规则 | `context-policy + top_k + eval-fact-粒度` | 混合问题；先 review 是否把目录级事实写得过密，再考虑 section/doc-level context |
| `S5P1-PDF-001` | `context_missing_facts` | PagerDuty PDF top-3 是 Home、Additional Resources、Don't know where to start | 覆盖流程的一部分、内部文档精简版、重大事故和新员工 on-call、事故前中后 | `eval-fact-粒度` | 复核这些摘要 fact 是否都能从 page 1 chunk 直接稳定支持；必要时改 source_support/facts |
| `S5P1-PDF-002` | `context_missing_facts` | Reliability Budgets top-3 是 Benefits、标题页、Unreliability Budgets | 季度单位、SLO 目标和实际 uptime 差额 | `eval-fact-粒度` | 复核 fact 是否应拆成 SLO/objective metrics/uptime difference 等原文粒度 |
| `S5P1-PDF-003` | `context_missing_facts` | Capacity Planning top-3 是 Conclusion、Systems scaling、What Is Capacity | 受约束资源、bottom-up capacity/primary drivers、theoretical minimum capacity | `eval-fact-粒度` | 复核 source_support 是否跨多个 chunk；如果是跨 chunk 事实，先调整 eval fact，不先调系统 |
| `S5P1-PDF-004` | `context_missing_facts` | Scoutflo top-3 偏 Clone repository、Video Tutorials、Navigate repository；top-10 仍偏 metadata/support | AWS/Kubernetes/Sentry、414 playbooks | `eval-fact-粒度` / source-support review | 先人工核对 `source_support` 指向的 overview chunk 是否真的可稳定召回；若确认题目合理，再重分类为 context-policy/top-k 候选 |
| `S5P1-PDF-005` | `context_missing_facts` | Systems Performance top-3 是 6.6 Analysis、Cycle Analysis、Tools Method | uptime/vmstat/mpstat/sar/ps 等工具，负载/CPU 平均值/profiling/tracing/计数器用途 | `eval-fact-粒度` | 表格/枚举 fact 过长，先拆成更小 atomic facts 并核对 table chunk |
| `S5P1-PDF-007` | `context_missing_facts` | PagerDuty top-3 是 Don't know where to start、Training、Training Guides | context 缺 Training Overview/术语表；答案漏第 3 页、Guides、Training Course | `context-policy + answer-prompt/policy + eval-fact-粒度` | 混合问题；先核对 page/chunk source_support，再决定是 context policy 还是答案漏写 |
| `S5P1-PDF-008` | `context_missing_facts` | Capacity Planning top-3 是 THEORETICAL MINIMUM CAPACITY 两个 chunk 和 Conclusion | context 缺增长指标与观察容量关联、设计固有膨胀；答案漏 theoretical minimum blow-up | `eval-fact-粒度` | 复核原文是否支持中文摘要 fact；将语义归纳改成更可判定的短 fact |
| `S5P1-PDF-009` | `context_missing_facts` | Scoutflo top-3 偏 Resources、Navigate repository、Essential Links；top-10 有 Kubernetes Issues Path | 第 4-5 页、Folder Structure、Networking/Storage/RBAC、Pod lifecycle 等 | `eval-fact-粒度` / source-support review | 先核对期望 page/chunk；若目标 folder structure 不稳定进入 context，再作为 context-policy/top-k 候选 |
| `S5P1-PDF-010` | `context_missing_facts` | Systems Performance top-3 包含 6.6 Analysis、table `t00008`、Other Tools | context 缺 Linux/Solaris 两列、工具枚举；答案漏 Table 6-6 | `eval-fact-粒度` | 表格事实需要拆短，并确认 table serialization 是否足够表达列名和用途 |
| `S5P1-PDF-011` | `context_missing_facts` | Scoutflo top-3 包含 Kubernetes Playbooks、Quick Lookup by Alert Name、KubeNodeNotReady Diagnosis | context 缺 `t00002` 证据和 KubePodNotReady negative fact；答案漏 Quick Lookup 表名 | `eval-fact-粒度` | 复核 negative fact 是否应作为 must_include；如果保留，需要 table-aware 判定而非普通句子匹配 |
| `S5P1-PDF-012` | `context_missing_facts` | Systems Performance top-3 包含 6.6 Analysis、table `t00008`、Cycle Analysis | 表格列名、DTrace/perf 和 perf/cpustat 及用途 | `eval-fact-粒度` | 表格枚举 fact 拆短；确认 table context 足够后再复跑 answer baseline |

## 5. 分流后的执行顺序

1. 人工 review 13 个 `eval_fact_granularity_review` 和 2 个混合样本。
   - 重点检查 `must_include_facts` 是否过细、是否跨 chunk、是否把概括性解释写成必须逐字命中的事实。
   - PDF/table 样本要回查 `chunk_id`、`table_id`、page/source_ref 是否能直接支撑 required facts。

2. 修正 eval/source_support 后重跑 Answer Pilot baseline。
   - 目标不是把标准放松到“好看”，而是把不可稳定判定的事实改成可回查、可解释、可复跑的事实。

3. 如果复核后仍有多个 top-k/context-policy 样本，再做 observation-only top-k/doc-level probe。
   - 当前只有 `S5P1-MD-002` 是明确 top-k 候选，不足以推动默认 top_k 或 retrieval mode 改动。

4. 如果复核后 answer-prompt/policy 候选仍成立，再做小样本 prompt shadow。
   - 当前明确 answer-prompt/policy 候选只有 `S5P1-MD-001` 和 `S5P1-MD-007`。
   - `S5P1-PDF-007` 是混合问题，不能先用来证明 prompt 需要全局改。

## 6. 当前决策

`answer_pilot_failed` 仍成立，但 S5-P3 不支持立即做以下动作：

- 不上 RAGAS 作为门禁
- 不启用 LLM-as-judge 作为门禁
- 不进入 agent_behavior 层
- 不切 hybrid
- 不开 rerank
- 不开 query rewrite
- 不盲目调 answer prompt

S5-P3.1 已按本矩阵修正 eval fact/source_support 并重跑 S5 answer baseline。修正后仍未达到通过线，因此下一步不继续放宽考卷，而是进入 observation-only probe：小样本 answer prompt/policy、top_k/doc-level context、Scoutflo PDF source-support/chunk 定位。

## 7. S5-P3.1 修正后结果

S5-P3.1 修正范围：

- 修正 `department_rag_answer_pilot_20q.jsonl` 中过细或跨语言匹配过严的 `must_include_facts`
- 为 deterministic fact check 支持显式 alias（`A||B`）
- 修复 `must_not_include_claims` 整句禁止项的模糊误报，避免把“答案包含 LOTO 安全要求”误判成“省略 LOTO 安全要求”
- 不修改 query、expected docs、retrieval mode、top_k、answer prompt 或默认配置

修正后真实 baseline：

| 指标 | 数值 |
|---|---:|
| report | `department_rag_answer_pilot_20q_baseline_after_s5_p31_repair_20260611.json` |
| total | 20 |
| passed | 13 |
| failed | 7 |
| pass_rate | 0.65 |
| not_ready | 0 |
| answer_missing_facts | 4 |
| context_missing_facts | 3 |
| citation_required_but_missing | 0 |
| unsupported_claim_count | 0 |
| permission_leak_count | 0 |
| source_ref_unresolvable_count | 0 |
| retrieval_layer_failed_count | 0 |

最终判定：`s5_p31_eval_standard_repaired_but_answer_pilot_still_failed`。

保留失败样本：

| sample_id | failure_category | 下一步 |
|---|---|---|
| `S5P1-MD-001` | `answer_missing_facts` | Answer prompt/policy shadow |
| `S5P1-MD-002` | `context_missing_facts` | `top_k=5` 或 doc-level context shadow |
| `S5P1-MD-007` | `answer_missing_facts` | Answer prompt/policy shadow |
| `S5P1-PDF-001` | `answer_missing_facts` | 观察 LLM 生成波动，暂不作为全局 prompt 依据 |
| `S5P1-PDF-002` | `answer_missing_facts` | 观察 LLM 生成波动，暂不作为全局 prompt 依据 |
| `S5P1-PDF-004` | `context_missing_facts` | Scoutflo overview chunk/source-support 复核 |
| `S5P1-PDF-009` | `context_missing_facts` | Scoutflo Kubernetes folder chunk/source-support 复核 |

边界保持：不进入 Answer 50q，不进入 RAGAS 扩充，不进入 agent_behavior 层，不启用 hybrid/rerank/query rewrite，不改默认配置。
