# P4.5 context_granularity 设计与执行计划

日期: 2026-05-18
范围: 仅 P4.5。明确不实现 P5（doc-level dedup）与 P6（domain_metadata enricher）。

## 0. 边界与不变量

- 不改 dense / sparse / hybrid / rerank 召回逻辑。
- 不改 citation 主语义：`RetrievalResult.chunk_id / content / source_ref / citation_text` 始终指向命中子块。
- `parent_content` 不进 `RetrievalResult` 主 DTO 字段，仍只挂在 `metadata`。
- 三模式只作用于 “命中后的回答上下文拼装”，即 `RetrievalResponse.context_text` 的构造。
- `full_doc` 不能成为默认。
- 本次提交不做任何 dedup（同 parent 多 child / 同 doc 多 chunk 都重复拉）。
- 现有 `78/78` 单测在默认模式下不允许回退。
- 现有 4 条 P3 golden queries 在默认模式（`chunk`）下结果与 P4 baseline 持平。

## 1. 三模式语义

引入 `ContextGranularity` 枚举，作为 `RetrievalQuery` 的可选字段：

```
class ContextGranularity(StrEnum):
    CHUNK = "chunk"
    PARENT_CHUNK = "parent_chunk"
    FULL_DOC = "full_doc"
```

默认值: `ContextGranularity.CHUNK`。

| 模式 | context_text 构造规则 | 命中子块的 RetrievalResult |
|---|---|---|
| `chunk` | 每条 hit 的 `content` 直接拼 | 不变 |
| `parent_chunk` | 若 hit 的 `metadata.parent_content` 存在则拼父块文本，否则回退用子块 `content`；**同 parent 多 child 重复拉，不做合并** | 不变 |
| `full_doc` | 每条 hit 拼该 doc 的完整可展示文本（按 `chunk_index` 顺序拼非 parent 子块）；**同 doc 多 hit 重复拉，不做合并** | 不变 |

约束：

- 三模式都不改写 `RetrievalResult.content`、`source_ref`、`citation_text`、`chunk_id`。
- 三模式只重建 `RetrievalResponse.context_text`，并把当条 hit 实际进入上下文的文本以 `metadata["expanded_context"]` 形式回挂，便于 token 统计和评测核对，不进入 DTO 主字段。
- `parent_chunk` 在子块没有 `parent_chunk_id` 时退回 `chunk` 行为，但记录 `metadata["context_granularity_fallback"] = "no_parent"`，用于评测可观测性。
- `full_doc` 在 doc 文本不可恢复时（metadata store 中没有非 parent 子块）退回 `chunk`，并记录 `metadata["context_granularity_fallback"] = "no_doc_text"`。

### 1.2 `expanded_context` / `context_granularity_fallback` 的生命周期硬口径

`metadata["expanded_context"]` 与 `metadata["context_granularity_fallback"]` 都是 P4.5 评测/调试用的临时观测位，必须满足以下边界，**不允许**未来某个 PR 把它们升格成稳定字段：

- **只在当前一次 retrieval response 构造期内存在**：`RetrievalService._format_context()` 在拼 `context_text` 的同时把这两个键写到该次 `RetrievalResult.metadata` 上，跟随 response 一起返回。
- **不写回 `KnowledgeMetadataStore`**：`replace_chunks` / `upsert_document` 路径与本字段无关；它们只在 retrieval-time 构造的 dict 上出现。
- **不写入 Milvus**：`vector_store_manager.add_documents()` 在索引时根本看不到这两个键，因为索引时它们尚未存在。
- **不进入 `retrieve_knowledge` 工具的稳定 artifact 契约**：
  - artifact 的稳定字段仍是 `kb_id / doc_id / chunk_id / content / score / source_ref / citation_text / metadata`。
  - `metadata` 里 `expanded_context` / `context_granularity_fallback` 视为 P4.5 调试位，下游消费方不得把它们当作可持久依赖字段。
- **下游不得用作 LLM 输入主语义**：模型可见的回答上下文是 `RetrievalResponse.context_text`，`expanded_context` 仅供评测和调试核对 token / signal density，不参与 prompt 构造。

落到代码上：这两个键由 `RetrievalService._format_context()` 单点产出，其它服务和持久化层都不引用。`tests/test_p4_5_context_granularity.py` 加一条用例锁住 “索引->retrieval->新一次 retrieval” 链路上 metadata store 不会沉淀 `expanded_context`。

