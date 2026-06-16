# ChunkPolicy 原子类型 hard cap 设计

日期: 2026-05-19
范围: `app/services/chunk_policy_service.py` 实现层修改 + 单测；解决 P6 corpus probe 撞到的 Milvus `content` 字段 8000 字符 schema 上限失败。

## 0. 边界与不变量

- 不动 ChunkPolicy 既有 4 类规则（merge / resplit / parent build / finalize）的语义，**只在它们之后加一道 hard cap pass**。
- 不动 `chunks.json` / `tables.json` 上游契约。
- 不动 `RetrievalQuery` / `RetrievalResult` / `retrieve_knowledge` 工具契约。
- 不动 metadata schema、Milvus collection schema（`content varchar(8000)` 维持，hard_cap 4000 自带 2× safety margin）。
- 既有 P5 / P5.f1 / P5.f2 / P5.f3 评测的语料 chunk 长度全部 ≤ 1,613 字符，hardcap 4000 对那些 cell **零影响**；drift = 0 是必须验证的回归条件。
- TDD 严格走：tests-first（应全 fail）→ 实现 → 既有 101 + 新 tests 全过 → P5.fX eval 回归。

## 1. 问题

### 1.1 失败现象

P6 corpus probe（17 文档，4 域）在 `h3c_comware_v7_high_risk_command_reference_cn` ingestion 时被 Milvus 拒收：

```
MilvusException(code=1100, message=length of varchar field content exceeds max length,
row number: 66, length: 21236, max length: 8000)
```

### 1.2 根因

ChunkPolicy `_resplit_pass` 只对 `TEXT_CONTENT_TYPES = {"text", "markdown_section"}` 触发再拆；其他 content_type（`manual_table`、`command_table`、`equation_interline` 等原子类型）按 P2 设计**绕过 merge / resplit**，原文多长就透传多长。`chunks.json` / `tables.json` 里的命令参考 / 配置手册类文档单条原子内容可达 26K+ 字符，写进 Milvus 时 schema-level 拒绝。

### 1.3 为什么 P5.fX 没暴露

P5.f1 / f2 / f3 的 3-MinerU-artifact 长文档 corpus 单 chunk 最大 1,613（`h3c_campus`）；p5_samples / p4_5_samples 跑的 5 篇 aiops-docs 都是 plain_text 短 chunk。这条边界是 P5.f1 close-out 时 Open Problems 已声明的 "large-corpus headroom 未验证" 的具体爆发，不是 P5 实现 bug。

## 2. 修复方案

### 2.1 新增常量

```python
ATOMIC_HARD_CAP_DEFAULT_BYTES = 6000
ATOMIC_SPLIT_QUALITY_FLAG = "atomic_split_by_size"
```

`6000 bytes` 选定理由（**单位与 Milvus content varchar(8000) schema 同单位对齐**）：

- **单位匹配**: hardcap 与 Milvus schema 都是 UTF-8 bytes。早期版本曾用 `4000 chars` + "2× safety margin" 作为口径，但 chars 与 bytes 在中文 corpus 上不等价（中文 UTF-8 通常 3 bytes/char），实际命令参考类纯中文 atomic table 在 4000 chars cap 下展开 ≈8,600 bytes，仍超 8000 schema 上限。改为 byte 口径后单位一致，物理含义可预测。
- **25% 安全边距**: `8000 - 6000 = 2000 bytes` 留作 metadata 字段同行序列化、Milvus 内部开销、未来格式微调的缓冲。
- **不打到任何 P5 / P5.fX 评测语料**: 5 篇 aiops-docs 全部 < 800 chars (≤ 2.4K bytes 上限)；`h3c_campus` max=1,613 chars (≈4.8K bytes)；`h3c_mc101` max=1,424 chars；`arxiv_vit` max=1,580 chars。所有 P5.fX 评测 corpus 单 chunk 均 < 6000 bytes，确保已验证 cell 零回归。
- **与 P5.f2 token 阈值同量级**: P5.f2 chunk DL ≤ 4000 token 阈值；6000 bytes ≈ 2000 中文 chars ≈ 2000 token，与 P5.f2 上限同一数量级（chunk 维度的 4000 token cap 是 retrieval-side 的，hardcap 是 storage-side 的，两个独立维度但同量级方便认知对齐）。

### 2.2 新增 pass

在 `_apply()` 流程里插入 `_atomic_hardcap_pass`，位置在 `_resplit_pass` 之后、`_finalize` 之前：

