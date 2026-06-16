# P5.f3 LLM 端 citation 漂移验证设计与执行计划

日期: 2026-05-19
范围: 仅 P5.f3。明确不修 ChunkPolicy parent 阈值（P5.f2 caveat (b)），不实现 P6。

## 0. 边界与不变量

- 不动 P5 / P4.5 / `ChunkPolicyService` 实现，全程验证-only。
- 不动 retrieval / context 的现有契约；P5.f3 在 retrieval 层之外加一层 LLM call。
- 阈值与范围跑前固定，跑后不调。
- LLM 调用失败不能伪装成数据，必须按容错规则处理或停下来汇报。
- P5.f2 已锁的 §4 不变性（6 条）必须仍然成立——这是 P5.f3 的强断言。
- LLM 端的所有指标都是 **citation drift 的 proxy**，不是事实级 citation correctness 的真值（见 §5.4）。
- `full_doc` 在长文档语料上的 out-of-scope 状态在 P5.f3 不变（见 §4）。

## 1. 目标与方法

### 1.1 想回答的核心问题

P4.5 / P5 / P5.f1 / P5.f2 都只证明了 retrieval/context 侧不漂——`RetrievalResult.chunk_id / content / source_ref / citation_text` 在所有 granularity / strategy / corpus 下都 byte-equal。但**没有证据**说明：把这个稳定的 context 喂给 LLM 后，模型回答里引用的 chunk_id 是否还稳定。

P5.f3 的目标就是补上这块"主链路最后一公里"的证据。

### 1.2 方法

利用 P4.5 已经把 `[chunk: <chunk_id>]` 嵌进 `RetrievalResponse.context_text` 的事实，prompt 让 LLM 用同样格式引用，回答里 grep 出 chunk_id，比对：

- 引用 chunk_id ⊆ retrieval 返回的 chunk_id set？（hallucination_rate）
- LLM 至少 mention 1 个 retrieval 给的 chunk？（coverage_rate）
- 集合相似度（Jaccard）

不是去问"LLM 答得对不对"，是问"LLM 引用的位置是否还指向 retrieval 真正给的位置"。

## 2. 样本与语料

复用 P5.f1 / P5.f2 同一 18 条样本 + 3 篇 MinerU 长文档语料：

- `evals/rag_retrieval/p5_long_doc_samples.jsonl`（18 条 / 3 类）
- 3 篇 artifact: `h3c_campus_switch_installation_guide_cn` / `h3c_mc101_mc102_user_manual_cn` / `arxiv_vision_transformer`
- 总规模 349 children + 15 parents

样本不重写、归类不调；唯一新维度是 LLM call。这保证 P5.f3 与 P5.f1 / P5.f2 严格可比。

## 3. 3-cell 主矩阵

主评测只跑 3 个 cell：

| cell | 评测目的 |
|---|---|
| `NONE × chunk` | LLM 在 P5 baseline（最小 context）下的 citation 行为 |
| `DOC_LEVEL × chunk` | dedup 后 LLM citation 是否仍稳 |
| `DOC_LEVEL × parent_chunk` | 把 P4.5 expansion 加进来后 LLM citation 是否漂 |

显式不开 `NONE × parent_chunk`：

- P5.f2 caveat (b) 显示这一 cell 在长文档语料上 fallback rate 0.833，15/18 sample 实际 context 等同于 `NONE × chunk`；
- 信号高度重叠，只增加 LLM 调用数与解释噪音；
- 如果未来 ChunkPolicy parent 阈值重构后 fallback 显著降下来，再单独补 cell。

LLM 调用次数 = 18 × 3 = **54 次**。

## 4. `full_doc` out-of-scope（写死）

`full_doc` granularity **不进 P5.f3 主评测矩阵**，理由是 P5.f2 caveat (a) 已经证明：

- `DOC_LEVEL × full_doc` tokens_avg = 46,302、p95 = 57,901、max = 57,906
- `NONE × full_doc` 更高
- `config.rag_model = qwen-max` context window = 32,768 tokens
- 即使 dedup 后仍超 1.4×；NONE 模式超 2.5×