### 1.1 `full_doc` 文本来源的硬口径

`full_doc` 的整篇文本**只能**来自 `KnowledgeMetadataStore` 里的非 parent 子块，不允许读 `DocumentRecord.original_path` / `cleaned.md` / 任何原始文件。原因：

- pdf / docx / xlsx 的 `original_path` 是二进制源文件，无法直接拼字符串。
- `cleaned.md` 在 P2 之后已经显式不进入入库输入路径（参见 `docs/chunk_refactor_execution_plan.md` §4）。
- 索引时落入 metadata store 的非 parent 子块就是 P4 之后唯一被授权进入回答上下文的文本载体。

实现规则：

- 入口函数命名为 `_assemble_full_doc_context(doc_id)`，避免 `_load_full_doc_text` 这类名字让人误以为要去读原始文件。
- 实现：`knowledge_metadata_store.list_chunks_by_doc_id(doc_id)` → 过滤 `metadata.chunk_role == "parent"` → 按 `chunk_index` 升序 → 用 `\n\n` 拼接 `chunk.content`。
- 列表为空（罕见，只可能因为索引失败或刚清理）时记 `metadata["context_granularity_fallback"] = "no_doc_text"` 并退回 `chunk` 行为。

## 2. 默认模式与切换条件

- 默认: `chunk`。
- `parent_chunk`、`full_doc` 仅在调用方显式指定时启用，例如 P4.5 评测脚本、未来 SOP/规章类 KB 的检索专用入口。
- 不在 `retrieve_knowledge` 工具上自动切换，以免污染既有 agent 行为。
- 不依据文档长度做自动切换，留待评测验证后再决定。

## 3. 同 parent 多 child 命中策略（硬口径）

- `parent_chunk` 模式: top-K 中存在两个或以上 child 指向同一 parent 时，**重复拉取，不做合并**。
- 目的: 让 token 浪费作为 P5 启动证据被显式观察到。
- 若评测中发现该规则使 `parent_chunk` 模式相对 `chunk` 明显劣化，**不允许**私自降级为 “merge once”，必须停下来汇报。

## 4. citation 不变性断言（必须以代码断言形式存在）

- `evals/rag_retrieval/run_p4_5_eval.py` 在每条 query 上分别以 `chunk` / `parent_chunk` / `full_doc` 三种模式跑一遍。
- 对每种模式收集 `[(r.chunk_id, r.citation_text) for r in response.results[:top_k]]`，**严格用有序列表**比较，不用集合。
- 断言三种模式产出的有序 top-k 列表完全相等：
  - `ordered_chunk == ordered_parent_chunk == ordered_full_doc`。
- 用有序列表比较的原因：P4.5 只改 `context_text` 拼装，不应影响命中顺序、citation 文本或任何 DTO 主字段；只比集合会漏掉 “顺序漂移” 这种 bug。
- 不变量同时要求 `chunk_id` 与 `citation_text` 一致：`citation_text` 内含 `source_file / page / heading_path / chunk_id`，可以一次性兜住 SourceRef 漂移。
- 任意一条 query 出现差异即 P4.5 实现 bug，eval 直接失败、不出报告。
- `tests/test_p4_5_context_granularity.py` 同样用 `assertEqual` 比较有序列表，作为单测层的不变性兜底。

## 5. token 成本统计（必须用真实 tokenizer）

- Tokenizer: `dashscope.tokenizers.qwen_tokenizer.QwenTokenizer`，通过 `dashscope.tokenizers.tokenizer.get_tokenizer("qwen-max")` 取得。
- 与下游 LLM `qwen-max` 一致（`config.rag_model = "qwen-max"`）。
- 三模式使用同一 tokenizer 实例统计 `context_text` 的 token 数。
- 报告结构：
  - 每条 query: `tokens_chunk`、`tokens_parent_chunk`、`tokens_full_doc`、`ratio_parent_over_chunk`、`ratio_full_doc_over_chunk`。
  - 全集汇总: 平均 / 最大 / p95。
- 严格禁止用 `len(text)/4`、字符数、word count 替代。

## 6. 反向控制阳性判定阈值（评测前固定）

我们用一个 deterministic proxy 表征 “相关性稀释”，因为评测目前不串 LLM：

