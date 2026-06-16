# RAG Corpus 清单6 C6-P2 Redis/MySQL Retrieval Pilot

日期：2026-06-12

状态：`c6_p2_redis_mysql_retrieval_pilot_passed`

后续更新：C6-P3 已在单独决策下创建派生 Mixed 54q baseline，见 `docs/RAG_Corpus_清单6_C6-P3_Mixed_54q_retrieval_baseline.md`。本文件保留 C6-P2 当时的独立 pilot 结论。

## 1. 目标

C6-P1b 已把 corpus 推进到 30 indexed docs，并新增 Redis high memory / MySQL slow query 两个 owner-approved 真实业务 Markdown。C6-P2 不修改正式 Mixed 50q，而是用独立 4q pilot 验证这两个新增文档是否能被 dense-only retrieval 稳定召回。

## 2. Evalset

新增 evalset：

```text
evals/knowledge_base/evalsets/department_rag_c6_p2_redis_mysql_retrieval_4q.jsonl
```

样本范围：

| sample_id | query focus | expected_doc_id |
|---|---|---|
| C6P2-REDIS-001 | Redis high memory 排查 | `doc_4609992d-0697-513e-945d-7a3b0dae62f4` |
| C6P2-REDIS-002 | Redis evicted keys 指标 | `doc_4609992d-0697-513e-945d-7a3b0dae62f4` |
| C6P2-MYSQL-001 | MySQL 慢查询执行计划 | `doc_91ddd5b9-93bd-5c30-8a57-c7eb86a7942c` |
| C6P2-MYSQL-002 | DBSlowQuery 连接池等待 | `doc_91ddd5b9-93bd-5c30-8a57-c7eb86a7942c` |

## 3. 运行结果

命令：

```text
uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_c6_p2_redis_mysql_retrieval_4q.jsonl \
  --no-write \
  --report evals/knowledge_base/reports/department_rag_c6_p2_redis_mysql_retrieval_4q_dense_20260612.json
```

结果：

```text
total = 4
passed = 4
failed = 0
not_ready = 0
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
```

四个样本的 top-3 actual docs 均为对应 Redis/MySQL 新文档，说明新增 runbook 已被当前 dense-only retrieval 正常召回。

## 4. 关键词修正记录

首轮 pilot 出现 2/4 失败，但失败原因不是 expected doc miss。四个样本均命中新文档 top-3；失败来自 `expected_answer_keywords` 覆盖了同一文档里另一个 chunk 的细节字段。

修正方式：

- `C6P2-REDIS-002` 从跨 chunk 的 `keyspace_hits/keyspace_misses/maxmemory_policy` 收窄为 top-3 context 已覆盖的 `evicted_keys/used_memory/maxmemory/mem_fragmentation_ratio`。
- `C6P2-MYSQL-002` 从排查步骤里的 `active / idle / wait` 收窄为 top-3 context 已覆盖的连接池耗尽特征和处理动作。

这不是放宽 expected doc；expected doc 仍固定为 C6-P1b 新增 Redis/MySQL runbook。

## 5. 边界

- 不修改正式 Mixed 50q evalset。
- C6-P2 当时不把 4q pilot 合并为新的正式 54q baseline；后续 C6-P3 以单独阶段创建派生 54q，且不覆盖历史 50q。
- 不运行 Answer baseline。
- 不创建 Answer 50q。
- 不运行 OpenJudge/RAGAS gate。
- 不进入 agent_behavior 层。
- 不修改 `rag_default_retrieval_mode=dense_only`、`rag_query_rewrite_mode=off` 或 `rerank_enabled=false`。

## 6. 结论

C6-P2 证明 Redis/MySQL 新增 owner runbook 在当前 dense-only retrieval 下可召回，且 source_ref/scope 边界干净。它只补齐新增语料的 retrieval pilot 覆盖，不代表 Answer 层或 Agent 行为层通过。

后续 C6-P3 已把本 4q 作为单独 source-support-reviewed 追加项派生出 Mixed 54q baseline；这不改变 C6-P2 本身的 shadow/pilot 边界，也不代表可以直接重启 Answer 50q。
