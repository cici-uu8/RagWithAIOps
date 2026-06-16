# Department RAG 18q Current-Scope Evalset

日期：2026-06-08

`department_rag_18q_current_scope_20260608.jsonl` 是当前小样本有效范围基线。它从 `department_rag_20q.jsonl` 派生，但排除了 RAG-12 / RAG-13。

## 为什么排除 RAG-12 / RAG-13

- RAG-12：`土壤地下水监测资料属于哪个方向`
- RAG-13：`环保监测报告怎么引用`

这两题指向环保监测 / 合规披露资料。当前产品定位是 oncall + 工艺 + AIOps，当前 3 个 indexed 文档也不包含这类资料。因此这两题被视为 `out_of_scope`，不进入当前有效 baseline。

## 基线口径

- 历史审计口径：`department_rag_20q.jsonl` 保留 20 题，不再给 RAG-12 / RAG-13 加字段或继续修改。
- 当前有效口径：`department_rag_18q_current_scope_20260608.jsonl`，18/18 passed。
- 排除口径：RAG-12 / RAG-13 是 2 道 out-of-scope 样本，不解释为系统检索失败。

## 边界

18/18 只代表当前 3 个 indexed 文档的小样本 current-scope baseline 通过，不代表长期评测充分。后续评测扩展应优先补权限隔离、scope 锁定、跨库不串、citation 准确性和 PDF 页码引用等系统能力题，而不是为了保持题数补无关内容题。
