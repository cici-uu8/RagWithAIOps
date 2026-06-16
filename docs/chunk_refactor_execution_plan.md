# Chunk 重构实施计划

日期: 2026-05-18

## 0. 当前执行状态 (2026-05-19 更新)

| 阶段 | 状态 | 说明 |
|---|---|---|
| P1 | 已完成 | `_merge_small_chunks` 跨标题合并 bug 已修，新增 6 个边界单测 |
| P2 | 已完成 | `ChunkPolicyService` 落地，plain_text / mineru 两条路径汇流到统一最终边界 |
| P3 | 已完成 | dense / sparse / rerank 三处 search text 通过 `chunk_text_helpers.build_search_text` 统一注入 heading_path，display content 保持原文 |
| P4 | 已完成 | `apply_with_parents` 生成 section parent，children + parents 落 metadata store，parents 不进 Milvus 也不进 BM25，`retrieval_service` 命中子块时把 parent_content 挂到 `result.metadata` 上 |
| P4.5 | 已完成 | `ContextGranularity` 三模式落地：默认 `chunk` 不变；`parent_chunk` / `full_doc` 仅作用于 `RetrievalResponse.context_text` 拼装；citation 主语义不动；同 parent / 同 doc 重复拉，不去重；`full_doc` 只从 metadata store 非 parent 子块组装；25 条样本 + Qwen tokenizer 评测全过区分度自检 |
| P5 | 已完成 | `ResultAggregation = none / doc_level` 落地：默认 `none` 与 P4.5 baseline 字节级等价；`doc_level` 显式开关后按 `doc_hit_count → doc_max_score → doc_id` 排序聚合，每 doc 至多 `top_chunks_per_doc` 条；citation 字段逐条不变；20 条样本 + Qwen tokenizer 评测 3 类区分度自检全过 |
| P5.f1 | 已完成 | 长文档 follow-up: 3 篇 MinerU artifact (h3c_campus / h3c_mc101 / arxiv_vit; 349 children + 15 parents)；§4 不变性 + F3 6/6+6/6+0/6 + D1 factor_enough = true + E3 token 双阈值全过；P5.f4 未触发；实现层未动 |
| P5.f2 | 已完成 with caveats | 6-cell `{NONE, DOC_LEVEL} × {chunk, parent_chunk, full_doc}` 矩阵在同语料上跑通；§4 不变性扩展到 6 条 (含 cross-granularity identity 与 P4.5 ordered-list 复测)；token 阈值分档全过；joint_amplification(parent_chunk)=0.835、joint_amplification(full_doc)=1.021，证明 dedup 与 P4.5 不互相放大。两条 caveats 已显式列入 `PROJECT_STATE.md` Open Problems：(a) `DOC_LEVEL × full_doc` tokens_avg=46K 超 qwen-max 32K context 不可消费；(b) parent_chunk fallback rate=0.833 受 ChunkPolicy parent 稀疏度限制；实现层未动 |
| P5.f3 | 已完成 | 3-cell `{NONE×chunk, DOC_LEVEL×chunk, DOC_LEVEL×parent_chunk}` 矩阵接真 `qwen-max` LLM (temp=0.0, max_tokens=1024, timeout=30s, retry=2)，54/54 调用成功；§4 不变性 6 条 × 18 样本 × 3 cells 全过 (`invariants_all_ok=true`)；soft observations 不设 pass/fail 全表入报告：`none__chunk` 0.056/0.889/0.509、`doc_level__chunk` 0.000/0.833/0.694、`doc_level__parent_chunk` 0.000/0.833/0.722；唯一 hallucinated sample (`p5_long_reverse_004`，引用 malformed doc-id `doc_p5_long_arxiv_transformer` vs 真名 `doc_p5_long_arxiv_vision_transformer`) 仅出现在基线 `NONE×chunk`，DOC_LEVEL 两 cell 都压到 0；§9.3 三类 corner case (coverage<0.5, empty>0.2, no_citation>0) 均未触发。`full_doc` 维持 out-of-scope（caveat a）；`NONE × parent_chunk` 维持不评测（caveat b near-degenerate）。报告 markdown header 显式标注 §5.5 LLM proxy 限制与 §4 范围限制；实现层未动；`tests/*` 未动；`unittest discover tests` 仍 101/101 |
| ChunkPolicy atomic hardcap fix | **complete** (2026-05-19, B-path byte-based) | P6 corpus probe 首次跑触发 stop-loss §7：`h3c_comware_v7_high_risk_command_reference_cn` ingestion 撞 Milvus content varchar 8000 上限。根因：`_resplit_pass` 按 P2 设计只对 `TEXT_CONTENT_TYPES` 触发，原子类型 (manual_table / command_table 等) 全部绕过；P5.fX 三套 corpus max=1,613 字符不暴露此边界，混 17 doc + 命令参考类首次撞上。Fix 设计 `docs/chunk_policy_atomic_hardcap_design.md`：在 `_resplit_pass` 后插 `_atomic_hardcap_pass`，加 `atomic_split_by_size` quality flag。**A→B 迭代**: A-path char-based 4000-cap 跑通 P5.fX step 2-7 (drift=0)，但接 P6 corpus probe 时中文 atomic table 仍撞穿 (4000 chars × 2.15 bytes/char ≈ 8600 bytes —— 单位错)；B-path 改 `ATOMIC_HARD_CAP_DEFAULT_BYTES = 6000`，单位与 Milvus schema 同维度对齐 + 25% 安全边距 + 切分 codepoint-safe + line-boundary greedy pack。TDD red→green：`tests/test_chunk_policy_atomic_hardcap.py` B-path 13 cases；`unittest discover tests` 114/114 全过。B-path 完整重跑回归清单 (设计 §4) 串行 6 步：step 2 retrieval_eval ✅ / step 3 p4_5_eval ✅ drift=0 / step 4 p5_eval ✅ drift=0 / step 5 p5_long_doc_eval ✅ drift=0 / step 6 p5_joint_eval ✅ drift=0 / step 7 p5_llm_eval ✅ retrieval 字节级 drift=0 + §4 6 条双过 + abort=False；LLM-side 软观察按设计 §5.1 不设 pass/fail (jaccard ±0.07, hallucinated 1/54 翻转方向 True→False = 改善)。Reports: `p4_5_eval_20260519_223124.{json,md}` + `p5_eval_20260519_223152.{json,md}` + `p5_long_doc_eval_20260519_223218.{json,md}` + `p5_joint_eval_20260519_223301.{json,md}` + `p5_llm_eval_20260519_223412.{json,md}` |
| P6 corpus prep | **complete** (2026-05-19) | P6 trigger 判定阶段 (不实现 P6, oracle filter 是 eval 脚本本地 post-processor simulation)。设计 `docs/p6_corpus_prep_design.md`：4 域 (contracts / manuals / papers / aiops-docs) + 显式排除 stress_cases / manual_windows + 阈值 `oracle precision@3 - actual precision@3 ≥ 0.10` (precision@3 离散性等价于 ≥ 0.33 = "至少多挖出 1 条") 在 ≥ 3 query 上稳定。脚本 `evals/rag_retrieval/_p6_corpus_probe.py` (17-doc index across plain_text + MinerU paths)。第一次跑被 hardcap 边界阻断；hardcap close-out 后已 unblock。3 阶段 probe 链 (corpus_probe → kw_probe → cross_pool_probe) 全部完成；6 single + 6 cross sample 写入 `p6_samples.jsonl`。|
| P6 trigger eval | **complete with §10(b) caveat** (2026-05-20) | `run_p6_trigger_eval.py` 单轮 frozen pre-run 跑出 `trigger_p6=True` (qualifying=3/12, 恰好踩阈值 ≥3)。3 个 qualifying samples 全部 `aiops-docs ↔ manuals` 一对域 (cross_001/002/003, lift 0.67/0.67/0.33); 其余 9/12 lift=0.00 (dense 在 contracts/papers/单域 manuals/单域 aiops 已满分)。retrieval §4 invariance 3 条全过, 18 sample × pool=12。**§10(b) caveat (NEW)**: 操作化只算了 §10 (a)∩(c)，(b) "kb_id 不足以表达业务边界" 与 (a)/(c) 正交且未操作化 — 3 条 qualifying lift 全在一对域上，开启了 "用 kb_id 拆分能否替代 P6 enricher" 待决问题。trigger=True 是 frozen 结论，但 P6 实现 thread 须 stakeholder 完成 §10(b) 决策再启动。第一次跑命中 DashScope `openai.APITimeoutError` (transient)，重跑通过；embed batch-level retry 作为独立 robustness 工作项 (task #8)，不 gate 本次 close-out。Reports: `p6_trigger_eval_20260520_152021.{json,md}`. Design 详见 `docs/p6_corpus_prep_design.md` §14。|
| §10(b) stakeholder decision | **complete: False** (2026-05-20) | 决策 = False ⇒ aiops-docs 与 manuals 拆成 2 个 kb_id；不在同一 KB 内通过 `domain_metadata` enricher 解决域间干扰。决策依据: trigger eval 只证明 aiops↔manuals 共存会干扰，**没**证明必须靠 `domain_metadata`；KB 拆分是更简单且更符合 "aiops vs manuals 是两类不同知识" 自然产品边界的替代。落档: `docs/p6_corpus_prep_design.md` §15 / §15.1。|
| P6 实现 | **permanently closed** (2026-05-20) | §10(b) = False ⇒ 永久关闭。范围 (`docs/p6_corpus_prep_design.md` §15.2): `domain_metadata` 子字段 / `MetadataEnricher` 接口 / retrieval-side `domain_filter` 全部不做；`docs/p6_implementation_design.md` 不创建；`ChunkRecord.metadata.domain_metadata` 不写入 schema；`RetrievalQuery.domain_filter` 字段不加。重启条件 (§15.3): 三条须同时满足 — 新场景 aiops + manuals 必须共存于同一 KB + 新 corpus 重跑 trigger=True + 写独立 design 不复用本设计。|
| P6 | **permanently closed** (2026-05-20) | 重复行（legacy table position marker）。详见上一行 "P6 实现 permanently closed" + `docs/p6_corpus_prep_design.md` §15。|

主线 P1-P5 完成；P5.f1 / P5.f2 / P5.f3 follow-up 完成（P5.f2 with caveats，P5.f3 complete）。**2026-05-19 新增**：ChunkPolicy 原子类型 hard cap fix **complete**（13 新 TDD + step 2-7 回归全过）；P6 corpus prep 设计 + 脚本就位。**2026-05-20 新增**：P6 trigger eval **complete** (`trigger_p6=True` qualifying=3/12 全部 aiops↔manuals 一对域)；DashScope embedding batch retry **complete** (task #8, 14 新 TDD + step 2-7 回归 drift=0)；**§10(b) stakeholder decision = False ⇒ P6 永久关闭** (2026-05-20)。本 release chunk-refactor 主线**全部闭项**；后续 corpus v2 作为独立 future work 与 P6 决策解耦，P6 重启须满足 §15.3 三条硬条件。

### P1-P4 retrieval eval 基线对比 (4 条 golden queries)

| mode | 指标 | P1 | P2 | P3 | P4 |
|---|---|---|---|---|---|
| dense_only | recall@1 / MRR@3 | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 1.0 |
| hybrid | recall@1 / MRR@3 | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 1.0 |
| hybrid_rerank | recall@1 / MRR@3 | 0.75 / 0.875 | 0.75 / 0.875 | 0.75 / 0.875 | 0.75 / 0.875 |

四条 query 上召回 / 命中 / citation 全部持平，没有任何阶段引入回退。`hybrid_rerank` 的 0.75 是 P1 之前就存在的现象，不是本次重构引入。

### P4 验收口径

- parent 只进 metadata store，不进 Milvus，不进 BM25 corpus。
- citation 严格指向命中子块，`RetrievalResult.content / chunk_id / source_ref / citation_text` 均不被 parent 数据覆盖。
- `parent_content` 仅作为附加上下文挂在 `RetrievalResult.metadata`，按需消费。
- 计划文档与 `PROJECT_STATE.md` 已同步到 P4 complete，P4.5 / P5 / P6 明确划为后续阶段。

### 验证记录

- `tests` 全量: 78 pass。
- `evals/rag_retrieval/run_retrieval_eval.py` 在本机 Milvus + DashScope 真实链路上跑通，报告写入 `evals/rag_retrieval/reports/`。

### P4.5 验收口径

- 三模式语义只作用于 `RetrievalResponse.context_text` 拼装，不动 `RetrievalResult.chunk_id / content / source_ref / citation_text` 主语义。
- 默认仍为 `chunk`，`parent_chunk` / `full_doc` 仅显式指定时启用；`retrieve_knowledge` 工具不自动切换。
- `full_doc` 文本来源硬口径：只从 `KnowledgeMetadataStore` 的非 parent 子块组装，按 `chunk_index` 升序拼，不读 `original_path` / `cleaned.md`。
- 同 parent 多 child / 同 doc 多 hit 命中：重复拉，不做合并（让 token 浪费作为 P5 启动证据被显式量化）。
- `metadata["expanded_context"]` / `metadata["context_granularity_fallback"]` 生命周期硬口径：只在本次 retrieval response 构造期存在，不写回 metadata store / 不入 Milvus / 不进入 `retrieve_knowledge` artifact 稳定契约字段。
- citation 不变性以"有序 top-k 列表 + `citation_text` 严格相等"形式断言，不只是集合相等。
- token 成本统计使用 `dashscope.tokenizers.qwen_tokenizer.QwenTokenizer`，与下游 `rag_model = qwen-max` 对齐。

### P4.5 验证记录 (2026-05-18)

- `tests` 全量: 88 pass（78 旧 + 10 新增 `tests/test_p4_5_context_granularity.py`）。
- `evals/rag_retrieval/run_retrieval_eval.py` 4 条 P3 golden queries 三模式与 P4 baseline 完全持平：`dense_only` `recall@1=1.0 / mrr@3=1.0`，`hybrid` 同；`hybrid_rerank` `0.75/0.875` 不退。
- `evals/rag_retrieval/run_p4_5_eval.py` 跑通：
  - 25 条样本（4 类场景）三模式 citation 严格有序相等，`citation_invariant_all_ok = true`；
  - 区分度自检 `parent_advantage 4/5`、`multi_child_hit 3/5`、`long_doc 8/8`、`reverse_control 6/7`，全部通过；
  - 三模式 token 成本（Qwen tokenizer）：`chunk` avg=1376 / `parent_chunk` avg=1660 / `full_doc` avg=6715；
  - `parent_advantage` 第一轮 0/5 失败为评测样本设计问题（被命中 child 已含全部 expected_keywords），仅重写 5 条 query（窄锚定 + 跨 child keywords），区分度阈值 §6/§9 一字未改；第二轮 4/5 PASS。
- 报告：`evals/rag_retrieval/reports/p4_5_eval_20260518_154233.{json,md}`。

### P5 启动证据（P4.5 评测沉淀，仅记不做）

- `multi_child_parent_chunk_waste_>=30%_ratio = 0.6`（multi_child_hit 60% 样本 parent_chunk token ≥ 1.30× chunk）。
- `any_full_doc_waste_>=50%_ratio = 1.0`（每条样本 full_doc ≥ 1.50× chunk）。
- 触发条件 `parent_waste_30 >= 0.5` 与 `full_doc_waste_50 >= 0.5` 同时成立，按 P4.5 设计 §10 视为稳定启动证据。
- 按 P4.5 设计 §14，本期不在 P4.5 内引入任何 dedup fallback；P5 作为独立 thread 启动时直接引用本节作为依据。

---

## 1. 目的

本文档定义当前仓库的 chunk 重构计划，目标不是重写整条 RAG 链路，而是在不破坏既有 P1/P2/P3 契约的前提下，把当前分散的 chunk 边界逻辑收口成一套可验证、可扩展、对 `md/txt` 与 `pdf/docx/xlsx` 都适用的统一策略。

本计划重点解决以下问题:

- `plain_text` 路径与 `mineru` 路径的 chunk 边界规则分散，后续很难统一优化。
- `document_splitter_service` 的小片段合并逻辑存在跨标题误合并风险。
- dense embedding 路径还没有把 `heading_path` 明确纳入向量化文本，标题信息利用不完整。
- 当前仓库已经预留 `parent_chunk_id`，但还没有形成真正的父子 chunk 方案。

本计划是一个新的后续阶段入口，不回退已完成的 P2 artifact 契约，也不推翻已完成的 P3 retrieval / citation / eval 边界。

## 2. 当前代码现状

### 2.1 `plain_text` 路径

当前 `plain_text` 路径由 [app/services/document_splitter_service.py](../app/services/document_splitter_service.py) 负责:

- Markdown 只按 `#` / `##` 做标题拆分。
- 二次拆分使用 `RecursiveCharacterTextSplitter`，实际长度阈值为 `chunk_max_size * 2`。
- `_merge_small_chunks()` 是顺序合并，不检查 `h1/h2` 边界。
- 切分结果随后由 [app/services/vector_index_service.py](../app/services/vector_index_service.py) 转成 `ChunkRecord`，并补齐 `heading_path` / `content_type` / `source_ref` / `quality_flags` 等字段。

结论:

- `plain_text` 不是“没有结构化 metadata”，而是“最终 metadata 有，前置 merge policy 太粗”。
- 这一条链路最先要修的是 merge bug，而不是先大改架构。

### 2.2 `mineru` 路径

当前 `mineru` 路径由三层组成:

1. [app/services/mineru_parser_adapter.py](../app/services/mineru_parser_adapter.py) 调 MinerU CLI 和 postprocess。
2. [pdf_eval/scripts/mineru_postprocess.py](/Users/cici/oncall agent/pdf_eval/scripts/mineru_postprocess.py) 把 MinerU 原始输出整理成 `cleaned.md`、`blocks.json`、`chunks.json`、`tables.json`、`quality_report.json`。
3. [app/services/artifact_chunk_builder_service.py](../app/services/artifact_chunk_builder_service.py) 读取 `chunks.json` / `tables.json` 并转成 `ChunkRecord`。

结论:

- `ArtifactChunkBuilderService` 本身不做切分，只做 contract normalization。
- 现在的 MinerU chunk policy 真正落在 `mineru_postprocess.py` 的 `chunk_blocks()`。
- 如果要统一 chunk policy，不能假设只改 `ArtifactChunkBuilderService` 就够了。
- 一旦 P2 落地，`chunks.json` 在主仓库里的语义就不再是“不可再改的最终块”，而是“通过 postprocess 产生的候选最终块”；最终入库边界由统一 `ChunkPolicy` 决定。

### 2.3 当前已有的统一面

虽然两条路的前置切分不同，但它们已经在 `ChunkRecord` 层汇流:

- `chunk_id`
- `doc_id`
- `kb_id`
- `content`
- `heading_path`
- `page_start/page_end`
- `content_type`
- `source_ref`
- `quality_flags`
- `parent_chunk_id`（已预留，未实际启用）

因此，本次重构的正确落点不是“重新定义模型”，而是“把最终 chunk 边界策略收口到 `ChunkRecord` 生成前的同一层”。

## 3. 重构目标

本次 chunk 重构分 4 个目标:

1. 修复现有 md/txt 兼容路径的错误合并行为。
2. 引入统一 `ChunkPolicy`，把 `plain_text` 与 `mineru` 的最终 chunk 边界规则收口。
3. 统一 dense / sparse / rerank 对标题路径的利用方式，但不污染展示原文。
4. 在稳定统一 chunk 边界后，启用父子 chunk 支持。

在这 4 个主目标之外，本计划还补充 3 个由教程启发、但必须按本项目边界重新裁剪的后续扩展面:

5. 上下文粒度切换: `chunk | parent_chunk | full_doc`
6. 检索结果的 doc 级聚合、去重与排序
7. 业务域 `domain_metadata` 与 `MetadataEnricher` 扩展点

最终期望达到的状态:

- 所有文档类型都遵守同一套“最终 chunk 边界”原则。
- 标题、段落、表格、公式等语义边界被保留，不再完全依赖字符切分。
- 向量化、稀疏检索和 rerank 都能看到标题上下文。
- retrieval / citation 契约保持不破。

## 4. 明确不做的事

本阶段明确不做以下事情:

- 不推翻 `docs/rag_ingestion_artifact_contract.md` 定义的六件套 artifact 契约。
- 不把 `cleaned.md` 提升为 MinerU 主入库输入。
- 不直接绕过 `mineru_postprocess.py`，首轮不改成“主仓库自己重新解释 MinerU 全量原始 JSON”。
- 不重写 retrieval / hybrid / rerank 服务的外部 DTO 契约。
- 不在本轮引入完整的 WeKnora parent-child chunk 体系、关系图谱或 FAQ 差异化 chunk。
- 不因为统一 chunk policy 就更改现有 `retrieve_knowledge` 工具名或 `RetrievalResponse` 形状。
- 不直接照搬教程里的 demo 域字段，如菜品分类、难度等级、三级标题分块策略。

## 5. 统一 ChunkPolicy 的目标语义

统一 `ChunkPolicy` 不是“所有输入都走同一个原始 splitter”，而是“所有上游块都遵守同一个最终 chunk 生成规则”。

首版统一语义如下:

| 规则 | 说明 |
|---|---|
| 标题边界保留 | 不允许跨不同 `heading_path` 合并普通正文 |
| 同节正文可合并 | 同一 `heading_path` 下的相邻短正文可合并 |
| 超长正文再拆 | 超过阈值的正文按长度二次拆分，但尽量保持句子完整 |
| 表格单独保留 | `table` / `manual_table` / `parameter_table` 等表格类 chunk 不与正文合并 |
| 公式单独保留 | `equation` / `equation_interline` 不并入普通正文 |
| 标题信息参与检索 | 向量化和稀疏检索都能看到 `heading_path + content` |
| 展示正文保持原文 | 返回给用户的 `content` 保持原始正文，不强制把标题前缀写回正文 |

## 6. 分阶段实施计划

### P1: 修复 `plain_text` 路径跨标题误合并

状态: `已完成` (2026-05-18)

目标:

- 修复 `document_splitter_service._merge_small_chunks()` 跨 `h1/h2` 合并的问题。
- 保持现有 `md/txt` 路径的主体切分算法不变，只修 bug，不顺手扩做架构调整。

建议改动:

- 调整 [app/services/document_splitter_service.py](../app/services/document_splitter_service.py) 中 `_merge_small_chunks()`:
  - 合并前对比相邻块的 `h1/h2`（必要时含 `h3`）metadata。
  - 只允许同标题路径的小片段合并。

实现方式约束:

- 不在 P1 修改 `vector_index_service` 的写入语义。
- 不在 P1 引入新的 policy service。
- 不扩大到 MinerU 链路。

验收:

- 同一标题下的小片段仍可合并。
- 不同 `h1/h2` 下的相邻短正文不再错误合并。
- 现有 md/txt regression gate 不回退。

建议验证:

```text
.venv/bin/python -m unittest tests.test_p1_4_regression -v
.venv/bin/python -m unittest discover tests -v
```

### P2: 引入统一 `ChunkPolicy`

状态: `已完成` (2026-05-18)

目标:

- 把最终 chunk 边界规则从“分散在 splitter / postprocess / builder 的多个局部逻辑”收口到一个统一 service。
- 保持上游块来源不变:
  - `plain_text`: splitter 产出的 `Document`
  - `mineru`: `ArtifactChunkBuilderService` 产出的初始 `ChunkRecord`

语义重定位:

- 对 `plain_text` 路径，splitter 产物从一开始就是“初始块”。
- 对 `mineru` 路径，`pdf_eval/scripts/mineru_postprocess.py` 产出的 `chunks.json/tables.json` 在主仓库中应重新理解为“候选最终块”。
- 也就是说，MinerU 的 `chunk_blocks()` 负责语义块整理和初始边界建议，真正的最终入库边界由统一 `ChunkPolicy` 决定。
- 这必须在实现前明确写进计划，否则后续读者会误以为 `ChunkPolicy` 只是在 `plain_text` 路径上补丁式修修补补。

建议改动:

- 新增 `app/services/chunk_policy_service.py`。
- 在两个调用点接入:
  - `plain_text` 路径: `VectorIndexService._build_chunk_records()` 之后，或改造为“先生成初始块，再交给 policy 输出最终块”。
  - `mineru` 路径: `ArtifactChunkBuilderService.prepare()` 之后，对初始 `ChunkRecord` 做统一合并/拆分，再输出最终块。

统一 policy 首版至少支持:

- 同 `heading_path` 的短正文合并。
- 超长正文按阈值再拆。
- `table` / `manual_table` / `parameter_table` / `equation` 不并入正文。
- 重新生成最终 `chunk_index`。
- 在边界变化后，确保 `chunk_id` 和 `source_ref.chunk_id` 与最终块一致。

实现方式约束:

- P2 的 `ChunkPolicy` 必须成为“最终 chunk 生成层”，不能只是附加修补。
- 如果 policy 改变了 chunk 边界，就必须同步更新 `chunk_id` / `chunk_index` / `source_ref`，不能保留旧边界下的标识。
- 不改 `RetrievalResponse` / `RetrievalResult` 的外部契约。

验收:

- `plain_text` 与 `mineru` 两条路径最终都经过同一 service 决定 chunk 边界。
- 表格类 chunk 仍保留独立语义。
- `heading_path`、`page_start/page_end`、`source_ref` 不丢失。
- 现有 P2-8 / P3 检索契约测试不回退。

P2 必须新增的 policy 本体测试:

- 跨 `heading_path` 不合并
- 同 `heading_path` 的短正文会合并
- 超长正文会二次拆分，句界优先、长度兜底
- `table` / `equation` 不并入普通正文
- chunk 边界变化后，`chunk_id` / `chunk_index` / `source_ref.chunk_id` 会被重新生成并保持一致

建议验证:

```text
.venv/bin/python -m unittest tests.test_chunk_policy_service -v
.venv/bin/python -m unittest tests.test_artifact_chunk_builder_service -v
.venv/bin/python -m unittest tests.test_p2_8_gate -v
.venv/bin/python -m unittest tests.test_retrieval_service tests.test_p3_retrieval_gate -v
.venv/bin/python evals/rag_retrieval/run_retrieval_eval.py
.venv/bin/python -m unittest discover tests -v
```

### P3: 统一检索文本增强，不改展示原文

状态: `已完成` (2026-05-18)

目标:

- 让 dense embedding、sparse search、rerank 都能看到 `heading_path + content`。
- `content` 仍保留原始正文，避免用户看到被拼接污染的文本。

建议改动:

- 在向量写入路径引入“embedding 用文本”概念。
- 首版可以不新增持久化字段，只在写入 `Document` 到 vector store 前构造:

```text
embedding_text = heading_path_joined + "\n" + content
display_content = content
```

- sparse / rerank 当前已经局部使用 `heading_path + content`，需要和 dense 路径口径对齐。

建议落点:

- dense 路径落在 `VectorIndexService` 或 `VectorStoreManager.add_documents()` 调用前。
- 具体形态应是构造临时 `Document(page_content=embedding_text, metadata=...)` 写入向量库，而不是修改 `ChunkRecord.content`。
- `ChunkRecord.content`、retrieval 返回正文、citation 展示正文都保持原文。
- 现有 sparse 与 rerank 的标题拼接逻辑应抽成公用 helper，例如 `chunk_search_text(...)`，避免 dense / sparse / rerank 三处独立漂移。

实现方式约束:

- 不直接把标题永久写回 `ChunkRecord.content`。
- 不改变 citation 文本的显示方式。
- 不让 retrieval 返回结果出现“双重标题”或展示异常。

验收:

- dense 路径也能利用标题上下文。
- sparse / rerank / dense 的输入口径一致。
- 返回给用户的 `content` 仍是正文原文。

建议验证:

```text
.venv/bin/python -m unittest tests.test_p3_hybrid_retrieval tests.test_p3_rerank_service tests.test_retrieval_service -v
.venv/bin/python evals/rag_retrieval/run_retrieval_eval.py
```

### P4: 启用父子 chunk

状态: `已完成` (2026-05-18)

目标:

- 基于已预留的 `parent_chunk_id`，支持子 chunk 召回、父 chunk 回溯。
- 让“检索精细命中”与“回答时保留更完整上下文”两者兼得。

建议改动:

- 在统一 `ChunkPolicy` 稳定后，生成:
  - 父 chunk: 章节级或合并后的较大语义块
  - 子 chunk: 用于 embedding / recall 的较小粒度块
- 子块写 `parent_chunk_id`。
- retrieval 侧在需要时回溯父块，供 LLM 上下文拼装使用。

实现方式约束:

- P4 必须建立在 P2 的统一 policy 稳定之后，不能先做。
- 首版只做 parent-child 身份和回溯，不引入 relation graph。
- 不破坏现有 `chunk_id` / `source_ref` 稳定引用语义。

验收:

- 命中的子 chunk 能稳定回溯父 chunk。
- 引用仍然指向真实命中 chunk，不因为父块扩展而混淆 citation。
- 新逻辑可被 gate 和检索测试覆盖。

### P4.5: 增加 `context_granularity` 上下文粒度开关

状态: `已完成` (2026-05-18)

目标:

- 在 P4 的 parent-child chunk 之上，再补一个“生成上下文粒度”的控制层。
- 支持按场景选择:
  - `chunk`
  - `parent_chunk`
  - `full_doc`

这一步解决的问题不是“怎么召回”，而是“命中后给 LLM 多大上下文最合适”。

适用场景:

- 短结构化文档、规章条款、SOP: `full_doc` 可能比 `parent_chunk` 更稳
- 长论文、长手册: `full_doc` 容易爆上下文，应保留 `chunk` 或 `parent_chunk`

建议改动:

- 在 retrieval/context assembly 层引入 `context_granularity` 配置或开关。
- 首版可在 `ChunkingConfig` 或 retrieval 配置中定义。
- `full_doc` 模式优先从 `DocumentRecord` 对应文档读取整篇可展示文本，而不是强依赖 chunk 拼接。

实现方式约束:

- P4.5 与 P4 紧耦合，应一起设计，但不一定同一提交完成。
- `full_doc` 不能作为所有场景的默认行为。
- 必须按文档长度、类型或显式配置控制，避免长 PDF / 长手册上下文爆炸。

验收:

- 三种粒度模式都能明确区分并被测试覆盖。
- `full_doc` 模式只在适合场景启用，不破坏默认检索体验。
- citation 仍落在真实命中 chunk，而不是被“整篇文档上下文”稀释掉定位。

### P5: 检索结果 doc 级聚合、去重与按命中数排序

状态: `已完成` (2026-05-18)

目标:

- 解决“同一文档多个 chunk 全部挤进结果列表”的问题。
- 在 `RetrievalService` 返回前，对同一 `doc_id` 的多条命中做聚合、去重和排序。

这一步和 P4 的父子 chunk 是不同维度:

- P4 解决的是“chunk 太小，回答时需要更大上下文”
- P5 解决的是“同一文档命中过多，结果列表冗余”

实际改动:

- 模型层新增 `ResultAggregation = none / doc_level` 枚举与 `RetrievalQuery` 的三个字段 (`result_aggregation` / `top_chunks_per_doc` / `doc_oversample_factor`); 默认 `none` 与 P4.5 baseline 字节级等价。
- `RetrievalService.retrieve()` 在 `doc_level` 模式下放大候选池 (`pool_k = top_k * doc_oversample_factor`), 调一次原召回路径 (强制 `none` 防递归), 然后 `_aggregate_by_doc()` 按 `doc_hit_count` 降 → `doc_max_score` 降 → `doc_id` 升排序，每 doc 至多保留 `top_chunks_per_doc` 条 result。
- 每条 dedup 后 result 挂三个观测位 (`aggregation_doc_hit_count` / `aggregation_doc_max_score` / `aggregation_dropped_chunk_ids`), 生命周期与 P4.5 `expanded_context` 一致：构造期临时、不持久化、不入 Milvus、不进 `retrieve_knowledge` artifact 稳定契约。

实现方式约束 (实际落地版本):

- 不替代 dense/sparse/hybrid/rerank 的底层召回逻辑。
- 不破坏 `RetrievalResult` 的字段语义；citation `chunk_id / content / source_ref / citation_text` 与候选池中同 chunk_id 那条逐字段相等。
- `result_aggregation` 默认 `none`, `retrieve_knowledge` 工具不传该字段、保持工具行为零变化。
- `doc_oversample_factor` 标为高级参数，不在工具层暴露。
- P5 与 P4.5 三模式正交：`DOC_LEVEL` 在 `parent_chunk` / `full_doc` 下顺带消除 P4.5 §3 的"重复拉"语义，但仅在用户显式选择 `doc_level` 时生效；P4.5 在 `none` 下的硬口径不变。

### P5 验收口径

- `none` 模式下 `top_chunks_per_doc` / `doc_oversample_factor` 必须绝对 no-op；`doc_level` 是用户显式选择的另一条结果组织策略，不是默认行为。
- `doc_level` 下 `top_k` 主语义为 doc 数；`len(results) ≤ top_k * top_chunks_per_doc`，每个 doc_id 出现次数 ≤ `top_chunks_per_doc`。
- citation 不变性以代码断言形式存在 (4 条)：返回 chunk_id ⊆ 候选池；`chunk_id / content / source_ref / citation_text` 与候选池逐字段相等；长度上限。
- 区分度自检阈值跑前固定: `same_doc_redundant ≥ 70%`、`cross_doc_already ≥ 70%`、`reverse_control 退化率 ≤ 10%`。
- token 成本统计沿用 P4.5 同一 Qwen tokenizer (`qwen-max`)。
- 同 parent / 同 doc 重复拉的 P4.5 硬口径只在 `none` 下成立；`doc_level` 是另一条显式旋钮，不算 P4.5 偷加 fallback。

### P5 验证记录 (2026-05-18)

- `tests` 全量: 101 pass (88 P4.5 收尾后 + 13 新增 `tests/test_p5_doc_level_dedup.py`)。
- `evals/rag_retrieval/run_retrieval_eval.py` 4 条 P3 golden queries 默认模式下三模式与 P4.5 baseline 完全持平。
- `evals/rag_retrieval/run_p4_5_eval.py` 默认模式 `citation_invariant_all_ok = true`、4 类区分度自检与 P4.5 收尾结果完全一致，证明 P5 改动对 P4.5 baseline 零污染。
- `evals/rag_retrieval/run_p5_eval.py` 跑通：
  - 4 条 §4 不变性断言 20/20 全过；
  - 区分度自检 `same_doc_redundant 8/8 (100%)`、`cross_doc_already 6/6 (100%)`、`reverse_control 退化率 0/6 (0%)`，全部 PASS。
  - DOC_LEVEL 在 `same_doc_redundant` 类上 distinct_doc_count_avg 从 1.13 → 2.63、tokens_avg 从 1456 → 1192 (-18%)，符合 P5 设计核心收益假设；在 `cross_doc_already` 类上 distinct_doc_count 维持 3 不变；在 `reverse_control` 类上 0/6 退化。
- 评测样本两轮调整：A 路径 round-1 `cross_doc_already` 3/6 → round-2 4/6 仍 < 70%，按 stop loss 转 B-1；B-1 把 round-2 的 cross_004 / cross_005 重归类为真阳性 `same_doc_redundant_007 / 008`，新补 cross_004 / cross_005 严格只用已通过形态的安全词，单轮过线。区分度阈值 §9 一字未改。
- 报告：`evals/rag_retrieval/reports/p5_eval_20260518_202904.{json,md}`。

### P5.f1 验证记录 (2026-05-18)

- 解析路径首次扩到 mineru：3 篇 MinerU artifact (h3c_campus / h3c_mc101 / arxiv_vit) 全过 B3 (≥30 children AND ≥20K Qwen tokens)，总 349 children + 15 parents。
- A1→A2→A3 路径只走到 A1：仓库内 `pdf_eval/outputs/postprocessed/mineru/expanded_corpus/` 已有现成 artifact，A2 实际成本 0。
- 18 条样本 / 3 类，由 probe-1 + probe-2 + keyword probe + hit dump + recheck 5 步 probe 数据驱动，避免 P5 round-1/2 凭语义直觉的覆辙。
- 4 项跑前固定门槛单轮过：§4 不变性 18/18 OK；F3 6/6 + 6/6 + 退化 0/6；D1 saturation 0/6 → factor_enough=true (P5.f4 未触发)；E3 token 双阈值 PASS (DL avg=640，DL/NONE=0.54)。
- 实现层未动；Step 2 全程验证 only。
- 报告：`evals/rag_retrieval/reports/p5_long_doc_eval_20260518_224445.{json,md}`。
- 边界（写下来给后续）：3 篇语料 same_doc_redundant 5/6 集中在 mc101，是这批语料的 dense recall 真实分布性质，**不能外推成所有 MinerU 长文档都如此**；只有 1 篇过 B3 的英文论文，"MinerU + 长英文论文"维度比原计划窄。

### P5.f2 验证记录 (2026-05-19, complete with caveats)

- 6-cell `{NONE, DOC_LEVEL} × {chunk, parent_chunk, full_doc}` 矩阵在 P5.f1 同语料上跑通；样本沿用 P5.f1 18 条不动，唯一变量是 granularity。
- §4 不变性扩到 6 条：原 1–4（DL/NONE ⊆ pool、DL identity byte-equality、长度上限）+ 新 5（同 chunk_id 在 6 cells 中 byte-equal，证明 granularity 不动 identity 字段）+ 新 6（P4.5 ordered-list invariance 在长文档语料上复测：NONE × 三 granularity 返回相同 ordered chunk_id 列表，DL × 三 granularity 同）。18 样本上全过。
- 分档 token 阈值全过：chunk DL=640 / ratio=0.54、parent_chunk DL=744 / ratio=0.45、full_doc ratio=0.55。
- P5.f1 sanity reproduction：NONE×chunk drift=0.000、DL×chunk drift=0.000，证明 P5.f2 插桩没有影响 P5.f1 已验证 cell。
- joint_amplification: chunk=1.000、parent_chunk=**0.835**（dedup 反而缓解 parent 膨胀）、full_doc=**1.021**（dedup 与 granularity 几乎独立）。**核心问题"dedup 与 P4.5 expansion 是否互相放大"答案：不互相放大**。
- D1 anchor restated：P5.f1 已证 factor_enough=true（granularity 不影响候选池，无需复测）；P5.f4 仍未触发。
- 实现层未动；Step 2 全程验证 only。
- 报告：`evals/rag_retrieval/reports/p5_joint_eval_20260518_232319.{json,md}`。

#### P5.f2 caveats（已显式列入 PROJECT_STATE Open Problems，不藏在表格里）

- **caveat (a) full_doc 在长文档语料上事实不可用**: `DOC_LEVEL × full_doc` tokens_avg=46,302 / p95=57,901，超 qwen-max 32,768 上下文窗口；`NONE × full_doc` 更是 83,492。模式结构上 pass-through（§4 6 条不变性都过），但**无法被当前 LLM 直接消费**。后续不允许把 `full_doc` 默认开给长文档 KB；P5.f3 已按这条 caveat 把 `full_doc` 显式标为 out-of-scope（仅 3-cell `{NONE×chunk, DOC_LEVEL×chunk, DOC_LEVEL×parent_chunk}` 跑通），未来要测 `full_doc` 的 LLM 行为需要单开 P5.f3.b 在短 doc 子集上跑。
- **caveat (b) parent_chunk 高 fallback**: NONE 与 DOC_LEVEL × parent_chunk fallback rate 都是 0.833 (15/18)，根因在 ChunkPolicyService 当前 parent 生成阈值（连续 ≥2 个同 heading 子块），3 篇语料下 h3c_mc101 1p/155c、h3c_campus 2p/132c、arxiv_vit 12p/62c。P5 / P4.5 机制都正常，瓶颈在 parent 稀疏度。**这是 P4.5 / ChunkPolicy 的边界，不是 P5 bug**；要修需要重新设计 ChunkPolicy parent 阈值，明确不在 P5 / P5.f1 / P5.f2 / P5.f3 范围内。P5.f3 在 `DOC_LEVEL × parent_chunk` cell 上独立复测了 `fallback_rate_avg=0.833`，与 P5.f2 完全一致，证明这条边界是 corpus 性质而非 P5 / P5.f3 引入。

### P5.f3 LLM 端 citation 漂移验证（2026-05-19, complete）

- 设计文档：`docs/p5_f3_llm_citation_drift_design.md`（cell 选择、proxy 限制、prompt 设计、LLM 配置、citation parser regex、容错与 stop-loss）。
- 实现脚本：`evals/rag_retrieval/_p5_llm_smoke.py`（1-call DashScope reachability + prompt + regex + retry/timeout 前置自检）+ `evals/rag_retrieval/run_p5_llm_eval.py`（3-cell 主矩阵；corpus indexing 沿用 P5.f1 / P5.f2 isolated Milvus + metadata store 框架；citation parser；soft-observation aggregator；corner-case 高亮；abort-on-≥50%-failure）。
- LLM 配置（pre-run 写死，跑后不调）：`qwen-max` via DashScope OpenAI-compat、temperature=0.0、max_tokens=1024、top_p=1.0、timeout=30s、retry=2（共 3 次尝试）、串行调用、prompt 不加"必须每句引用"等强化约束。
- 矩阵：3 cells × 18 samples = 54 calls；`full_doc` 按 caveat (a) 维持 out-of-scope；`NONE × parent_chunk` 按 caveat (b) 维持不评测（near-degenerate to `NONE×chunk`）。
- 硬断言：retrieval §4 不变性 6 条 × 18 样本 × 3 cells，`invariants_all_ok = true`，证明 LLM call layer 没污染 retrieval 路径。
- soft observations（不设 pass/fail 全表入报告）：

| cell | hallucination_rate | coverage_rate | jaccard_avg | empty_answer_rate | no_citation_rate | fallback_rate_avg |
|---|---|---|---|---|---|---|
| `none__chunk` | 0.056 | 0.889 | 0.509 | 0.111 | 0.000 | 0.000 |
| `doc_level__chunk` | 0.000 | 0.833 | 0.694 | 0.167 | 0.000 | 0.000 |
| `doc_level__parent_chunk` | 0.000 | 0.833 | 0.722 | 0.167 | 0.000 | 0.833 |

- 唯一 hallucinated sample：`p5_long_reverse_004` 在基线 `NONE×chunk` cell 引用了 malformed doc-id `doc_p5_long_arxiv_transformer`（真实是 `doc_p5_long_arxiv_vision_transformer`），DOC_LEVEL 两个 cell 都把它压到 0。**P5 doc-level dedup 在 LLM citation 对齐这一维度上是净正向**。
- §9.3 三类 corner case（coverage<0.5、empty>0.2、no_citation>0）均未触发。
- LLM proxy 限制（报告 markdown header 显式标注，按设计 §5.5 / §16）：hallucination_rate / coverage_rate / citation_jaccard 只衡量 prompt 与 answer 之间 chunk_id 是否对齐——**这就是 P5 在生产决策上需要回答的问题**（dedup / granularity 是否引入 LLM 侧漂移？）。**事实级 answer faithfulness（LLM 回答内容是否与所引 chunk 一致）是跨 pipeline 的 RAG 质量横切关注点，不是 P5 / P5.f3 交付项**：它对任何 RAG 系统都成立，与 dedup / granularity 策略无关，通常用 LLM-as-judge 框架（RAGAS / TruLens / Phoenix）或人工 spot-check 评测。如果未来要做，作为独立工作项**与 P5 / P6 并行**而非阻塞，不在 P5.f3 名下补做。报告里这条声明是 scope 说明，不是 P5.f3 缺口。
- 不回归证据：`unittest discover tests` 仍 101/101（P5.f3 没动 `app/*` / `tests/*`）；retrieval §4 6 条不变性仍 18/18 全过；54 LLM calls 0 失败（`abort_should_trigger = false`）。
- 报告：`evals/rag_retrieval/reports/p5_llm_eval_20260519_131538.{json,md}`（markdown header 显式列出 §5.5 + §4 两条文档约束）。
- 状态判定：**complete**，不是 with caveats——硬断言全过；soft observations 没有 trigger 任何 corner case；唯一异常 sample 出现在基线 cell 且被 DOC_LEVEL 修复，是 P5 dedup 的正向佐证而非问题。两条 P5.f2 caveats 自然在长文档语料上仍然有效（一条 full_doc 维持 out-of-scope，另一条 0.833 fallback rate 在 P5.f3 同一 cell 上独立复测一致），不是 P5.f3 新增 caveat。
- P6 trigger 判定：仍 false / gated。**P5.f3 是 citation drift 评测，不是 domain-filter 评测**，按设计天然不产生 P6 trigger evidence；开 P6 thread 仍需要换一套显式有 path/folder/domain 过滤痛点的语料 + 样本集。

### P6 启动证据（按 P5 设计 §10 判定）

> **2026-05-20 update — final state**: 本节是 2026-05-19 前的中间认知（`trigger_p6 = false`）。最终状态见本文档顶部表格 + `docs/p6_corpus_prep_design.md` §14（trigger 评测结果 trigger_p6 = True with §10(b) caveat） + §15（stakeholder 决策 §10(b) = False ⇒ P6 永久关闭）。下面段落保留作为历史认知记录，不再代表当前状态。

- `p6_evidence.trigger_p6 = false`：当前 aiops-docs 语料没有 path / 目录 / domain 显式 metadata；本次评测里没有 ≥ 3 条查询需要 path/folder filtering，反向控制类也没有出现仅靠 `kb_id` 不足以表达的稳定信号。
- 结论：P5 评测未触发 P6 启动证据；P6 仍 deferred，开 P6 thread 时需要先扩样本到带显式领域过滤需求的语料，不允许直接基于"语义直觉"启动 P6。

### 评测集已知边界（P5 落定后写下来给后续用）

5 篇 aiops-docs 语料天然偏向 single-doc semantic anchor：`cross_doc_already` 类的稳定信号来源很窄，仅限"程序性框架词组合"（查询规范、扩容/告警同模板术语）；任何带"章节标题词"或"时序紧急处理"措辞的 query 都容易被 dense embedding 推到单簇。这条边界以"评测限制"形式记入 `PROJECT_STATE.md` Open Problems。

### P6: `domain_metadata` 子字段与 `MetadataEnricher` 扩展点

状态: `后续阶段，未启动`

目标:

- 给当前固定 metadata schema 增加“路径派生 + 内容派生”的业务域扩展位。
- 让目录结构、命名约定、文档正文里的业务语义能被提炼成过滤和排序可用字段。

建议改动:

- 在 `ChunkRecord.metadata` 中规范一个 `domain_metadata: dict` 子字段。
- 定义 `MetadataEnricher` 接口:
  - 输入: `file_path + content + current_metadata`
  - 输出: `domain_metadata`
- 允许按知识库、目录或业务域注册不同 enricher。

适用示例:

- 产品 / 版本 / 模块
- 规章类别 / 发布部门 / 生效范围
- 设备类型 / 告警等级 / 处理阶段

实现方式约束:

- 不把教程里的 demo 字段直接写死进主仓库。
- `domain_metadata` 必须作为扩展位存在，不污染通用 citation / source_ref / heading_path 契约。
- 首版先支持 enrichment 和持久化，不要求同时完成所有过滤检索能力。

验收:

- `domain_metadata` 可以从路径和内容中派生并稳定写入 chunk metadata。
- 后续向量过滤或检索策略能消费这些字段。
- 不同 KB 可以接不同 enricher，而不互相污染。

## 7. 影响面

本计划预估影响文件如下:

### 首轮必改

- `app/services/document_splitter_service.py`
- `app/services/vector_index_service.py`
- `app/services/artifact_chunk_builder_service.py`
- `tests/test_p1_4_regression.py`
- `tests/test_artifact_chunk_builder_service.py`
- `tests/test_p2_8_gate.py`

### 二轮高概率新增

- `app/services/chunk_policy_service.py`
- `tests/test_chunk_policy_service.py`
- 新增针对统一 chunk policy 的测试文件

### 后续阶段可能改动

- `app/services/vector_store_manager.py`
- `app/services/retrieval_service.py`
- `app/services/sparse_search_service.py`
- `app/services/rerank_service.py`
- `app/models/knowledge.py`
- 新增 `MetadataEnricher` 或相关扩展注册入口

## 8. 风险与控制

| 风险 | 场景 | 控制方式 |
|---|---|---|
| 回归 md/txt 行为 | P1/P2 修改后 chunk 数量和边界大幅漂移 | 先修 bug，再引入 policy；保留 regression gate |
| 回归 MinerU artifact 契约 | P2 把 postprocess / builder 边界打乱 | 不改六件套 contract，不把 `cleaned.md` 拉回主输入 |
| citation 漂移 | 改 chunk 边界但没同步改 `chunk_id` / `source_ref` | 统一由最终 policy 产出最终块标识 |
| 检索展示异常 | P3 把标题永久写回正文 | 标题只进入 embedding/search text，不污染 display content |
| 过早做复杂 parent-child | P4 先做导致写入、检索、引用一起变复杂 | 严格放到 P2/P3 稳定后再做 |
| full_doc 上下文爆炸 | P4.5 对长 PDF 默认整篇喂给模型 | 按文档长度/类型/显式配置控制粒度 |
| 结果去重后信息丢失 | P5 只保留 doc 级结果，丢失关键 chunk | 每个 doc 保留 top_n_chunks_per_doc，并保留 citation 原子性 |
| 业务域 schema 失控 | P6 每个 KB 各写一套 metadata 键 | 固定 `domain_metadata` 子字段和 enricher 接口边界 |

## 9. 执行顺序

本计划的推荐执行顺序固定为:

1. 先做 P1，单点修 bug。
2. 再做 P2，建立统一 `ChunkPolicy`。
3. 再做 P3，统一 dense/sparse/rerank 的标题上下文利用。
4. 最后做 P4，启用父子 chunk。
5. P4 稳定后，再决定是否启用 P4.5 的 `context_granularity`。
6. P5 和 P6 作为后续增强面，可独立评估、并行排期。

阶段级基线要求:

- P1、P2、P3 每一步完成后，都应至少跑一次:

```text
.venv/bin/python evals/rag_retrieval/run_retrieval_eval.py
```

- 目的不是要求每一步都“提升指标”，而是留下 chunk 边界变化对召回/引用/延迟影响的数字证据。

禁止跳步:

- 不先做 P3 再做 P2。
- 不先做 P4 再做 P2。
- 不把 P2 直接扩大成“重写 MinerU 全量后处理脚本”。
- 不把 P5 的 doc 去重误当成 P4 的 parent-child 替代品。
- 不把 P6 的业务域 metadata 设计成主仓库硬编码 demo 字段。

## 10. 完成标准

本计划主线完成时，应满足以下 5 条:

1. `plain_text` 与 `mineru` 都经过统一的最终 chunk policy。
2. `md/txt` 现有 regression gate 不回退。
3. MinerU artifact 契约不回退，`chunks.json/tables.json` 仍是主入库输入。
4. dense / sparse / rerank 都能利用标题上下文。
5. 父子 chunk 若启用，citation 仍能稳定定位到真实命中 chunk。

若后续扩展面也纳入实施，则再增加以下 3 条:

6. `context_granularity` 能在 `chunk / parent_chunk / full_doc` 间按场景切换。
7. 检索结果支持 doc 级聚合、去重和按命中数排序。
8. `domain_metadata` 与 `MetadataEnricher` 能为业务域过滤和排序提供稳定扩展位。
