# RAG Query Rewrite 清单 4 S4 阶段性收口

日期：2026-06-11

状态：`s4_observation_only_closeout`

对应清单：`docs/RAG_QueryRewrite_语料扩充与表达缺口评测清单4.md`

---

## 0. 一句话结论

S4 已完成 mixed Markdown+PDF RAG baseline (41/50 passed)，但 expression-gap 和 Benefit-B 证据不足，不创建正式 evalset，不启用 hybrid / rerank / query rewrite，转入 S5 Answer-layer eval。

当前配置保持：

```text
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
default_switch_eligibility = not_eligible_for_default_switch
```

---

## 1. S4 已完成工作

### 1.1 语料扩充 (S4-P1 / S4-P1.7)

✅ **18 个 indexed 文档** (12 Markdown + 6 PDF)

| Phase | 产物 | 状态 |
|---|---|---|
| S4-P1 | 10 个 Markdown runbook reviewed import/index | ✅ 完成 |
| S4-P1.7 | 6 个 PDF reviewed import/index | ✅ 完成 |
| S4-P1.5 | Mixed RAG eval readiness gate | ✅ 通过 |

**PDF artifact inventory**: `ready_for_expansion`
- 6 个 indexed PDF，artifact 完整
- Page/table sample candidates 可用
- 827 页 AWS PDF 暂缓，不纳入首版 baseline

### 1.2 Mixed 50q Baseline (S4-P1.6 / S4-P2)

✅ **正式 mixed 50q evalset 创建并跑完 dense-only baseline**

| 指标 | 值 |
|---|---:|
| Total samples | 50 |
| **Passed** | **41 (82%)** |
| Failed | 9 (18%) |
| Wrong scope count | 0 |
| Citation unresolvable count | 0 |
| All source_ref resolvable | true |

**失败分流** (S4-P2.2 after eval design repair):
- `rank_gap`: 8 样本 (expected doc 已命中，但目标 chunk/table/page 未进 top-3)
- `confirmed_expression_gap`: 1 样本 (S4M-E-010，用户表达口语化导致 dense no-hit)

**安全边界未退化**：
- ✅ 无跨部门泄露
- ✅ 所有引用可回查
- ✅ 权限过滤正确

### 1.3 Rerank C-Probe (S4-P2.3)

✅ **8 个 rank_gap 样本的 observation-only rerank probe**

| 结果 | 数量 |
|---|---:|
| rank_lift_proven | 0/8 |
| rank_observation_only | 4/8 |
| no_rank_lift | 4/8 |

**结论**: Rerank 对当前 8 个 rank_gap 样本无正式价值，不升级为正式 C evalset。

### 1.4 Expression-Gap 扩充 (S4-P3 / S4-P3.3)

✅ **Observation-only 候选扩充 + dual probe**

**Phase 1: 12 个 pending 候选 dense probe**
- 10/12 dense-only 已命中 expected doc → 不是真正 expression-gap
- 2/12 no-hit → 进入人工 review

**Phase 2: 人工 review**
- S4P3-EG-010: ✅ 确认为 expression-gap
- S4P3-EG-006: ❌ 转入 Benefit-B (sparse hit)

**Phase 3: Dual probe (8 rank_gap + 1 expression_gap)**
- Expression-gap rewrite: 0/8 proven (手工改写无法修复 rank_gap)
- Benefit-B sparse/hybrid: 1/9 proven (仅 S4M-E-010 被 sparse 修复)

**最终统计**:
- Confirmed expression-gap: 2 (S4M-E-010 + S4P3-EG-010)
- Observation Benefit-B: 2 (S4P3-EG-006 + S4M-E-010)
- 两者均 < 10，不满足正式 evalset 创建条件

---

## 2. S4 不创建的 Evalset

根据三层评测体系总规范 (S4-P2.1) 和实际 probe 结果，以下 evalset **不应创建**：

### 2.1 Expression-Gap 10q

