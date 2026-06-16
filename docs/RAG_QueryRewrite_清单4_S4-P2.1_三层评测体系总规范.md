# RAG Query Rewrite 清单 4 S4-P2.1 三层评测体系总规范

日期：2026-06-10

状态：`eval_system_spec_done_no_new_eval_run`

对应清单：`docs/RAG_QueryRewrite_语料扩充与表达缺口评测清单4.md`

---

## 0. 结论

清单 4 后续评测固定分三层：

```text
retrieval       = 检索层，先测找没找对资料和证据链是否可回查
answer          = 回答层，再测基于资料生成的答案是否忠实、相关、正确
agent_behavior  = Agent 行为层，最后测工具调用、权限、审计和多步证据是否完整
```

当前 50q mixed baseline 属于 retrieval 层，不等于完整 RAG/Agent 体验验收。

RAGAS / LLM-as-judge 只允许作为 answer 层补充，不能替代 retrieval 层和 agent_behavior 层的确定性硬门禁。

当前默认配置继续保持：

```text
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
default_switch_eligibility = not_eligible_for_default_switch
```

---

## 1. 为什么要分三层

如果只问“答案好不好”，失败原因会混在一起：

- 可能是检索没有找到正确文档。
- 可能是找到了文档，但 source_ref / citation 不可回查。
- 可能是检索结果正确，但 LLM 回答遗漏或编造。
- 可能是工具调用、权限过滤、审计链或 AIOps 证据链不完整。

所以清单 4 后续所有 RAG、rerank、chunk、query rewrite、模型变更，都必须先说明它影响哪一层，再跑对应门禁。

---

## 2. 三层评测对象

| 层级 | 评测对象 | 主要问题 | 当前状态 |
|---|---|---|---|
| retrieval | 检索、排序、chunk、source_ref、scope | 能不能找对资料，证据能不能回查 | 已有 mixed 50q 第一版 baseline |
| answer | 基于检索上下文生成的回答 | 是否忠实、相关、正确、完整 | 待建 answer eval |
| agent_behavior | 工具调用、多步计划、审计、权限、AIOps 证据 | Agent 是否按规则行动且可审计 | 已有零散门禁，待统一矩阵 |

规则：

- retrieval 层先过，才能解释 answer 层结果。
- answer 层不能绕过 retrieval 的 source_ref / scope 失败。
- agent_behavior 层不能用答案分数代替工具和审计证据。

---

## 3. 现有 evalset / report 分层

| 产物 | 层级 | 用途 | 当前结论 |
|---|---|---|---|
| `department_rag_mixed_markdown_pdf_50q.jsonl` | retrieval | mixed Markdown+PDF 检索基线 | dense-only 32/50，需失败分流 |
| `checklist4_mixed_50q_readiness_20260610.json` | retrieval | 语料和 evalset readiness | ready，gaps 为空 |
| `department_rag_permission_isolation_10q.jsonl` | retrieval / agent_behavior | KB 权限隔离 | 已作为 E1 guardrail |
| `department_rag_scope_lock_10q.jsonl` | retrieval | scope 锁定 | 已作为 E1 guardrail |
| `department_rag_citation_accuracy_10q.jsonl` | retrieval / answer | citation/source_ref 可解析 | 已作为 E1 guardrail |
| `checklist3_long_session_shadow_report.py` | agent_behavior | session memory shadow 不污染 prompt | 已通过 synthetic shadow |
| `checklist3_long_log_offload_shadow_report.py` | agent_behavior | long tool result offload 可回查 | 已通过 synthetic shadow |
| `checklist3_rerank_shadow_report.py` | retrieval | rerank shadow readiness | 仅证明可观测，不证明收益 |
| AIOps P6/P7 memory evals | agent_behavior | 多步诊断/记忆/证据链 | 属于历史 Agent 行为证据，不替代 mixed RAG |

缺口：

- answer 层还没有固定 evalset。
- answer 层还没有固定 RAGAS / LLM-as-judge 报告格式。
- agent_behavior 层还没有统一的最小样本字段和门禁汇总报告。

---

## 4. 固定 evalset 最小字段