**硬规则**: P5.f3 不因为加了 LLM 就把 `full_doc` 偷偷带回主评测。如果未来要测 `full_doc` 的 LLM 行为，必须**单开** P5.f3.b（短文档子集专项），不在本计划内执行。

这条规则同时写进 `PROJECT_STATE.md` 的 P5.f2 caveat (a) 做交叉锚点，避免后续讨论时 corpus / mode 边界被悄悄修改。

## 5. citation 漂移度量定义

### 5.1 主门槛 / 软观察分层（沿用 P5.f2 软观察精神）

| 指标 | 类型 | 跑前阈值 |
|---|---|---|
| **retrieval 侧 §4 不变性** | 强断言 | 6 条全过；任一失败 = AssertionError 立刻停 |
| **hallucination_rate** | 主观察 | 不设 pass/fail（G1） |
| **coverage_rate** | 软观察 | 不设 pass/fail |
| **citation_jaccard** | 软观察 | 不设 pass/fail |

P5.f3 是这条线上第一次接真 LLM，没有先验数据建阈值。先观测，不门槛；让 P5.f3 数据本身成为后续阶段建阈值的依据。

### 5.2 hallucination_rate（主观察）

定义：

```
retrieval_chunk_ids(sample, cell) = {r.chunk_id for r in retrieval_response.results}
llm_cited_chunk_ids(sample, cell) = parse_citations(llm_answer_text)
hallucination_count(sample, cell) = |llm_cited_chunk_ids - retrieval_chunk_ids|
hallucinated(sample, cell) = (hallucination_count > 0)
hallucination_rate(cell) = #{sample : hallucinated(sample, cell)} / total_samples
```

含义：LLM 在回答里引用了 retrieval 范围**外**或**错位**的 chunk_id 的样本占比。

### 5.3 coverage_rate（软观察）

```
covered(sample, cell) = (|llm_cited_chunk_ids ∩ retrieval_chunk_ids| ≥ 1)
coverage_rate(cell) = #{sample : covered(sample, cell)} / total_samples
```

含义：LLM 至少 mention 了 1 个 retrieval 给的 chunk_id 的样本占比。tiny coverage 说明 LLM 不是在用 context 答题，是在用 parametric memory 答题。

### 5.4 citation_jaccard（软观察）

```
citation_jaccard(sample, cell) =
    |llm_cited ∩ retrieval| / |llm_cited ∪ retrieval|
    （若分母为 0 则视为 0.0，并单独标注 sample）
```

含义：引用集合与 retrieval 集合的相似度。

### 5.5 必须显式写进报告的 proxy 限制

> **P5.f3 的 LLM 指标是 citation drift 的 proxy，不是事实级 citation correctness 的真值。**

具体含义（必须在报告 markdown 头部明确写出，不允许只在脚注里）：

- hallucination_rate 只衡量"引用范围外 / 错位引用"的**表层信号**。LLM 完全可能：
  - 引用了 retrieval 给的 chunk_id（hallucination=0），但回答内容与该 chunk 真实内容不一致（事实错误未被检出）；
  - 引用 retrieval 范围外的 chunk_id（hallucination=1），但实际引用的是 retrieval 给过的另一段事实（位置漂移但内容正确）。
- coverage_rate 不能区分"模型用 context 答题"与"模型 parametric 答完后顺手贴个引用"。
- 这些指标合在一起，**只能回答"chunk_id 标识符在 prompt 与 answer 之间是否对齐"**，不能回答"LLM 答得对不对"。
- 真正的事实级 citation correctness 验证需要人工 / LLM-as-judge 评测，**不在 P5.f3 范围**。

## 6. Prompt 设计

```text
你是知识库问答助手。请基于给定的参考资料回答用户问题。

引用规则:
- 每个事实陈述后用 [chunk: <chunk_id>] 格式标注引用。
- <chunk_id> 必须是参考资料中出现过的 chunk 标识符。
- 如果参考资料里找不到答案，直接说"参考资料中未找到相关信息"。

参考资料:
<context_text>

用户问题: <query>

请按以下格式回答:
回答: <回答内容，每个事实后标注 [chunk: <chunk_id>]>
```

设计原则：