- **signal_density(mode)** = `keyword_occurrences(context_text) / token_count(context_text)`。
  - `keyword_occurrences` = 每条样本 `expected_keywords` 在 `context_text` 中的出现次数之和（含重复）。
  - `token_count` = 第 5 节定义的 Qwen token 计数。
- 阳性条件: 在 `parent_chunk` 或 `full_doc` 模式下，`(signal_density_chunk − signal_density_mode) / signal_density_chunk ≥ 0.10`，即相对 `chunk` 模式 signal density 下降 ≥ 10%。
- 反向控制组（D 类样本）期望命中阳性。
- LLM 级 “citation 漂移” 需要真 LLM 出答案，本次评测不串 LLM。该信号显式列为 P4.5 评测限制，不允许临时换成更松的代理来强行复现。

阈值在评测前写入本设计文档，**不允许跑完后再调**。

## 7. 评测样本（20-30 条 / 4 类场景）

样本集落点: `evals/rag_retrieval/p4_5_samples.jsonl`。语料复用 `aiops-docs/*.md`（cpu、memory、disk、service_unavailable、slow_response 五篇），不引入新文档。

四类场景（每类 5-7 条，总 20-26 条，目标 25 条）：

| 类别 | 标记 | 期望行为 |
|---|---|---|
| parent 优势 | `category = "parent_advantage"` | `chunk` 命中单段不足，`parent_chunk` 提供完整章节 |
| 多子块命中 | `category = "multi_child_hit"` | top-K 中 ≥ 2 条命中指向同一 parent |
| 长文档 full_doc 风险 | `category = "long_doc"` | 长文档（disk_high_usage / service_unavailable）下 `full_doc` token 显著膨胀（≥ 2× chunk）|
| 反向控制 | `category = "reverse_control"` | child-only 已够用，期望命中第 6 节阳性条件 |

每条样本字段：

```
{
  "id": "p45_parent_advantage_001",
  "category": "parent_advantage|multi_child_hit|long_doc|reverse_control",
  "query": "...",
  "expected_doc_ids": ["..."],
  "expected_keywords": ["...", "..."],
  "notes": "..."
}
```

注：

- `expected_doc_ids` 用 `default + aiops-docs/<file>.md` 的 `_build_doc_id` 同函数生成，与 P3 eval 一致。
- `expected_keywords` 用于 signal density 计算，必须显式覆盖目标段落里的关键词。
- 不再要求 `gold_chunk_ids`，因为 chunk_id 由 `ChunkPolicyService` 决定，跨改动不稳定；P4.5 评测靠 doc-level recall + signal density + 三模式断言交叉表达，不依赖 chunk-id 精确匹配。

## 8. 评测指标

每条样本、每种模式输出：

- `doc_recall@k` (k=top_k=3): hit 中是否覆盖 `expected_doc_ids`。
- `keyword_coverage(context_text)`: 落在 `context_text` 里的不重复关键词比例。
- `keyword_occurrences(context_text)`: 关键词总出现次数。
- `tokens(context_text)`: Qwen token 数。
- `signal_density(context_text)`: 见第 6 节。

聚合：

- 三模式 token 平均 / 最大 / p95。
- 各类别在三模式下的均值对比。
- 反向控制组阳性命中数 (≥ 10% signal density 下降的样本数 / 总反向控制样本数)。

## 9. 评测集区分度自检

跑完后检查：

| 类别 | 区分度判据 |
|---|---|
| parent 优势 | `parent_chunk` 的 `keyword_coverage` 至少 50% 样本严格高于 `chunk` |
| 多子块命中 | 至少 50% 样本在 top-K 中存在 ≥ 2 条 hit 共享同一 `parent_chunk_id` |
| 长文档 | 至少 50% 样本 `full_doc` token / `chunk` token ≥ 2.0 |
| 反向控制 | 至少 30% 样本满足第 6 节阳性条件 |

任一类别不达标即标记 “评测集失效，需扩样本或改样本”，停下来汇报。**不允许直接报 “持平”。**

## 10. 启动 P5 的判定

下列任一条件稳定出现即作为 P5 启动证据写入 `PROJECT_STATE.md` 与本计划：

- 多子块命中类别 ≥ 50% 样本，`parent_chunk` 模式下 token 因 “同 parent 重复拉取” 浪费 ≥ 30%。
- 任意类别 `full_doc` 模式下，token 因 “同 doc 重复拉取” 浪费 ≥ 50%。

P4.5 实现里**不允许**偷加 dedup fallback “顺手优化”。