❌ **不创建** `evals/knowledge_base/evalsets/department_rag_expression_gap_candidate_10q.jsonl`

**原因**:
- 当前 confirmed count = 2，远不足 10
- 8 个 rank_gap 样本手工改写后仍无改善，不是表达问题
- 12 个 pending 候选中 10 个 dense-only 已命中，不是 expression-gap

**证据**:
- S4-P3.3 dual probe phase 1: rewrite_lift_proven = 0/8
- 手工改写 map 见 `checklist4_s4_p33_rank_gap_dual_probe.py:HAND_REWRITE_MAP`
- 即使改写为标准技术术语，仍无法将 expected doc 提升到 top-3

### 2.2 Benefit-B Sparse/Hybrid 10q

❌ **不创建** `evals/knowledge_base/evalsets/department_rag_benefit_b_sparse_hybrid_10q.jsonl`

**原因**:
- 当前 confirmed count = 2，远不足 10
- 9 个 failed 样本中只有 1 个被 sparse 修复 (S4M-E-010)
- 该样本本身是 expression-gap，不是纯粹的 sparse lexical 收益

**证据**:
- S4-P3.3 dual probe phase 2: sparse_lift_proven = 1/9
- 唯一 proven 样本 (S4M-E-010) 同时也是 confirmed expression-gap
- 其余 8 个 failed 样本在 dense/sparse/hybrid 下均为 rank=0 (no-hit)

### 2.3 Benefit-C Rerank 10q

❌ **不创建** (S4-P2.3 已证明无正式价值)

**原因**:
- 8 个 rank_gap 样本 rerank probe: rank_lift_proven = 0/8
- Rerank 无法将 expected doc 从 rank 4+ 提升到 rank 1-3
- 不满足 `min_effective_samples = 6` 的阈值

**证据**:
- `evals/knowledge_base/reports/checklist4_s4_p23_rank_gap_c_probe_20260610.json`
- `eligible_for_formal_evalset = false`

---

## 3. S4 不启用的增强

根据当前 observation-only 证据，以下配置**不应启用**：

### 3.1 Query Rewrite

```python
# app/config.py - 保持不变
rag_query_rewrite_mode: str = Field(default="off")
```

**原因**:
- Expression-gap confirmed count = 2，不足 10
- 无正式 expression-gap evalset
- S4-P3.3 dual probe 未证明 rewrite 能修复 rank_gap

**允许的 shadow 范围**:
- ❌ 不允许在真实 RAG query 上启用 rewrite
- ✅ 允许在专门 evalset 上做 observation-only rewrite candidate 生成
- ✅ 允许在评测报告中记录 rewrite candidate，但不替换原始 query

### 3.2 Hybrid / Sparse

```python
# app/config.py - 保持不变
rag_default_retrieval_mode: str = Field(default="dense_only")
```

**原因**:
- Benefit-B confirmed count = 2，不足 10
- 无正式 Benefit-B evalset
- S4-P3.3 dual probe 仅 1/9 proven，且该样本是 expression-gap

**允许的 shadow 范围**:
- ❌ 不允许切换默认检索模式
- ❌ 不允许在真实 RAG session 上默认启用 hybrid
- ✅ 允许在评测脚本中临时对比 dense/sparse/hybrid
- ✅ 允许在 shadow report 中记录模式对比结果

### 3.3 Rerank

```python
# app/config.py - 保持不变
rerank_enabled: bool = Field(default=False)
```

**原因**:
- S4-P2.3 C-probe: rank_lift_proven = 0/8
- 不满足 `min_effective_samples = 6` 阈值
- 无正式 Benefit-C evalset

**允许的 shadow 范围**:
- ❌ 不允许启用默认 rerank
- ❌ 不允许切换 `rag_default_retrieval_mode=hybrid_rerank`
- ✅ 允许在评测脚本中临时启用 rerank 做对比
- ✅ Checklist 3 已证明 rerank shadow readiness (synthetic active/fallback)

### 3.4 Default Switch Eligibility