- **简单 prompt**: 不加"每句必须引用"、"不要凭空想象"等强化约束，避免人为压低 hallucination rate 掩盖真实问题（用户 F 决策）。
- **保留一条基本协议**: "chunk_id 必须来自参考资料中出现过的 chunk"——这是协议层面的硬约束，不算额外语言束缚。
- 不在 prompt 里告诉 LLM 这是 citation drift 测试。

## 7. LLM 选型与配置

| 项 | 值 | 理由 |
|---|---|---|
| 模型 | `qwen-max` | 与 `config.rag_model` 一致；与 P4.5 / P5 / P5.f1 / P5.f2 token 阈值口径一致 |
| temperature | 0.0 | 评测要求结果可重现；漂移信号必须不来自采样随机性 |
| max_tokens | 1024 | chunk/parent_chunk 模式 context 1-2K tokens，回答预算 1K 充足 |
| top_p | 1.0（默认） | 与 temperature=0 配合 |
| 调用接口 | dashscope / langchain `ChatQwQ` 或 `ChatTongyi` | 复用现有 LLM 接入路径 |

## 8. citation 解析

### 8.1 提取 regex

```python
CITATION_REGEX = re.compile(r"\[chunk:\s*([^\]]+?)\s*\]")
```

匹配 `[chunk: <id>]`，捕获 `<id>` 部分。容忍前后空格。

### 8.2 提取规则

- 一次回答里同一 chunk_id 多次引用只算一次（用 set）。
- 提取得到的 raw chunk_id 与 retrieval 的 chunk_id 做严格 string 相等比对，不做 fuzzy match（避免 LLM 把 `:c00001` 写成 `: c00001` 时被强行 normalize 掉真实漂移）。

### 8.3 边界情况

- **空回答 / "未找到相关信息"**: `llm_cited_chunk_ids = set()`、`hallucinated = False`、`covered = False`、`jaccard = 0.0`，单独标注 `empty_answer = True`。
- **解析失败 / 回答完全没引用**: `llm_cited_chunk_ids = set()`，与上同处理，标注 `no_citation = True`。
- 这两类样本进入聚合统计，但报告里单独高亮，不允许默默并入"通过"。

## 9. 阈值与断言（跑前固定）

### 9.1 强断言（通过即下一步，失败即停）

- **retrieval §4 不变性 6 条**: 与 P5.f2 完全相同。任一失败 → `AssertionError`，立即停下来汇报"P5 / P4.5 实现 bug"或"P5.f3 接入污染了 retrieval 路径"。

### 9.2 软观察（不设 pass/fail）

- hallucination_rate、coverage_rate、citation_jaccard、empty_answer 比例、no_citation 比例。
- 报告里必须列出 3-cell × 这 5 个指标的全表。

### 9.3 必须显式高亮的 corner case

- 任意 sample 的 `hallucinated = True` 时，单独列出 LLM 引用了哪些范围外 chunk_id（前 5 个）。
- 任意 cell 的 `coverage_rate < 0.5` 时，在报告头部高亮（"LLM 半数以上回答没用 retrieval context"是个值得停下来讨论的信号，但不直接 fail）。
- 任意 cell 的 `empty_answer rate > 0.2` 时，单独高亮（≥20% sample LLM 拒答说明 prompt 或 corpus 有问题）。

## 10. LLM 调用容错

| 场景 | 处理 |
|---|---|
| LLM 调用异常 | 重试 2 次（共 3 次尝试） |
| 调用 timeout | 30s timeout，超时算一次失败，进重试 |
| 重试用尽仍失败 | 该 sample 该 cell 标 `llm_call_failed = True`，**不进聚合统计**，但报告显式列出失败 sample id 与 cell |
| 失败 sample 数 ≥ 50%（任一 cell） | `AssertionError` 停下来汇报，不允许"部分数据写进报告" |
| 全部 sample × 全部 cell 都失败 | 同上，立即停 |

调用速率：54 次串行调用，按 qwen-max 平均 2-3s/call 估算 ~3 min wall clock。不并发，避免 rate limit。

## 11. 实现切片

### 11.1 新增