### 4.1 通用字段

所有层级样本至少包含：

| 字段 | 说明 |
|---|---|
| `sample_id` | 稳定唯一 ID |
| `layer` | `retrieval` / `answer` / `agent_behavior` |
| `query` | 原始用户输入，不写 rewrite 后问题 |
| `allowed_kb_ids` | 用户允许访问的 KB |
| `scope` | `scoped` / `permission_filtered` 等 |
| `expected_failure_type` | 期望失败类型或 `none` |
| `source_support` | 人工可复核依据 |
| `review_status` | `approved_human_review` 后才可进入正式 evalset |

### 4.2 Retrieval 层字段

| 字段 | 说明 |
|---|---|
| `expected_doc_ids` | 预期命中文档 |
| `expected_chunk_ids` | 可选，预期命中 chunk |
| `expected_answer_keywords` | 检索上下文应覆盖的关键词 |
| `expected_page` | PDF page/source_ref 样本使用 |
| `expected_table_id` | PDF table 样本使用 |
| `retrieval_mode` | baseline 固定 `dense_only`，对比时显式写模式 |
| `top_k` | 固定 top-k，避免 runner 默认漂移 |
| `failure_class` | `content_recall` / `pdf_table` / `expression_gap` 等 |

### 4.3 Answer 层字段

| 字段 | 说明 |
|---|---|
| `reference_answer` | 人工审过的参考答案，不要求唯一措辞 |
| `must_include_facts` | 必须出现的事实点 |
| `must_not_include_claims` | 不得编造或泄露的内容 |
| `required_citations` | 必须能追溯的 source_ref / citation |
| `context_policy` | `retrieved_context_only` / `provided_context_only` |
| `judge_policy` | `deterministic_only` / `ragas` / `llm_judge_shadow` |

### 4.4 Agent 行为层字段

| 字段 | 说明 |
|---|---|
| `expected_tools` | 应调用的工具列表 |
| `forbidden_tools` | 不应调用的工具 |
| `expected_audit_events` | 应出现的 audit event |
| `required_evidence_refs` | 必须保留的证据 ref |
| `permission_expectation` | allow / deny / filtered |
| `expected_final_state` | success / blocked / pending_approval / fallback |
| `max_side_effect_level` | none / read_only / approved_write |

---

## 5. 指标与门禁

### 5.1 Retrieval 层

硬门禁：

| 指标 | 规则 |
|---|---|
| `wrong_scope_count` | 必须为 0 |
| `citation_unresolvable_count` | 必须为 0 |
| `source_ref_resolvable_rate` | 必须为 100% |
| `permission_filtered_passed` | 权限过滤样本必须通过 |
| `expected_docs_indexed` | 必须为 true |

观察指标：

| 指标 | 用途 |
|---|---|
| `hit@k` | expected doc 是否出现在 top-k |
| `recall@k` | 多 expected docs 的召回比例 |
| `MRR` | expected doc 的首个排名质量 |
| `answer_keyword_coverage` | 检索上下文覆盖关键词比例 |
| `latency_p50/p95` | 模式对比和上线成本评估 |

### 5.2 Answer 层

硬门禁：

| 指标 | 规则 |
|---|---|
| `citation_required_but_missing` | 必须为 0 |
| `unsupported_claim_count` | 必须为 0，或明确阻塞 |
| `permission_leak_count` | 必须为 0 |
| `source_ref_unresolvable_count` | 必须为 0 |

观察指标：

| 指标 | 工具 |
|---|---|
| `faithfulness` | RAGAS / LLM judge shadow |
| `answer_relevancy` | RAGAS / LLM judge shadow |
| `answer_correctness` | LLM judge shadow + 人工抽检 |
| `completeness` | rubric / LLM judge shadow |

### 5.3 Agent 行为层

硬门禁：

| 指标 | 规则 |
|---|---|
| `forbidden_tool_call_count` | 必须为 0 |
| `missing_required_tool_count` | 必须为 0，除非样本声明可跳过 |
| `audit_missing_count` | 必须为 0 |
| `evidence_missing_count` | 必须为 0 |
| `permission_bypass_count` | 必须为 0 |
| `unsafe_side_effect_count` | 必须为 0 |