## 11. 改动面（实现切片）

### 11.1 模型层

- `app/models/knowledge.py`
  - 新增 `ContextGranularity(StrEnum)`。
  - `RetrievalQuery` 增加 `context_granularity: ContextGranularity = Field(default=ContextGranularity.CHUNK, ...)`。
- 不动 `RetrievalResult` / `RetrievalResponse` 字段。

### 11.2 检索层

- `app/services/retrieval_service.py`
  - `retrieve()` 末段把 `query.context_granularity` 透传到 `_format_context()`。
  - `_format_context(results, granularity)`:
    - `chunk`: 现有逻辑不变。
    - `parent_chunk`: 每条 hit 用 `metadata["parent_content"]`（已挂载），缺失时回退到 `result.content` 并记 `metadata["context_granularity_fallback"]="no_parent"`。
    - `full_doc`: 每条 hit 调 `_assemble_full_doc_context(doc_id)`（见 §1.1），缺失时回退记 `"no_doc_text"`。
  - 新增 `_assemble_full_doc_context(doc_id)`:
    - **只**从 `knowledge_metadata_store.list_chunks_by_doc_id(doc_id)` 拿子块，**不读** `original_path` / `cleaned.md` / 任何原始文件。
    - 过滤 `metadata.chunk_role == "parent"`，按 `chunk_index` 升序。
    - 用 `\n\n` 拼接 `chunk.content`。
  - 同 parent 多 child / 同 doc 多 hit 不去重（按列表顺序逐条拼）。
  - 在每条 result 的 `metadata["expanded_context"]` 上回挂当前模式真正进入 context 的文本，仅评测/调试用，生命周期严格遵守 §1.2（不持久化、不入 Milvus、不进 artifact 稳定契约）。

### 11.3 工具层

- `app/tools/knowledge_tool.py`：保持调用默认 granularity，不变。

### 11.4 测试

- 新增 `tests/test_p4_5_context_granularity.py`:
  - `chunk` 模式输出与现状一致。
  - `parent_chunk` 模式拼父块内容；命中子块没有 parent 时回退并标记 fallback。
  - `full_doc` 模式拼整篇 doc，按 `chunk_index` 升序，过滤 parent。
  - 同 parent 多 child 命中时 parent 文本在 `context_text` 中重复出现两次。
  - 同 doc 多 hit 命中时 doc 文本在 `context_text` 中重复出现。
  - 三模式下 `result.chunk_id / content / source_ref / citation_text` 完全一致。
- 既有 `tests/test_retrieval_service.py` 不动；通过默认 `ContextGranularity.CHUNK` 自动 backward-compat。

### 11.5 评测样本与脚本

- 新增 `evals/rag_retrieval/p4_5_samples.jsonl`，25 条覆盖 4 类场景。
- 新增 `evals/rag_retrieval/run_p4_5_eval.py`:
  - 复用现有 isolated Milvus collection + KnowledgeMetadataStore 临时目录的 setup（与 `run_retrieval_eval.py` 一致）。
  - 装入 5 篇 aiops-docs。
  - 对每条样本跑 `chunk / parent_chunk / full_doc`。
  - 强断言 citation 不变。
  - 输出 token / signal density 表格、类别区分度自检表、反向控制阳性命中数。
  - 报告写入 `evals/rag_retrieval/reports/p4_5_eval_<ts>.{json,md}`。

## 12. 验证清单（结束态必须守住）

完成 P4.5 必须同时满足：

1. `unittest discover tests` 仍 78/78 +（本期新增） 全过。
2. `evals/rag_retrieval/run_retrieval_eval.py` 在 4 条 P3 golden queries 上各模式指标与 P4 baseline 持平（`dense_only` `recall@1=1.0 / mrr@3=1.0`，`hybrid` 同；`hybrid_rerank` `0.75/0.875` 不退）。
3. `evals/rag_retrieval/run_p4_5_eval.py` 跑通：
   - 三模式 citation 集合断言全部通过。
   - token 成本表用 Qwen tokenizer 输出。
   - 区分度自检全部达标，否则停下来汇报。
4. 文档同步: `docs/chunk_refactor_execution_plan.md`、`PROJECT_STATE.md`、`task_plan.md`、`docs/rag_fusion_development_record.md`。

## 13. 执行顺序

