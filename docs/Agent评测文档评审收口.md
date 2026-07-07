---
feature_ids:
  - agent-eval-doc-review-closeout
topics:
  - agent-evaluation
  - documentation-review
  - governance
doc_kind: review-closeout
created: 2026-07-07
status: documentation_only
---

# Agent 评测文档评审收口

## 1. 评审范围

本次评审覆盖三个文档资产：

- `docs/Agent评测体系设计_基于054文章.md`
- `docs/Agent评测资产索引.md`
- `docs/Agent评测RCA标签体系.md`

评审目标不是继续扩写方法论，而是确认三件事：

1. 资产分级没有把 `shadow`、`observation` 写成可直接发布的 `gate`。
2. RCA 标签没有把 corpus gap、权限边界、SafeSQL 阻断等问题错归到 LLM。
3. 状态文件没有把“设计 / 索引完成”写成“评测体系实现完成”。

本轮仍为 documentation-only：不改运行时代码，不跑新 eval，不训练模型，不接生产路径。

## 2. 资产分级评审

结论：未发现需要阻断提交的分级误判。

需要保留的解释口径如下：

| 资产 | 当前分级 | 评审判断 |
|---|---|---|
| RAG Mixed 54q | `gate` / `baseline` | 可作为 retrieval、source_ref、scope 的门禁和默认策略提升前置证据；不能当作完整 Answer/GA 质量门禁。 |
| Answer 30q | `baseline` / `limitation_record` | 正确。`18/30` 是当前阶段基线和限制记录，不是成熟 Answer 证明。 |
| Boundary 12Q | `shadow` / `edge_pressure_set` | 正确。它是边界压力集，不直接授权默认 retrieval 改动。 |
| Beta feedback | `observation` / `real_feedback_set` | 正确。真实反馈要按聚类阈值触发 triage，不能单条当 gate。 |
| top_k / rerank matrix | `shadow` / `compare_gate` | 正确，但 `compare_gate` 只表示候选 promotion gate，不是运行时 gate。 |
| BGE-M3 shadow | `shadow` / `model_comparison_evidence` | 正确。结果 `38/54`、decision `keep-shadow`，不能切生产 embedding。 |
| Enterprise trace eval | `shadow` / `deterministic_gate_candidate` | 正确。可升级为门禁，但当前要先明确 evalset 和阻断阈值。 |
| Router 52 candidates | `shadow` / `candidate_set` | 正确。它不是 reviewed training set，也没有生成 `router_classifier_samples.jsonl`。 |

## 3. RCA 主责评审

结论：未发现“所有问题都归到 LLM”的错误归因。

重点口径如下：

- `retrieval_no_hit` 先判断语料是否存在；语料不存在时主责是 corpus，不是 LLM。
- `answer_incomplete` 只有在 retrieved context 已包含事实但回答漏掉时，才归 answer layer。
- `source_ref_unresolvable`、`permission_scope_issue`、`human_review_bypassed` 是 P0 确定性问题，不能交给 LLM Judge。
- `sql_blocked` 本身不代表 bug；正确阻断应作为 negative control 保留，不能为了通过样本放宽 SafeSQL。
- `intent_misroute` 的高风险 false negative 优先级高于普通问答误路由，router 微调仍只能后置离线。

## 4. 状态文件评审

结论：状态文件没有把设计完成写成实现完成。

当前状态文件使用的是以下边界：

- `documentation-only`
- `不改变 runtime code / defaults / router production routing / model training`
- `micro-finetuning and model comparison are indexed as assets only`
- `Router 52 candidate JSONL remains a shadow candidate set`

需要同步调整的是：评审已经完成，下一步从“review docs”变为“提交当前 worktree，然后选择最小实现方向”。

## 5. 收口结论

本批文档可以作为独立文档资产提交。

提交前检查范围限定为：

```text
git diff --check
frontmatter / 关键字段检查
git status --short
```

不需要跑 pytest，因为本轮没有 runtime code、配置、API、测试逻辑或生产默认值改动。

## 6. 提交后的推荐下一步

优先顺序：

1. `docs/Agent评测门禁Scorecard.md`：把资产索引和 RCA 标签变成一页可执行门禁表。
2. `AuditEvidenceVerifier`：检查 P0 allow / deny / block 是否有足够 audit 字段。
3. `ToolTrajectoryVerifier`：检查 required tool / forbidden tool。

当前更推荐先做 `Agent评测门禁Scorecard.md`，因为它仍是 documentation-only，能把“哪些证据阻断什么”先固化，再决定是否进入 verifier 代码实现。