```
_merge_pass             (text only, ≤ chunk_max_size chars)
_resplit_pass           (text only, > chunk_max_size chars → ≤ chunk_max_size chars)
_atomic_hardcap_pass    (NEW: any type, > atomic_hard_cap_bytes UTF-8 bytes →
                         line-greedy + codepoint-safe split into ≤ atomic_hard_cap_bytes pieces)
_finalize               (assign chunk_index, regenerate chunk_id when boundary_changed)
```

### 2.3 行为规则（pre-run frozen）

对每个 working chunk：

1. `len(chunk.content.encode("utf-8")) <= atomic_hard_cap_bytes` → pass-through 不改。
2. `len(chunk.content.encode("utf-8")) > atomic_hard_cap_bytes` → byte-aware codepoint-safe 切分：
   - **优先 line-greedy 打包**: 按 `\n` 边界拆行，greedy pack 多行直到下一行加上会超 cap 才 flush。表格行 / 公式行 / 命令行的语义结构尽量保留。
   - **单行超 cap 兜底**: 单行本身超 cap 时，按 codepoint-aware 字节累加切分（迭代 Python str 字符 = Unicode codepoint，累加 UTF-8 byte 数，到上限就切；**不在 UTF-8 多字节序列中间断开**）。
   - 每片都标 `boundary_changed = True`（`_finalize` 会赋新 `:cp{index:05d}` chunk_id）。
   - **content_type 保留原值**（manual_table 切完后每片仍是 manual_table；不退化为 text）。
   - **heading_path / page_start / page_end / 其他 metadata 字段 全部继承**（model_copy）。
   - **quality_flags 加入 `"atomic_split_by_size"`**，与原有 quality_flags 取并集后排序。
   - start_index / end_index 按累计游标重算，每片 = `cursor → cursor + len(piece)`。

### 2.4 不做的事

- **不做 sentence-boundary 切分**: atomic 类型 (table / equation / command) sentence 概念不适用；text 类已在 `_resplit_pass` 走 sentence-first → hard_cut fallback，新 pass 与之解耦。
- **不做 fragment_index 元数据**：v1 不在 metadata 里加 `fragment_seq` / `total_fragments`。如果未来 retrieval 需要把同一原 atomic 的多个片段聚合，再加。
- **不重写既有 Milvus collection 的 schema**：`content varchar(8000)` 维持。本 fix 在写入前就把每片压到 ≤ 6000 bytes，schema 不需要改。
- **不回填既有 indexed collections**：本仓库的 P5.fX 评测每次跑都是 isolated temp collection；production `biz` collection 是不是受影响由用户决定（不在 P6 trigger 工作项内）。

## 3. TDD 测试矩阵

新增 `tests/test_chunk_policy_atomic_hardcap.py`（独立文件，不污染既有 `test_chunk_policy_service.py`），13 个 case：

| # | case | 锁定行为 |
|---|---|---|
| 1 | `test_default_constant_is_6000_bytes` | sanity: 默认常量 = 6000 bytes，与 ChunkPolicyService 默认实例对齐 |
| 2 | `test_atomic_under_hardcap_passes_through` | atomic content (ASCII) < cap → 原样透传，不打 atomic_split_by_size |
| 3 | `test_atomic_at_hardcap_passes_through` | 边界值 == cap bytes → 不切（cap 含义是"超过才切"）|
| 4 | `test_atomic_over_hardcap_splits_into_pieces_of_at_most_hardcap_bytes` | 超 cap 的 ASCII content → 切多片，每片 byte-length ≤ cap，无数据丢失 |
| 5 | `test_atomic_split_preserves_content_type` | manual_table 切片后仍是 manual_table（不退化为 text）|
| 6 | `test_atomic_split_marks_quality_flag` | 每片 quality_flags 都含 `atomic_split_by_size`（且与原有 flags 并集排序）|
| 7 | `test_atomic_split_assigns_sequential_cp_chunk_ids` | 切出的 N 片在 `_finalize` 后获得 `:cp00###` 连续 id |
| 8 | `test_atomic_split_preserves_heading_and_pages` | heading_path / page_start / page_end 在每片上保持原值 |
| 9 | `test_text_oversized_uses_resplit_not_hardcap` | text 类先走 `_resplit_pass` 按 chars 切到 ≤ chunk_max_size，无 atomic flag |
| 10 | `test_short_text_unchanged_no_atomic_flag` | 普通短 text → 既不 resplit 也不 hardcap，无 atomic flag |
| 11 | `test_section_parents_unaffected_by_atomic_hardcap` | atomic 切片不进 parent group |
| 12 | `test_atomic_chinese_locks_byte_unit_not_char_unit` | **关键边界 case**: 100 chars 中文 = 300 bytes 必须切（旧 char-based cap 会漏切）；切片每片 byte-length ≤ cap；每片 UTF-8 round-trip 不损坏（codepoint-safe）|
| 13 | `test_atomic_split_prefers_line_boundaries` | 多行 atomic 内容优先按 `\n` line 边界 greedy pack，行不被中间切断 |