- `evals/rag_retrieval/run_p5_llm_eval.py`
  - 复用 `run_p5_long_doc_eval.py` / `run_p5_joint_eval.py` 的 corpus indexing 与 isolated Milvus / metadata store 框架
  - 加 LLM call layer
  - 加 citation parser
  - 输出 3-cell × 5 指标聚合表 + per-sample 明细 + 高亮 corner case
  - 报告写 `evals/rag_retrieval/reports/p5_llm_eval_<ts>.{json,md}`

### 11.2 不动

- `app/*` 一字不动
- `tests/*` 一字不动（P5.f3 不加单测；citation parser 是 eval 脚本内部 helper）
- `evals/rag_retrieval/p5_long_doc_samples.jsonl` 不动
- `run_p5_eval.py` / `run_p5_long_doc_eval.py` / `run_p5_joint_eval.py` 不动

### 11.3 LLM 接入

复用现有 `ChatTongyi` 或 dashscope SDK 直调。具体接入方式在脚本里选择，但必须满足：

- 使用 `config.dashscope_api_key` 与 `config.rag_model`
- temperature=0.0
- 单次调用 timeout 30s
- 失败重试 2 次

## 12. Stop-loss

- 评测**单轮**跑完即结论，不重写 prompt / 不调阈值。
- §4 不变性失败 → 立即停（实现层 bug）。
- LLM 调用失败 ≥ 50% → 立即停（环境 / API 问题）。
- 任意发现 P5 / P4.5 实现层问题 → 立即停下来汇报，不"先记下再说"。
- 不修 ChunkPolicy（P5.f2 caveat (b) 不在 P5.f3 范围）。
- 不开 `full_doc` cell（§4 已锁）。

## 13. 验证清单（结束态守住）

- `unittest discover tests`: 101/101 仍持平（P5.f3 不动 app/*）。
- retrieval §4 不变性 6 条 × 18 样本 × 3 cells: all OK。
- 3-cell × 5 软观察指标全表写进报告。
- corner case（hallucinated samples、coverage<0.5 cells、empty_answer>0.2 cells）显式高亮。
- 报告 markdown 头部显式标注两条文档约束（§5.5 + §4）。
- PROJECT_STATE / task_plan / chunk_refactor_execution_plan / dev record 同步更新，状态写法按 P5.f3 实际结果决定（complete / complete with caveats / blocked）。

## 14. 执行顺序

1. 设计落地（本文档）。
2. 写 `run_p5_llm_eval.py`，沿用 P5.f1 / P5.f2 框架。
3. 单轮跑评测。
4. 写报告，更新 4 份状态文档。
5. 决定 P6 是否进入"trigger 判定"阶段（按 PROJECT_STATE Next Step）。

## 15. 不做的事（防止偷跑）

- **不在 P5.f3 修 ChunkPolicy parent 阈值**: caveat (b) 是 P4.5 / ChunkPolicy 边界，混做会污染 LLM citation drift 信号。
- **不偷偷把 `full_doc` 带回主矩阵**: §4 已写死 out-of-scope。即使 LLM context window 升级到 128K，本计划也不变；要测 full_doc 单开 P5.f3.b。
- **不把 LLM 软观察指标当事实级 citation correctness 的真值**: §5.5 已写明 proxy 限制，报告必须显式标注。
- **不在 P5.f3 加 LLM-as-judge / 人工评测**: 这两条是 P5.f3 之外的独立工作。
- **不实现 P6 enricher**: P5.f3 不影响 P6 gate 状态。
- **不允许 prompt 里加"必须每句引用"、"绝对不能凭空想象"等强化约束**: 这会人为压低 hallucination_rate，掩盖真实漂移。
- **不允许"调用失败但脚本继续跑、报告里写部分数据"**: 失败必须按 §10 处理或停。
- **不允许跑后调阈值或重写 prompt**: P5.f3 是单轮 stop-loss。

## 16. 文档约束（必须显式写进报告）

按用户 P5.f3 拍板时的两条要求：

1. **P5.f3 的 LLM 指标是 citation drift 的 proxy，不是事实级 citation correctness 的真值。** 报告 markdown 头部必须显式标注这条。
2. **`full_doc` 在长文档语料上继续 out-of-scope**——不因为这一轮接了 LLM 就把它偷偷带回主评测矩阵。报告与 PROJECT_STATE 必须保持这条边界一致。