```text
default_switch_eligibility = not_eligible_for_default_switch
```

**判定依据** (三层评测体系总规范 §7):
- ❌ retrieval 层 hard gate passed: 41/50 passed，但无收益证明
- ❌ expression-gap / Benefit-B / Benefit-C 证据不足
- ❌ 无 retrieval-default rollback record
- ✅ 安全边界未退化

---

## 4. S4 Observation-Only 结论

### 4.1 当前 Dense-Only Baseline 是合理的

**Mixed 50q dense-only baseline**: 41/50 (82%) passed

**失败分流显示**:
- 8 个 rank_gap: 手工改写无效 (0/8 rewrite lift)，rerank 无效 (0/8 rank lift)
- 1 个 expression-gap: 可用 sparse 修复，但不足以证明 sparse 普遍收益

**解释**:
- 当前 dense-only 已经覆盖了大部分真实场景
- 剩余 9 个失败不是简单的检索/排序/表达问题
- 可能是 chunk/context/parser/answer 层问题，需要更深层次分析

### 4.2 Expression-Gap 不是主要失败模式

**证据链**:
1. Mixed 50q 中只有 1 个 confirmed expression-gap (S4M-E-010)
2. 12 个 pending 候选中 10 个 dense-only 已命中
3. 8 个 rank_gap 样本手工改写后仍无改善
4. S4-P3.3 dual probe: rewrite_lift_proven = 0/8

**结论**:
- 用户表达问题不是当前 corpus 的主要失败原因
- Query Rewrite 不能修复 rank_gap 问题
- 当前业务场景下，用户 query 质量可接受

### 4.3 Sparse/Hybrid 收益有限

**证据链**:
1. S4-P3.3 dual probe phase 2: sparse_lift_proven = 1/9
2. 唯一 proven 样本 (S4M-E-010) 是 expression-gap，不是纯 lexical 收益
3. 其余 8 个 failed 样本在 dense/sparse/hybrid 下均 no-hit

**结论**:
- Sparse lexical matching 不能普遍修复当前失败样本
- Hybrid fusion 也无明显收益 (hybrid_lift_proven = 0/9)
- 失败原因可能不在检索模式，而在 corpus/chunk/context/answer 层

### 4.4 Rerank 无正式价值

**证据链**:
1. S4-P2.3 C-probe: rank_lift_proven = 0/8
2. 4/8 样本 rerank 后 expected doc 仍未进 top-3
3. 4/8 样本 rerank 后 expected doc 进了 top-3，但与 hybrid 结果相同 (no lift)

**结论**:
- Rerank 不能将 expected doc 从 rank 4+ 提升到 rank 1-3
- 当前 LexicalRerankScorer 对 8 个 rank_gap 样本无收益
- 不排除其他 rerank 模型 (semantic / cross-encoder) 可能有效，但当前无证据

---

## 5. S4 → S5 转向建议

根据三层评测体系总规范，当前应从 **retrieval 层进入 answer 层**。

### 5.1 为什么不继续优化 Retrieval 层

**Retrieval 层已经"足够好"**:
- 41/50 (82%) passed
- 安全边界未退化
- Expression-gap / Benefit-B / Benefit-C 证据不足

**继续优化 Retrieval 层的边际收益低**:
- Query Rewrite 不能修复 rank_gap (0/8)
- Sparse/Hybrid 收益有限 (1/9)
- Rerank 无正式价值 (0/8)

**风险**:
- 继续调 retrieval 可能引入新噪声
- 可能掩盖 answer 层和 agent_behavior 层的真实问题

### 5.2 为什么转向 Answer 层

**Retrieval 层 passed ≠ Answer 层 passed**:
- Mixed 50q baseline 只检查 expected doc 是否命中
- 未检查 LLM 基于检索上下文的回答质量
- 未检查是否忠实、相关、完整、无编造

**可能的 Answer 层问题**:
- 检索上下文有事实，但 LLM 回答遗漏
- 检索上下文有事实，但 LLM 编造了不存在的内容
- Citation 格式错误或不可回查
- 回答不相关或过度泛化