观察指标：

| 指标 | 用途 |
|---|---|
| `tool_latency_p95` | 工具性能 |
| `fallback_count` | 降级稳定性 |
| `retry_count` | 工具/模型可靠性 |
| `human_review_trigger_count` | 高风险任务触发质量 |

---

## 6. RAGAS / LLM-as-judge 使用边界

允许：

- 用在 answer 层评估回答忠实度、相关性、正确性、完整性。
- 以 shadow/report 方式输出，不直接决定 active。
- 结合人工抽检校准 judge prompt。
- 报告 judge model、prompt version、temperature、sample count。

禁止：

- 用 LLM judge 替代 `wrong_scope_count=0`。
- 用 RAGAS 替代 `source_ref` 可回查。
- 用 answer 分数掩盖检索没有命中 expected doc。
- 用 judge 的“看起来合理”覆盖权限泄露或工具越权。
- 把 LLM 自动生成的 query / answer 当作 ground truth。

---

## 7. 门禁报告格式

每次改以下内容，都必须跑对应层级报告：

- chunk / parser / artifact
- retrieval mode / hybrid / rerank
- query rewrite
- embedding model
- generation model / prompt
- tool schema / Agent planning / AIOps 工具链

报告必须同时输出 JSON 和 Markdown。

最小 JSON 结构：

```json
{
  "report_name": "string",
  "run_at": "ISO-8601",
  "change_under_test": "string",
  "layers": {
    "retrieval": {
      "status": "passed|failed|blocked|observation_only",
      "hard_gate_passed": true,
      "metrics": {},
      "failures": []
    },
    "answer": {
      "status": "not_run|passed|failed|observation_only",
      "hard_gate_passed": null,
      "metrics": {},
      "failures": []
    },
    "agent_behavior": {
      "status": "not_run|passed|failed|observation_only",
      "hard_gate_passed": null,
      "metrics": {},
      "failures": []
    }
  },
  "regressions": [],
  "default_switch_eligibility": "eligible|not_eligible_for_default_switch",
  "next_required": "string"
}
```

上线 / active 判定：

```text
allow_active = retrieval.hard_gate_passed
            AND answer.hard_gate_passed_or_not_required
            AND agent_behavior.hard_gate_passed_or_not_required
            AND regressions == []
            AND rollback_record_exists
```

---

## 8. 当前 S4-P2.1 决策

当前不继续直接跑 hybrid / rerank / Query Rewrite。

先按三层体系把 50q dense-only baseline 的 18 个失败样本分流：

| 失败类型 | 归属层 | 下一步 |
|---|---|---|
| expected doc 命中但关键词不全 | retrieval | 复核 source_support / strict keyword / top-k context |
| expected doc 未命中 | retrieval | 再做 B/C probe 或 query rewrite 候选判断 |
| expression-gap 样本失败 | retrieval -> answer 前置 | 先确认是否真表达缺口，再建 Query Rewrite shadow |
| PDF page/table 局部失败 | retrieval | 先查 artifact / table sample / chunk |
| 权限/scope/citation 失败 | retrieval / agent_behavior | 立即阻塞 active，先修门禁 |

当前 mixed 50q 事实：

```text
retrieval_layer_baseline = done
answer_layer_eval = not_started
agent_behavior_layer_eval = not_unified
default_switch_eligibility = not_eligible_for_default_switch
next_required = mixed_50q_failure_class_analysis
```

---

## 9. 给小白解释

现在不是只看“答案像不像对”。

要分三步看：

1. 先看资料有没有找对。
2. 再看答案有没有忠实使用资料。
3. 最后看 Agent 有没有按规则调用工具、留审计、守权限。

如果第一步资料都没找对，第二步答案再流畅也没有意义。

如果答案看起来对，但引用查不回去、串了部门、工具越权，也不能上线。

所以 S4-P2.1 的作用是把“考什么、怎么算通过、什么只能观察”固定下来，后面每次改 RAG 或 Agent 都用同一把尺子量。