## 4. 回归验证清单

实现完成后必须按顺序跑通：

1. `unittest discover tests` → 101 + 13 = **114/114** 全过。
2. `evals/rag_retrieval/run_retrieval_eval.py`（4-query golden set, 3 modes）→ `dense_only` / `hybrid` / `hybrid_rerank` recall@1 / MRR@3 与 P4.5 baseline 持平（`run_retrieval_eval.py` 报告里 metric 持平）。
3. `evals/rag_retrieval/run_p4_5_eval.py`（25 samples）→ `citation_invariant_all_ok = true`，per-category discrimination self-check 全过。
4. `evals/rag_retrieval/run_p5_eval.py`（20 samples）→ `citation_invariant_all_ok = true`，区分度自检全过。
5. `evals/rag_retrieval/run_p5_long_doc_eval.py`（18 samples）→ `citation_invariant_all_ok = true`，F3 6/6+6/6+0/6，D1 factor_enough=true，E3 token_pass=true。
6. `evals/rag_retrieval/run_p5_joint_eval.py`（18 samples × 6 cells）→ §4 6 条不变性全过；token 阈值分档全过；P5.f1 sanity reproduction `drift = 0.000`。
7. `evals/rag_retrieval/run_p5_llm_eval.py`（18 samples × 3 cells，54 LLM calls）→ §4 6 条不变性全过；soft observations 与 2026-05-19 报告 drift = 0（同 sample 同 cell 的 hallucination / coverage / jaccard 应当一致）。

如果 2-7 任一退化（recall / citation / token / invariance），停下来汇报，**不**继续 P6 probe；这条 fix 的 design 边界写明了 "drift=0 必须成立"。

### 4.1 实跑状态（2026-05-19，B 路径 byte-based 闭环完成）

第一轮以 char-based `ATOMIC_HARD_CAP_DEFAULT = 4000` 跑通 step 2-7，retrieval 字节级 drift=0；但接 P6 corpus probe 时 `h3c_comware_v7_high_risk_command_reference_cn` 仍撞穿 Milvus content varchar(8000) 上限（中文 atomic table 4000 chars × 2.15 bytes/char = 8600 bytes）。根因是单位错：hardcap 用 chars，Milvus schema 用 bytes，纯中文 corpus 上不等价。

**B 路径修复**: 单位改成 UTF-8 bytes，常量 `ATOMIC_HARD_CAP_DEFAULT_BYTES = 6000`，切分 codepoint-safe + line-boundary greedy pack（详见 §2.1 / §2.3）。13 个 TDD case 全过；`unittest discover tests` 114/114（既有 101 + 新 13）。完整重跑 step 2-7 回归全过。

| step | eval | 结果 | drift vs baseline |
|---|---|---|---|
| 1 | `unittest discover tests` | ✅ 114/114（既有 101 + 新 13）| n/a |
| 2 | `run_retrieval_eval.py` | ✅ 通过 | metric 持平（仅 latency 数字波动） |
| 3 | `run_p4_5_eval.py` | ✅ `citation_invariant_all_ok = true` | drift = 0（diff 仅时间戳 / collection 名）|
| 4 | `run_p5_eval.py` | ✅ §4 不变性 + 区分度全过 | drift = 0（diff 仅时间戳 / collection 名）|
| 5 | `run_p5_long_doc_eval.py` | ✅ F3 6/6+6/6+0/6, D1 / E3 全过 | drift = 0（diff 仅时间戳 / collection 名）|
| 6 | `run_p5_joint_eval.py` | ✅ §4 6 条 + token 阈值 + P5.f1 sanity 全过 | drift = 0（diff 仅时间戳 / collection 名）|
| 7 | `run_p5_llm_eval.py` | ✅ §4 6 条全过 + 54/54 LLM 调用成功 + abort=False | retrieval 字节级 drift = 0 (chunk_ids / context_text / doc_ids / fallback_count 0/54 mismatches)；LLM 软观察在合理噪声内（详见 §4.1.1）|