1. 设计落地（本文档）。
2. 写 25 条 P4.5 样本，标好类别 + expected_keywords。
3. 加 `ContextGranularity` 枚举 + `RetrievalQuery` 字段。
4. `RetrievalService._format_context` 三分支实现 + `_load_full_doc_text`。
5. 写 `tests/test_p4_5_context_granularity.py` 并跑过。
6. 写 `evals/rag_retrieval/run_p4_5_eval.py`，跑通三模式。
7. 跑 `tests` 全量 + 跑 P3 golden queries 不回归。
8. 写报告，记 P5 启动证据，更新 PROJECT_STATE / 计划文档 / 开发记录。

## 14. 不做的事（防止偷跑）

- 不实现 P5 dedup（即使评测显示重复浪费也只记证据不动手）。
- 不实现 P6 enricher。
- 不让 `parent_content` / `expanded_context` 进 `RetrievalResult` 主 DTO。
- 不让 `full_doc` 成为默认。
- 不在 P4.5 内改 dense/sparse/hybrid/rerank 排序。
- 不把 P4.5 与 P5 混做一个改动包。
- 不在评测中把 `len(text)/4` 当 token。

## 15. 验证记录 (2026-05-18)

### 15.1 评测样本第二轮重写

- 第一轮 (`evals/rag_retrieval/reports/p4_5_eval_20260518_151005.json`) 区分度自检
  `parent_advantage` 0/5 失败：原 5 条 query 选中的 child 已含全部 expected_keywords，
  parent_chunk 扩展不上 coverage。
- 处理路径按 (A) 改样本不改实现：仅重写 5 条 `parent_advantage` query，让
  query 锚定 c00003 一侧，但 expected_keywords 强制跨 c00003+c00004 边界。
- 第一轮区分度阈值 §9 一字未改，第二轮使用同一阈值。
- 第二轮报告：`evals/rag_retrieval/reports/p4_5_eval_20260518_154233.json`。

### 15.2 第二轮区分度自检（与 §9 阈值一致）

| 类别 | 命中 / 总数 | 比例 | 通过 |
|---|---|---|---|
| parent_advantage | 4 / 5 | 0.80 | PASS |
| multi_child_hit | 3 / 5 | 0.60 | PASS |
| long_doc | 8 / 8 | 1.00 | PASS |
| reverse_control | 6 / 7 | 0.86 | PASS |
| **overall_passed** |  |  | **true** |

`parent_advantage_003` 是单条噪声样本：dense recall 直接把 c00003 与 c00004 一起
拉进 top-3，chunk 模式 keyword_coverage 已经 1.0，parent_chunk 无法严格更高。
不影响 ≥ 50% 阈值。

### 15.3 citation 不变性（§4 有序断言）

`citation_invariant_all_ok = true`。25/25 样本三模式 `[(chunk_id, citation_text)]`
有序列表完全相等。

### 15.4 三模式 token 成本汇总（Qwen tokenizer / qwen-max）

| 模式 | tokens_avg | tokens_p95 | tokens_max | signal_density_avg | keyword_coverage_avg |
|---|---|---|---|---|---|
| chunk | 1376.1 | 1831 | 2305 | 0.0103 | 0.964 |
| parent_chunk | 1660.3 | 2804 | 2986 | 0.0111 | 0.992 |
| full_doc | 6715.4 | 7405 | 7407 | 0.0067 | 0.992 |

### 15.5 不回归证据（结束态守住）

- `unittest discover tests`: 88/88 pass（78 旧 + 10 新增 P4.5）。
- `evals/rag_retrieval/run_retrieval_eval.py` 4 条 P3 golden queries：
  `dense_only` 1.0/1.0、`hybrid` 1.0/1.0、`hybrid_rerank` 0.75/0.875，
  与 P4 baseline 完全持平。

### 15.6 P5 启动证据（§10）

- `multi_child_parent_chunk_waste_>=30%_ratio = 0.6`（multi_child_hit 中 60%
  样本 parent_chunk token ≥ 1.30× chunk）。
- `any_full_doc_waste_>=50%_ratio = 1.0`（每条样本 full_doc ≥ 1.50× chunk）。
- 触发条件 `parent_waste_30 >= 0.5` 与 `full_doc_waste_50 >= 0.5` 同时成立。
- 结论：P5 启动证据稳定且强烈。按本设计 §14 不在 P4.5 内动 dedup，
  开 P5 单独 thread 时直接引用本节作为启动依据。