### 5.3 S5 Answer-Layer Eval 设计方向

**目标**: 从 mixed 50q 里挑 20-30 题做 answer eval pilot

**最小字段扩展** (基于 S4-P2.1 三层总规范):
- `reference_answer`: 人工审过的参考答案
- `must_include_facts`: 必须出现的事实点
- `must_not_include_claims`: 不得编造或泄露的内容
- `required_citations`: 必须能追溯的 source_ref / citation

**硬门禁**:
- `citation_required_but_missing = 0`
- `unsupported_claim_count = 0`
- `permission_leak_count = 0`
- `source_ref_unresolvable_count = 0`

**观察指标** (允许 LLM-as-judge，但仅作补充):
- `faithfulness`: RAGAS / LLM judge shadow
- `answer_relevancy`: RAGAS / LLM judge shadow
- `answer_correctness`: LLM judge shadow + 人工抽检

**判定规则**:
- 如果 answer eval 失败原因是"上下文缺事实" → 回到 chunk/top_k/parser
- 如果上下文有事实但回答漏答/编造 → 调 prompt / answer policy
- 如果 citation 错 → 修 citation assembly

### 5.4 Chunk/Parser 优化推迟

**不在 S5 第一优先级**:
- 当前 PDF artifact inventory 为 `ready_for_expansion`
- 6 个 indexed PDF 的 artifact 完整，page/table sample candidates 可用
- 但 S4 失败样本中没有明确的 artifact 缺失证据

**触发条件**:
- 如果 S5 answer eval 发现"检索上下文缺关键事实"
- 且该事实在 PDF 的某个 table/page 中存在
- 但当前 chunk 未覆盖
- → 再优化 chunk/table/page splitting

### 5.5 Corpus 扩充推迟

**不在 S5 第一优先级**:
- 继续扩是对的，但不是当前第一优先级
- 否则会把"答案层问题"和"新语料噪声"混在一起

**触发条件**:
- S5 answer eval 证明当前 18-doc corpus 的回答质量稳定
- 且 answer 层 hard gate passed
- → 再扩充 corpus，重跑 retrieval + answer baseline

---

## 6. S4 产物清单

### 6.1 文档

| 文档 | 状态 |
|---|---|
| `docs/RAG_QueryRewrite_语料扩充与表达缺口评测清单4.md` | ✅ S4 主文档 |
| `docs/RAG_QueryRewrite_清单4_Mixed_RAG评测体系设计.md` | ✅ S4-P1.5 readiness 设计 |
| `docs/RAG_QueryRewrite_清单4_S4-P2.1_三层评测体系总规范.md` | ✅ 三层评测规范 |
| `docs/RAG_QueryRewrite_清单4_S4-P2.2_Mixed_50q失败样本分流分析.md` | ✅ 失败分流 |
| `docs/RAG_QueryRewrite_清单4_S4-P3_Expression_Gap候选扩充矩阵.md` | ✅ Expression-gap 扩充 |
| `docs/RAG_QueryRewrite_清单4_S4-P3_Benefit_B_Hybrid候选扩充矩阵.md` | ✅ Benefit-B 扩充 |
| `docs/RAG_QueryRewrite_清单4_S4_Closeout.md` | ✅ 本文档 |

### 6.2 Evalset

| Evalset | 样本数 | 状态 |
|---|---:|---|
| `evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl` | 50 | ✅ 正式 |
| `evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_10q_pilot.jsonl` | 10 | ✅ Pilot (历史) |

**不创建**:
- ❌ `department_rag_expression_gap_candidate_10q.jsonl`
- ❌ `department_rag_benefit_b_sparse_hybrid_10q.jsonl`

### 6.3 报告