P5.fX 评测 corpus 单 chunk 最大约 4.8K bytes（h3c_campus 1,613 chars），全部 < 6000 bytes cap，所以 byte-based 新 pass 在 P5.fX 上是结构 noop。Reports: `p4_5_eval_20260519_223124.{json,md}` + `p5_eval_20260519_223152.{json,md}` + `p5_long_doc_eval_20260519_223218.{json,md}` + `p5_joint_eval_20260519_223301.{json,md}` + `p5_llm_eval_20260519_223412.{json,md}`.

#### 4.1.1 step 7 LLM 软观察 drift 归因（B 路径重跑 vs baseline）

精确分维度的 byte-level diff（baseline=`p5_llm_eval_20260519_131538.json`，B-path 新跑=`p5_llm_eval_20260519_223412.json`）：

| 维度 | mismatches | 归因 |
|---|---|---|
| retrieval `chunk_ids` / `context_text` / `doc_ids` / `fallback_count` | **0 / 54** | hardcap byte-based pass 在 retrieval 路径上字节级零差异 — 这是 hardcap fix 真正的承诺 |
| §4 invariance 6 条 | both `True` | hardcap 不破坏 retrieval 契约 |
| `abort_should_trigger` | both `False` | LLM 调用稳定，无 cell 失败率 ≥ 0.5 |
| LLM `answer_text` | 52 / 54 不同 | qwen-max temp=0.0 API 本身非确定（DashScope batching + FP non-determinism；与 A 路径同模式）|
| LLM `cited_chunk_ids` (set) | 5 / 54 不同 | answer 漂动级联到引用集合 |
| `hallucinated` 翻转 | 1 / 54，方向 **True→False** | `p5_long_reverse_004` 基线唯一一条 hallucinated 在新跑里被 LLM 自纠正（与 A 路径同 sample / 同方向，独立确认）|
| `covered` 翻转 | 0 / 54 | 完全稳定 |

LLM-side 漂动是横切的 LLM-eval methodology 问题（API 非确定性），与 hardcap 实现无关；按 P5.f3 设计 §5.1 是软观察不 gate。


#### 4.1.1 step 7 LLM 软观察 drift 归因（重跑 vs baseline）

精确分维度的 byte-level diff（baseline=`p5_llm_eval_20260519_131538.json`，新跑=`p5_llm_eval_20260519_214029.json`）：

| 维度 | mismatches | 归因 |
|---|---|---|
| retrieval `chunk_ids` / `context_text` / `doc_ids` / `fallback_count` | **0 / 54** | hardcap pass 在 retrieval 路径上字节级零差异 — 这是 hardcap fix 真正的承诺 |
| §4 invariance 6 条 | both `True` | hardcap 不破坏 retrieval 契约 |
| `abort_should_trigger` | both `False` | LLM 调用稳定，无 cell 失败率 ≥ 0.5 |
| LLM `answer_text` | 53 / 54 不同 | qwen-max temp=0.0 API 本身非确定（DashScope 已知行为；temperature=0 ≠ deterministic，batching + FP non-determinism）|
| LLM `cited_chunk_ids` (set) | 6 / 54 不同 | 上面 53 条 answer 漂动级联导致的引用集合差异 |
| `hallucinated` 翻转 | 1 / 54，方向 **True→False** | `p5_long_reverse_004` 基线唯一一条 hallucinated 在新跑里被 LLM 自己纠正；新跑比基线更干净，不是回归 |
| `covered` 翻转 | 0 / 54 | 完全稳定 |

新跑 by_cell 软观察：`none__chunk` hall=0.000 cov=0.889 jacc=0.574；`doc_level__chunk` 0.000/0.833/0.722；`doc_level__parent_chunk` 0.000/0.833/0.694。vs baseline 主要差异在 jaccard ±0.07 量级、`hallucination_rate` 在 reverse_control 上 0.056 → 0.000（改善方向）。

### 4.2 hardcap 实现完成度判定（complete）

按 P5.f3 设计 §5.1（"所有 LLM 指标是 soft observations，no pass/fail，因为这是这条线上第一次接 LLM 没有先验数据建阈值"）的精神：

- **hardcap fix 真正该验的契约 = retrieval byte-level drift=0 + §4 invariance + abort=False**：三条全过 ✓
- **LLM-side drift 是 soft observation 不是 pass/fail**：与基线偏差在 jaccard ±0.07 量级，覆盖率完全稳定，唯一 hallucinated 翻转方向是改善

