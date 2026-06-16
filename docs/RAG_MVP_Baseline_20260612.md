# RAG System MVP Baseline

日期：2026-06-12

状态：`mvp_baseline_accepted_for_beta_readiness`

## 1. 结论

当前 RAG 系统接受为小范围生产 beta / MVP 基线。

这不是正式 GA 质量承诺，也不是 Answer 层 fully solved。它表示当前系统已经具备受控 beta 的最小能力：语料可用、Retrieval 达到健康线、Answer 安全边界干净、默认配置保守、反馈闭环已定义。

```text
mvp_decision = accept_current_baseline_for_beta
retrieval_baseline = 45/54 (83.3%)
answer_baseline = 18/30 (60.0%)
beta_smoke = 7/7 passed
default_retrieval_mode = dense_only
query_rewrite_mode = off
rerank_enabled = false
answer_50q = not_started
agent_behavior = not_started
```

## 2. Corpus Baseline

来源：

```text
evals/knowledge_base/reports/checklist6_c6_p3_mixed_54q_readiness_20260612.json
```

当前 indexed corpus：

| metric | value |
|---|---:|
| indexed documents | `30` |
| indexed KB count | `2` |
| indexed Markdown | `18` |
| indexed PDF | `12` |
| source_ref resolvable | `true` |
| artifact missing count | `0` |

KB：

```text
process_digital_dept
craft_dept
```

覆盖范围：

- oncall / SRE runbook
- AIOps lab / alert handling
- Redis high memory runbook
- MySQL slow query runbook
- database operation capability docs
- craft PDF and mixed public SRE PDFs

## 3. Retrieval Baseline

来源：

```text
evalset = evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl
report = evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_54q_after_c6_p2_dense_20260612.json
```

结果：

| metric | value |
|---|---:|
| total | `54` |
| passed | `45` |
| failed | `9` |
| pass rate | `83.3%` |
| not_ready | `0` |
| wrong_scope_count | `0` |
| citation_unresolvable_count | `0` |
| all_source_ref_resolvable | `true` |

解释：

- Retrieval 达到当前健康线 `>=80%`。
- 新增 Redis/MySQL 4q retrieval 样本 `4/4` 通过。
- 9 个失败全部来自旧 Mixed 50q 残留，不是 C6 新文档退化。
- 残余失败分流见 `docs/RAG_Retrieval_C6_Mixed_54q_Residual_Failure_Triage.md`。

当前不能由 9 个残余失败推出默认策略变更：

```text
true_rerank_probe_rank_lift = 0/8
sparse_or_hybrid_lift = 1/9
change_default_retrieval_mode = no
enable_rerank_default = no
enable_query_rewrite_default = no
```

## 4. Answer Baseline

来源：

```text
evalset = evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6_triage_fix.jsonl
report = evals/knowledge_base/reports/department_rag_answer_30q_after_c6_triage_fix_20260612.json
triage = docs/RAG_Answer_Layer_C6_Answer_30q_Failure_Triage.md
```

结果：

| metric | value |
|---|---:|
| total | `30` |
| passed | `18` |
| failed | `12` |
| pass rate | `60.0%` |
| not_ready | `0` |
| answer_missing_facts | `7` |
| context_missing_facts | `5` |
| hard_gate_passed | `false` |

硬安全边界：

| gate | value |
|---|---:|
| citation_required_but_missing | `0` |
| unsupported_claim_count | `0` |
| permission_leak_count | `0` |
| source_ref_unresolvable_count | `0` |
| retrieval_layer_failed_count | `0` |

解释：

- Answer 覆盖率低于早先建议的 70%，不作为 Answer 层完成证明。
- 但硬安全边界干净，可接受为 beta 阶段的有限能力基线。
- 3q sample-local `top_k=5` Answer shadow 只有 `1/3` 通过，说明 context coverage 不是 Answer pass 的充分条件。
- 当前不继续追 Answer 70%，除非真实用户反馈集中触发。

## 5. Beta Smoke Baseline

来源：

```text
runner = evals/knowledge_base/beta_readiness_smoke.py
report = evals/knowledge_base/reports/beta_readiness_smoke_20260612.json
doc = docs/RAG_Beta_Readiness_生产试运行闭环.md
```

结果：

| metric | value |
|---|---:|
| status | `passed` |
| check_count | `7` |
| passed_count | `7` |
| failed_count | `0` |
| external_llm_called | `false` |
| external_vector_db_called | `false` |

覆盖：

- login
- controlled RAG Q&A
- source_ref lookup
- permission filtering
- config defaults
- audit logging
- feedback schema

## 6. MVP Capability Statement

可以对 beta 用户说明：

- 当前知识库有 30 个 indexed documents，覆盖 Markdown 和 PDF。
- 系统能进行多文档 retrieval，并返回可回查 source_ref。
- 当前 retrieval 基线是 Mixed 54q `45/54`。
- 权限、scope、citation/source_ref 边界在当前 baseline 中保持干净。
- Answer 可以给出初步解释，但可能遗漏细节，需要用户反馈真实 case。

不能对外承诺：

- 不承诺 Answer 50q 已通过。
- 不承诺 90%+ 答案完整率。
- 不承诺复杂 agent behavior 已验收。
- 不承诺 hybrid、rerank、query rewrite 已启用。
- 不承诺无人工复核即可用于高风险生产操作。

## 7. Known Limitations

| area | known limitation | current handling |
|---|---|---|
| Answer completeness | Answer 30q only `18/30` | beta 中收集真实 `answer_incomplete` 反馈 |
| PDF deep retrieval | Scoutflo PDF chunk/table/page ranking 残留失败 | 后续可做 observation-only chunk/table probe |
| Expression gap | formal-countable expression-gap 样本不足 | query rewrite 保持 off |
| Rerank | true rerank probe `0/8` lift | rerank 保持 disabled |
| Hybrid | only `1/9` proven lift | default 仍为 dense_only |

## 8. Decision Boundary

MVP beta 可以继续：

```text
retrieval >= 80%
source_ref/scope/citation clean
permission leak = 0
beta smoke passed
feedback loop exists
```

MVP beta 不能升级为正式 GA，除非后续补齐：

```text
real user feedback period completed
no clustered source_ref/permission/scope incidents
answer_incomplete cluster triaged or accepted
performance baseline recorded
rollback runbook verified for target deployment
owner approval for production scope
```

## 9. Next Action

进入 Beta Readiness / Production Readiness Checklist：

```text
docs/RAG_Production_Readiness_Checklist.md
```

优先顺序：

1. 锁定默认配置和 dependency lock 状态。
2. 运行 beta readiness smoke。
3. 记录性能 baseline。
4. 确认 rollback / monitoring / feedback loop。
5. 小范围内部 beta，3-5 个用户，1 周。