| 报告 | 类型 | 结论 |
|---|---|---|
| `checklist4_mixed_50q_readiness_20260610.json` | Readiness gate | ✅ ready_for_mixed_baseline |
| `department_rag_mixed_markdown_pdf_50q_dense_baseline_20260610.json` | Dense baseline | 41/50 passed |
| `department_rag_mixed_markdown_pdf_50q_dense_baseline_after_s4_p23_repair_20260610.json` | Dense baseline (修复后) | 41/50 passed |
| `checklist4_s4_p23_rank_gap_c_probe_20260610.json` | Rerank C-probe | 0/8 rank_lift_proven |
| `checklist4_s4_p33_rank_gap_dual_probe_20260611.json` | Dual probe | 0/8 rewrite, 1/9 benefit-b |

### 6.4 脚本

| 脚本 | 用途 |
|---|---|
| `evals/knowledge_base/checklist4_mixed_rag_eval_readiness_report.py` | Readiness gate |
| `evals/knowledge_base/checklist4_s4_p23_rank_gap_c_probe.py` | Rerank C-probe |
| `evals/knowledge_base/checklist4_s4_p33_rank_gap_dual_probe.py` | Dual probe (rewrite + sparse/hybrid) |

---

## 7. 给小白解释

**S4 做了什么**:
- 扩了语料：从 3 个文档扩到 18 个 (12 Markdown + 6 PDF)
- 建了考卷：mixed 50q，考检索能不能找对文档
- 跑了基线：dense-only 模式，41 题对、9 题错
- 查了错题：8 个是"找到了但排序不够靠前"，1 个是"用户说话太口语"

**S4 试了什么**:
- 试了改写：8 个排序靠后的题，改成标准问法，还是没用
- 试了 rerank：8 个排序靠后的题，用 rerank 排序，还是没用
- 试了 sparse/hybrid：9 个错题，用关键词匹配 + 混合，只修复了 1 题 (就是那个口语化的)

**S4 结论**:
- 当前检索已经"足够好"了 (82% 正确率)
- 剩下的错题不是"换个算法"能修的
- 可能是答案生成有问题，或者切分文档的方式有问题

**接下来做什么**:
- 不是继续调检索
- 而是看"找对了文档，能不能生成好答案"
- 这叫 Answer-layer eval，是下一阶段 (S5) 的事

---

## 8. 状态锁定

```text
s4_status = observation_only_closeout
s4_corpus_expanded = yes
s4_mixed_50q_baseline = done
s4_expression_gap_confirmed = 2
s4_benefit_b_confirmed = 2
s4_benefit_c_rank_lift_proven = 0
s4_expression_gap_eligible = no
s4_benefit_b_eligible = no
s4_benefit_c_eligible = no
s4_creates_expression_gap_jsonl = no
s4_creates_benefit_b_jsonl = no
s4_enables_query_rewrite = no
s4_enables_hybrid = no
s4_enables_rerank = no
s4_default_switch_eligibility = not_eligible_for_default_switch
s5_next = answer_layer_eval_pilot
```

---

## 9. Handoff 到 S5

**S5 输入**:
- Mixed 50q evalset (50 samples, retrieval 层已验证)
- Dense-only baseline report (41/50 passed)
- 18-doc indexed corpus (12 MD + 6 PDF)
- 三层评测体系总规范

**S5 目标**:
- 从 mixed 50q 挑 20-30 题做 answer eval pilot
- 扩展字段：reference_answer / must_include_facts / must_not_include_claims / required_citations
- 跑 answer baseline：调用 LLM 生成答案，检查忠实度/相关性/正确性/完整性
- 硬门禁：citation_required_but_missing=0 / unsupported_claim_count=0 / permission_leak_count=0

**S5 判定规则**:
- 如果上下文缺事实 → 回到 chunk/top_k/parser
- 如果上下文有事实但回答漏答/编造 → 调 prompt / answer policy
- 如果 citation 错 → 修 citation assembly

**S5 不做**:
- ❌ 不调 retrieval mode
- ❌ 不调 query rewrite
- ❌ 不调 rerank
- ❌ 不扩 corpus (除非 answer eval 证明当前 18-doc 稳定)