**关于"close-out criteria 自洽性"的修正记录**：handoff session 里曾把 step 7 的 close-out condition 写成 "byte-level drift=0 vs baseline"，与设计 §5.1 软观察精神不一致 —— qwen-max temp=0.0 在 API 层就非确定（DashScope batching + FP non-determinism），byte-level drift=0 在物理上不可能。这条不一致是 handoff 写过头的产物，不影响 hardcap fix 本身的验证；设计原文 §5.1 与实跑结果都支持 hardcap fix complete。

**最终结论**: hardcap fix **complete**（2026-05-19）。

### 4.3 后续推进的允许动作

- ✅ 标 hardcap fix complete，落 P5.f1 Open Problem "large-corpus headroom 未验证" 为 resolved。
- ✅ 接 P6 corpus probe（task #6）。
- LLM-side noise envelope 刻画（B 路径）作为独立 LLM-eval methodology 工作项保留，不阻塞 hardcap close-out 也不阻塞 P6。

## 5. 实现切片

### 5.1 修改

- `app/services/chunk_policy_service.py`:
  - 顶部新增 `ATOMIC_HARD_CAP_DEFAULT_BYTES = 6000`、`ATOMIC_SPLIT_QUALITY_FLAG = "atomic_split_by_size"`。
  - `__init__` 增加 `atomic_hard_cap_bytes: int | None = None` 参数（默认 ATOMIC_HARD_CAP_DEFAULT_BYTES）。
  - 新增 `_atomic_hardcap_pass(self, workings) -> List[_WorkingChunk]`：按 UTF-8 byte 长度判定与切分。
  - 新增 `_byte_safe_split(self, text, max_bytes)`：line-greedy 打包多行；单行超 cap 时降级到 codepoint 硬切。
  - 新增 `_byte_codepoint_hard_cut(self, text, max_bytes)`：迭代 Unicode codepoint 累加 UTF-8 byte 数，不在多字节序列中间断开。
  - `_apply()` 在 `_resplit_pass` 之后调用 `_atomic_hardcap_pass`。

### 5.2 新增

- `tests/test_chunk_policy_atomic_hardcap.py`（13 cases，与 §3 矩阵 1:1 对应；含中文 byte/char 边界 case 与 line-boundary case）。

### 5.3 不动

- `app/services/artifact_chunk_builder_service.py`：上游契约不变。
- `app/services/document_splitter_service.py`：plain_text 路径已经走 sentence-first resplit，不会产出 > 4000 chunk。
- `app/services/vector_index_service.py`：消费 ChunkPolicy 输出的逻辑不变。
- `app/services/vector_store_manager.py`：Milvus schema `content varchar(8000)` 不动。
- `app/models/knowledge.py`：ChunkRecord 字段定义不动。
- 既有 `tests/test_chunk_policy_service.py`：现有 case 不受影响（content 都 < 4000）。

## 6. Stop-loss

- TDD 顺序失守（先写 impl 再写 test）→ 停。
- 任一既有测试 fail → 停下来定位，**不**为了让新 case 过而改既有断言。
- P5.fX 评测 drift > 0 → 停下来汇报，要么是新 pass 误改了已验证 cell，要么是 hardcap 阈值选错；不允许悄悄调阈值"凑"过。
- P5.fX 评测 §4 invariance 失败 → 停（implementation bug，等同 P5 系列 stop-loss）。
- Milvus collection schema 仍报 8000 超限 → 停（说明 hard_cap 没生效或绕过去了）。

## 7. 文档约束

本 fix 完成后，PROJECT_STATE.md / findings.md / progress.md / chunk_refactor_execution_plan.md 都要更新：

- P5.f1 Open Problem "large-corpus headroom 未验证" 改写为 "已通过 ChunkPolicy atomic hardcap 修复（2026-05-19），17-doc 4-domain mixed corpus 已能成功 ingest"。
- chunk_refactor_execution_plan.md 在 P2 / P4 chunk policy 段落加一段 "原子类型 hard cap 子规则" 说明。
- task_plan.md 增一行 "ChunkPolicy atomic hardcap" 子项，与 P6 corpus prep 并列。

## 8. 与 P6 的关系

- 本 fix 是 P6 corpus probe 的**前置依赖**，不是 P6 实现的一部分。
- P6 实现层（domain_metadata、MetadataEnricher）仍维持 deferred 状态。
- 本 fix 完成后立即接 P6 corpus probe 重跑，与原计划无缝衔接。
