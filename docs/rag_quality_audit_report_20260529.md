# RAG 质量审计报告

日期：2026-05-29

范围：仅读取现有 RAG 评估报告，不重跑 eval，不新增 API 消耗。

## 执行摘要

当前 RAG 在现有 corpus 上已经足够稳定，不需要再来一次大范围检索重写。

- 检索质量在固定评测集上表现稳定。
- 引用对齐保持稳定。
- `doc_level` 能明显减少上下文长度，同时不破坏现有质量。
- 真正还在的 caveat 只有两个：
  - `full_doc` 在当前长文档 corpus 上超出 qwen-max 的 32K 窗口。
  - `parent_chunk` 的供给太少，fallback 仍然偏高。

建议的下一小步：优先改 `ChunkPolicyService._build_section_parents()` 的 parent 覆盖率，并保持 `full_doc` 只作为显式 opt-in。

## 证据快照

| 方向 | 证据 | 说明 | Caveat | 用户价值 | 风险 | 下一小步 |
|---|---|---|---|---|---|---|
| 检索准确率 | `evals/rag_retrieval/reports/p4_5_eval_20260520_232941.json`、`evals/rag_retrieval/reports/p5_eval_20260520_233007.json`、`evals/rag_retrieval/reports/retrieval_eval_20260520_232933.json` | 固定评测集上 `doc_recall@1/3=1.0`、`hit@1/3=1.0`、`citation_correctness@3=1.0`、`mrr@3=1.0`，`doc_level` 也通过。 | 样本数仍然偏小，corpus 也比较窄。 | 命中稳定，引用稳定。 | 低。 | 先别动主检索链路。 |
| 引用对齐 | `evals/rag_retrieval/reports/p4_5_eval_20260520_232941.json`、`evals/rag_retrieval/reports/p5_llm_eval_20260520_233200.json` | 引用不变性成立，LLM 侧没有出现 hallucinated samples。 | 跨跑次仍会有 LLM 噪声，别过度解读小幅波动。 | 更可信的引用答案。 | 低。 | 保持当前 citation contract。 |
| 上下文预算 | `evals/rag_retrieval/reports/p5_long_doc_eval_20260520_233026.json`、`evals/rag_retrieval/reports/p5_joint_eval_20260520_233105.json` | `DOC_LEVEL × full_doc` 的平均 token 约 46.3K，p95 约 57.9K，明显超过当前 32K 下游窗口。 | `full_doc` 结构上可用，但在这批长文档上不可直接消费。 | 避免把用户带进一个不可用的大上下文。 | 中。 | 保持 `full_doc` 显式开启。 |
| Parent chunk 覆盖率 | `evals/rag_retrieval/reports/p5_joint_eval_20260520_233105.json`、`ChunkPolicyService._build_section_parents()` | `parent_chunk` 的 fallback rate 仍是 0.833；当前代码只会把同 heading_path 下连续 >=2 个文本子块聚成 parent。 | parent 供给稀疏，parent 层收益被压住了。 | 更高层级、更好用的上下文。 | 中。 | 小范围提升 parent 生成覆盖率。 |
| Doc-level 粒度 | `evals/rag_retrieval/reports/p5_eval_20260520_233007.json`、`evals/rag_retrieval/reports/p5_llm_eval_20260520_233200.json` | `doc_level` 在当前 corpus 上能明显降 token，而且质量不掉。 | 仍然受 corpus 窄度限制。 | 更省 prompt、更稳。 | 低。 | 把 `doc_level` 作为常规路径。 |

## 代码边界说明

- `RetrievalQuery.context_granularity` 默认是 `CHUNK`，所以 `full_doc` 本来就是显式 opt-in。
- `RetrievalService._assemble_full_doc_context()` 只会把 `KnowledgeMetadataStore` 里的非 parent 子块拼接起来，不会去读原始文件。
- 如果要提升 `parent_chunk`，最直接的边界就是 `ChunkPolicyService._build_section_parents()`。

## 建议

不要扩大范围。

如果继续做 RAG，下一步最值得做的是一个小而明确的 parent-chunk 切口：

1. 小范围审查 `ChunkPolicyService._build_section_parents()` 的 parent 生成规则。
2. 用现有 long-doc eval 看 `parent_chunk` fallback 是否下降。
3. 继续保持 `full_doc` 显式 opt-in，必要时再加可消费性 guard。

这比再来一次 broad retrieval rewrite 更稳。

