# P6 corpus 准备与 trigger 判定设计

日期: 2026-05-19
范围: 仅 **P6 trigger 判定**（语料 / 样本 / 评测脚本）。**不实现 P6**——不动 `app/*` / `tests/*` / ChunkPolicy / metadata schema / RetrievalService。本阶段产出的 `trigger_p6 = true / false` 决定 P6 实现阶段是否启动。

## 0. 边界与不变量

- 沿用 P5.fX validation-only 纪律：不动 `app/*` / `tests/*`，evals/* 与新 docs/* 是本阶段唯一交付物。
- P6 实现层（`domain_metadata` 子字段、`MetadataEnricher` 接口、retrieval 端 filter 入口）一律不在本阶段做。
- 阈值跑前固定（frozen pre-run），跑后不调。
- §4 retrieval invariance（沿用 P5 系列硬断言 6 条）必须仍然成立——这是 P6 评测没污染 retrieval 路径的保证。
- 单 `kb_id` 混 4 域是结构前提，由此**结构上**坐实 §10 trigger (b) "`kb_id` 不足以表达业务边界"。
- 样本规模与 P5.f1 / f2 / f3 对齐：18 条 / 3 类。
- probe 先于样本写定（P5.f1 教训：不允许凭语义直觉选 keyword）。

## 1. 目标与方法

### 1.1 想回答的核心问题

`PROJECT_STATE.md` §10 P6 trigger evidence 三要素：

- (a) ≥ 3 queries 在真实语料里需要 path / folder / domain filtering；
- (b) 仅靠 `kb_id` 不足以表达业务边界；
- (c) 评测里出现"如果有 domain metadata 会明显更好"的稳定案例。

P5 / P5.f1 / P5.f2 / P5.f3 全部跑在 single-domain-natural 的语料上（5 篇 aiops-docs 或 3 篇长文档语料），结构上没法 surface 跨域干扰；`trigger_p6 = false` 不是 P5 实现 bug，是 P5 系列样本/语料天然不带 domain-filter 信号。**P6 trigger 判定需要专门搭一套混库语料**。

### 1.2 方法

本阶段**不实现 P6**，用 oracle filter simulate "if domain metadata existed":

- `actual` flavor: 无 filter，`top_k = 3`；
- `oracle` flavor: 知道 ground-truth domain，candidate pool 内只保留该 domain 的 chunks，再取 `top_k = 3`；
- `lift = oracle_precision@3 - actual_precision@3`。

如果 lift 在 ≥ 3 条 query 上 ≥ 0.10，说明 P6 真的能改善 retrieval；否则当前语料不够 trigger P6。

## 2. 4 域选择（拍板锁定）

混库前提：4 个差异最大的 domain 装进**同一个** `kb_id`。

| 域 | 来源路径 | 文档数 | 选入理由 |
|---|---|---|---|
| `contracts` | `pdf_eval/outputs/postprocessed/mineru/expanded_corpus/contracts_regulations/` | 3 | 法律 / 合同语域，与其他 3 域几乎无术语交集 |
| `manuals` | `pdf_eval/outputs/postprocessed/mineru/expanded_corpus/manuals/` | 5 | 网络设备命令 / 配置，技术词强 |
| `papers` | `pdf_eval/outputs/postprocessed/mineru/expanded_corpus/papers/` | 4 | 学术英语，结构化章节 |
| `aiops-docs` | `super_biz_agent_py-release-2026-03-21/aiops-docs/` | 5 | 中文运维 SOP，已是 P5 主评测原始语料 |

**显式排除**（写死，跑后不放回）：

- `stress_cases/`：扫描件 / 法院表单，解析质量噪音大，会把 P6 trigger 误读成 "解析质量问题"。
- `manual_windows/h3c_e528_config_guide_cn_pages_0_29`：是 `manuals/h3c_e528_config_guide_cn` 的子集，加进来不增 domain 多样性。

总文档数 = 3 + 5 + 4 + 5 = **17**。注意混合 parser engine：`aiops-docs` 是 plain_text（.md），其余 3 域走 MinerU artifact ingestion 路径。这是**特性**不是问题：P6 trigger 应该在两条解析路径混跑下也成立。

**doc 大小不均衡是预期偏置**：aiops-docs 5 篇加起来约 50 chunks；3 个 MinerU 长文档每篇 100+ chunks（参考 P5.f1 数据：h3c_campus 132c、h3c_mc101 155c、arxiv_vit 62c）。candidate pool 12 在 dense recall 下天然偏向 chunk 多的 domain。**这是 P6 oracle filter 应该纠正的偏置本身，是 P6 trigger 信号的来源，不是 corpus 设计 bug**。如果 4 域文档 chunk 数均衡，反而会人为压低 lift，掩盖真实需求。

## 3. 样本设计：18 条 / 3 类

| 类别 | 数量 | 设计目的 | 是否参与 trigger 判定 |
|---|---|---|---|
| `single_domain_required` | 6 | 答案只在某一 domain，但词面跨域暧昧（例：`试用期最长` → contracts；`L2 normalization` → papers）| ✓ |
| `cross_domain_tempting` | 6 | dense recall 容易把 top-3 拉跨域；oracle filter 才能纠正 | ✓ |
| `domain_irrelevant_control` | 6 | folder 无关的负向对照；不参与 trigger 判定，仅做不退化自检 | ✗ |

样本字段（与 P5.f1 jsonl 风格对齐）：

```json
{
  "id": "p6_single_001",
  "category": "single_domain_required",
  "query": "试用期最长不能超过多少？",
  "correct_domain": "contracts",
  "expected_chunk_ids": ["doc_p6_contracts_beijing_..._labor_contract:c00012", "..."],
  "expected_chunk_keywords": ["试用期", "六个月"]
}
```

`correct_domain` 字段：`single` / `cross` 必填四域之一；`control` 必为 `null`。

样本纪律（沿用 P5.f1 教训，跑前固定）：

1. 先用 `_p6_corpus_probe.py` 跑 candidate query 的 dense top-3 命中分布，dump 实际命中 doc / domain 与文本前 500 字。
2. 再用 `_p6_corpus_kw_probe.py` 验证 `expected_chunk_keywords` 在 NONE@top-3 命中文本里**实际出现**。
3. 不允许凭语义直觉选 keyword；不允许凭"看 PDF 标题猜命中"写 `expected_chunk_ids`。
4. probe 失败的 candidate query → 替换或归类到别类，不强写。

## 4. 评测指标

### 4.1 主门槛 / 软观察分层

| 指标 | 类型 | 跑前阈值 |
|---|---|---|
| **retrieval §4 invariance**（沿用 P5 系列）| 强断言 | 6 条 × 18 样本全过；任一失败 = AssertionError 立刻停 |
| **trigger condition (a+c) lift** | 主门槛 | (single + cross) **12 条**里，**≥ 3 条**同时满足 `oracle_precision@3 - actual_precision@3 ≥ 0.10` |
| **不退化自检**（control）| 软观察 | control 6 条 oracle 不应显著拖低 actual；不设硬阈值 |
| precision@3 / recall@3 / citation_correctness@3 / mrr@3 | 软观察 | 全表入报告；与 P3 baseline 口径一致 |

### 4.2 actual_precision@3 vs oracle_precision@3

```
candidate_pool = retrieve_candidates(query, k = top_k * 4)   # 12 candidates
actual_results = candidate_pool[:3]
oracle_results = [c for c in candidate_pool if c.domain == sample.correct_domain][:3]

actual_precision@3 = |chunk_ids(actual) ∩ expected_chunk_ids| / 3
oracle_precision@3 = |chunk_ids(oracle) ∩ expected_chunk_ids| / 3
lift               = oracle_precision@3 - actual_precision@3
```

- **oracle filter 的实现层面 hard rule**：

- 不动 `RetrievalService`；oracle filter 是 eval 脚本本地的 **post-processor**。
- candidate pool 大小固定 `top_k * 4 = 12`，与 P5 `doc_oversample_factor = 4` 对齐；保证 actual 与 oracle 在同一 candidate 集合上比较，避免 "深度不一致" 把 lift 灌水。
- domain 字段在 eval 脚本本地由 §5 显式维护的 `doc_id → domain` 映射查得；**不**写进 `ChunkRecord.metadata`（P6 实现是单独阶段）。

### 4.3 trigger 判定逻辑（frozen pre-run）

```python
trigger_p6 = (
    invariants_all_ok
    and len([
        s for s in single_domain_required + cross_domain_tempting
        if s.lift >= 0.10
    ]) >= 3
)
```

**不允许跑后调阈值** —— P5 系列纪律延续到 P6 trigger。如果 12 条样本里只有 2 条满足，结论就是 `trigger_p6 = false`，记入 Open Problems，**不**降到 ≥ 2 来"凑过线"。

## 5. corpus 索引

- 单一 isolated Milvus collection（沿用 P5.f1 frame）；collection name `p6_corpus_eval_<ts>`；评测结束 drop collection。
- 单一 `kb_id = "default"`（与 P5 系列约定一致）；不分 kb 是结构前提，保证 §10 trigger (b) "`kb_id` 不足以表达业务边界" 直接成立。**实现细节**：plain_text 路径走 `index_service.index_single_file(md_path, kb_id="default")`；MinerU 路径走 `index_service.index_document_record(record)`，`record.kb_id` 显式置 `"default"` 与之对齐。这里的 `default` 只用于 isolated eval collection，不能理解为生产入口 fallback。设计早期版本写作 `kb_id = "p6_corpus"`，patch 后统一为 `"default"`，避免 plain_text 与 MinerU 的 kb_id 不一致导致"双 kb_id 暗坑"。
- doc_id：MinerU 路径手工构造为 `doc_p6_<domain>_<safe_filename>`（debug 可读；e.g. `doc_p6_contracts_beijing_construction_worker_labor_contract_template`）；plain_text 路径由 `index_service._build_doc_id("default", md_file.resolve())` 自动生成（hash 形态，无 domain 前缀）。
- domain 字段不依赖 doc_id 前缀反查：由 indexing 函数在写入时**显式维护** `dict[doc_id → domain]` 映射，eval 脚本逻辑只读这张表。设计早期版本写作"由 doc_id 前缀反查"，patch 后改为显式 map（plain_text doc_id 不带 domain 前缀，prefix 反查会漏）。
- 评测 retrieval 配置默认 cell：`granularity = chunk`，`aggregation = none`，`mode = dense_only`，`top_k = 3`，`pool_k = 12`。这是与 P3 / P5 主基线一致的最小可比 cell；P4.5 / P5 dedup / hybrid / rerank 不在 P6 trigger 判定范围。

## 6. 实现切片

### 6.1 新增

| 文件 | 作用 |
|---|---|
| `docs/p6_corpus_prep_design.md` | 本文档 |
| `evals/rag_retrieval/_p6_corpus_probe.py` | corpus 索引 17 文档到 isolated collection；dump 各 candidate query 的 dense top-3 命中分布与命中文本前 500 字 |
| `evals/rag_retrieval/_p6_corpus_kw_probe.py` | candidate query 的 `expected_chunk_keywords` 在 NONE@top-3 命中文本里的存在性自检 |
| `evals/rag_retrieval/p6_samples.jsonl` | 收敛后的 18 条 / 3 类样本 |
| `evals/rag_retrieval/run_p6_trigger_eval.py` | 主评测脚本，输出 trigger 判定 + 全表 + corner case 高亮 |
| `evals/rag_retrieval/reports/p6_trigger_eval_<ts>.{json,md}` | 报告产物 |

### 6.2 不动

- `app/*` 一字不动（P6 实现单独阶段）。
- `tests/*` 一字不动。
- 既有 P5 / P5.f1/f2/f3 评测脚本与样本 jsonl 不动。
- `ChunkRecord` / `RetrievalQuery` / `RetrievalResult` 字段定义不动。

## 7. Stop-loss

- §4 invariance 失败 → 停（P5 / P4.5 实现 bug 或 P6 评测污染了 retrieval 路径）。
- **corpus indexing 任一文档失败 → 立即停（混 parser engine 首次 live）**：本阶段是 plain_text 与 MinerU artifact 两条 ingestion 路径首次在 eval 框架里混合写入同一 collection。`DocumentIngestionService` / `VectorIndexService` 在单元测试层面覆盖过两条路径，但混合 live 没跑过。任一文档 ingestion fail 都不允许跳过继续，必须停下来汇报根因（解析问题 / metadata 问题 / Milvus 写入问题），由用户决定是否补 fix。
- probe 揭示候选 query ≥ 50% 找不到对应 expected_chunk → 停下来重设计样本，不强写。
- 跑后调阈值或重写样本 → 不允许（与 P5 系列同纪律）。
- **如果 `trigger_p6 = false`**：写明 "P6 trigger evidence 仍不足"，记入 `PROJECT_STATE.md` Open Problems；P6 仍 gated；**不**因为想推 P6 就放宽阈值或扩样本。

## 8. 验证清单（结束态守住）

- `unittest discover tests`: 101/101 仍持平（不动 app/* 与 tests/*）。
- §4 invariance 6 条 × 18 样本: all OK。
- 12 条 (single + cross) sample 的 actual / oracle precision@3 / lift 全表入报告。
- control 6 条不退化自检全表入报告。
- `trigger_p6` 判定结果显式写出（true / false）+ 触发样本 id 列出。
- 报告 markdown 头部显式标注：(i) P6 实现层未动；(ii) oracle filter 是 simulation 不是 P6 实现；(iii) §10 (a)+(c) 的具体阈值（lift ≥ 0.10，≥ 3 条 query 稳定出现）；(iv) 排除域 (`stress_cases` / `manual_windows`) 与排除理由。

## 9. 执行顺序

1. **设计落地（本文档）→ 用户审阅。**（当前步）
2. 写 `_p6_corpus_probe.py`，跑通索引 17 文档到 isolated collection。
3. 草拟 25-30 条 candidate query，跑 corpus probe 看 dense top-3 命中分布与跨域比例。
4. 写 `_p6_corpus_kw_probe.py`，验证 `expected_chunk_keywords` 实际出现。
5. 收敛到 18 条 / 3 类，写入 `p6_samples.jsonl`。
6. 写 `run_p6_trigger_eval.py`。
7. 单轮跑评测。
8. 写报告 + 更新状态文档（PROJECT_STATE / task_plan / chunk_refactor / dev record / findings / progress）；按 `trigger_p6` 结果决定下一步：`true` → 启动 P6 实现阶段（独立 design doc）；`false` → P6 仍 gated，记入 Open Problems，下一步看是 (i) 扩语料再判 还是 (ii) 把 faithfulness 立成独立线先做。

## 10. 不做的事（防偷跑）

- **不实现 P6**：本阶段不动 ChunkPolicy / metadata schema / RetrievalService / 任何 `app/*` 文件。
- **不混进 stress_cases / manual_windows**：理由已写死，未来要扩需单开 P6.b。
- **不允许跑后调阈值**：≥ 0.10 / ≥ 3 query 是 frozen pre-run。
- **不允许 probe 失败时强写样本**：宁可减少 query 数量也不强写（参考 P5.f1 long-doc 4 篇变 3 篇的处理）。
- **不允许 oracle filter 实现混进 `RetrievalService`**：oracle filter 是 eval 脚本本地的 post-processor。
- **不允许把 `trigger_p6 = false` 的结果改写成 "需要扩语料"**：如果 false 就 false，记入 Open Problems；要扩语料是另一个独立决策。
- **不开 P4.5 granularity / P5 dedup / hybrid / rerank cell**：P6 trigger 判定只跑 dense_only + chunk + none 一个最小 cell，多 cell 是 P6 实现阶段后才需要的复测。

## 11. 文档约束（必须显式写进报告）

报告 markdown 头部必须显式标注以下 4 条，不允许只在脚注或附录里写：

1. §10 (a)+(c) 的操作化阈值：`oracle_precision@3 - actual_precision@3 ≥ 0.10`，且在 ≥ 3 条 query 上稳定出现。**等价含义**：因 precision@3 的离散性（分母固定为 3），lift 实际取值集合是 `{0, ±1/3, ±2/3, ±1}`，所以 `≥ 0.10` 实际等价于 `≥ 1/3 ≈ 0.33`，语义上是 "oracle filter 在该 query 上至少多挖出 1 条正确 hit"。这条等价含义必须显式写在报告头部，避免被误读为"小幅提升也算过线"。
2. 4 域选择（contracts / manuals / papers / aiops-docs）+ 排除域（`stress_cases` / `manual_windows`）的理由。
3. oracle filter 是 eval 脚本本地的 post-processor simulation，**不是** P6 实现；P6 实现层在本阶段未动。
4. `trigger_p6` 判定结果（true / false）+ 决策影响（启动 P6 实现 / 仍 gated）。

## 12. 与 P5 系列的关系

- **不替换** P5 / P5.f1 / P5.f2 / P5.f3 已闭合的评测；P6 trigger 评测是**新一类**评测（mixed-domain）而不是 P5 follow-up。
- **不复用** P5 long-doc samples（`p5_long_doc_samples.jsonl`），不复用 P5 main samples（`p5_samples.jsonl`），不复用 P4.5 samples（`p4_5_samples.jsonl`）——这些样本设计目的不同。
- **复用**：corpus indexing 框架（isolated Milvus / metadata store / sandbox-external execution 模式）、§4 invariance 6 条断言、`doc_oversample_factor = 4` 默认、Qwen tokenizer。
- P5.f4 仍 not triggered；P6 trigger 评测不会自动触发 P5.f4。

## 13. faithfulness 边界（reframing 后的当前共识）

按 2026-05-19 reframing 决定：**factual answer faithfulness 是跨 pipeline 的 RAG 质量横切关注点，不是 P5 / P6 交付项**，不是 P6 gate。即使 `trigger_p6 = false`，faithfulness 也作为独立线另起。本设计**不**把 faithfulness 写进 P6 trigger 判定。

## 14. Post-eval finding (2026-05-20): trigger_p6 = True with §10(b) caveat

`run_p6_trigger_eval.py` 单轮 frozen pre-run 跑出：

- `invariants_all_ok = True`（3 条 retrieval-side 不变性 18 sample × pool=12 全过）
- `qualifying_count = 3 / 12`（恰好踩 §10 阈值 `≥ 3`）
- `trigger_p6 = True`
- 报告：`evals/rag_retrieval/reports/p6_trigger_eval_20260520_152021.{json,md}`

3 个 qualifying samples **全部** 集中在 `aiops-docs ↔ manuals` 这一对域：
- `p6_cross_001` 时延延迟网络优化 (aiops, lift=0.67)
- `p6_cross_002` 并发吞吐量限流 (aiops, lift=0.67)
- `p6_cross_003` 归档备份日志存储 (manuals, lift=0.33)

其余 9 条 trigger samples (6 single + 3 control cross) 全部 `lift=0.00`，pool 12/12 同 correct_domain — dense embedding 在 contracts / papers / 单域 manuals / 单域 aiops 上已足够准。

### 14.1 §10 (b) 操作化 gap

设计 §10 的 P6 trigger 三要素是 **(a) ∧ (b) ∧ (c)**：

- (a) ≥ 3 query 需要 path/folder/domain filtering — **本评测验证**: True
- (b) 仅靠 `kb_id` 不足以表达业务边界 — **本评测未验证**
- (c) 评测里出现"如果有 domain metadata 会明显更好"的稳定案例 — **本评测验证**: True

操作化 §10 (a) ∩ (c) 时，trigger 公式只算了这两条；**(b) 与 (a)/(c) 正交**：3 条 qualifying lift 全在 `aiops-docs ↔ manuals` 一对域上。这条事实开启了一个未被本评测排除的可能性：**如果业务上允许把 aiops-docs 和 manuals 拆成两个 `kb_id`，那么用户用 `kb_id` filter 可能就能产生类似量级的 lift，P6 `domain_metadata` enricher 是否必要就取决于产品 / 业务能不能接受这条拆分**。本评测没跑 "split-kb baseline" 验证这条 hypothesis（要跑需要把 aiops+manuals 拆成 2 KB 重新评测，与 §10(b) 决策的因果关系反过来 — 拆 KB 这步本身就在回答 §10(b)）。

换句话说：**这次 `trigger_p6 = True` 证明的是"需要某种域级 filter"，没证明"必须是 P6 的 `domain_metadata` enricher，而不是 kb_id 拆分"**。前一句是 frozen 结论，后一句是 §10(b) 待决问题。

### 14.2 状态判定：trigger=True with caveat，P6 实现仍 deferred

按 frozen pre-run 纪律，trigger 公式跑前定，跑后不调 — **trigger_p6 = True 是 frozen 结论，不能因为 (b) 未操作化就回写成 False**。但 P6 实现 thread 是否启动，需要 **(b) 决策完成** 后再判：

- 如果 stakeholder 决定把 aiops + manuals 分成 2 个 KB → P6 不必要，仍 deferred / 永久关闭
- 如果业务上 aiops + manuals 必须共存于同一 KB（典型场景：运维助手要在网络设备手册和应用监控 SOP 之间无缝跳转）→ P6 必要，启动实现 thread，但 scope 收窄到 aiops↔manuals 这一对域，**不**自动展开成 generic enricher

### 14.3 不允许的事

- **不允许把 trigger=True 直接读成"启动 P6 generic 实现"**：本评测只证 (a) ∩ (c)，未证 (b)。
- **不允许跑后改 trigger 公式补 (b)**：(b) 是产品 / 业务边界判断，不属评测可操作化的事。
- **不允许把 (b) 包装成 evaluation work item**：(b) 决策需要 stakeholder 对齐，不靠加 sample / 改阈值能产生答案。
- **不允许 corpus v2（D 路径）作为 (b) 替代**：corpus v2 (语义近的子域) 是为了让 (a)/(c) 在更挑战性 corpus 上仍稳定，与 (b) 是否需要 P6 这条决策无关。

### 14.4 Followup work items

记入 `PROJECT_STATE.md` Open Problems / Next Step：

1. **§10 (b) 决策**: stakeholder 对齐 "aiops + manuals 是否必须同 KB"。决策→False ⇒ P6 永久关闭；决策→True ⇒ 进 (2)。
2. **P6 实现阶段（gated on 1）**: 启动后写独立 design `docs/p6_implementation_design.md`，scope 限定 `aiops-docs ↔ manuals` 一对域；不开 generic `domain_metadata` enricher。
3. **Corpus v2 / D 路径**（独立 future work，与 §10(b) 决策无关）：当前 4 域语义距离过大让 9/12 trigger samples lift=0；如要让 trigger 评测更具区分度（覆盖更多 domain pair），需要换更挑战 corpus（例如 manuals 内部 install/config/troubleshoot/command-ref/safety 子类），但这是 corpus 评测方法学问题，不是 P6 必须前置。

## 15. §10(b) decision recorded (2026-05-20): **False**

Stakeholder 决策 (2026-05-20): **§10(b) = False**，**P6 永久关闭**，`domain_metadata` enricher 在当前产品形态下**不需要**。

### 15.1 决策依据

按 §14 评测结果：

- trigger 评测只证明了 `aiops-docs ↔ manuals` 这一对域在共存于同一 KB 时会互相干扰（3 条 qualifying lift 全集中在这一对域）。
- 评测**没有**证明"必须靠 `domain_metadata` enricher 才能解决" — `kb_id` 拆分是更简单的替代方案，且未被评测排除。
- 从产品边界看，**aiops-docs 和 manuals 本来就是两类不同知识**（应用运维 SOP vs 网络设备手册）：拆成 2 个 KB 比塞进同一个 KB + 加 enricher 更符合自然业务边界。
- 当前证据（3/12 恰好踩阈值 + 信号高度局部化）支持的最简解是 KB 拆分，不是新增 metadata schema + enricher 接口 + retrieval filter。

### 15.2 关闭范围

以下永久关闭：

- **P6 trigger 阶段**: trigger=True 是 frozen 结论保留在历史记录里，但**不再触发任何后续动作**。
- **P6 实现阶段**: `domain_metadata` 子字段 / `MetadataEnricher` 接口 / retrieval-side domain filter 全部不做。
- **`docs/p6_implementation_design.md`**: 不创建。
- **`ChunkRecord.metadata.domain_metadata`**: 不写入 schema。
- **`RetrievalQuery.domain_filter`**: 不加字段。
- **task_plan.md "P6 domain metadata enricher design" 行**: 标 permanently closed。

以下不受决策影响（独立 future work）：

- **Corpus v2 / D 路径**: 仍然 future work，但与 P6 实现解耦。下次需要在更挑战性 corpus 上跑 trigger 评测（or 别的 domain-filter 评测）时，corpus v2 设计仍然有用，但**不**必然导向 P6 enricher。
- **现有评测脚本**: `_p6_corpus_probe.py` / `_p6_corpus_kw_probe.py` / `_p6_cross_pool_probe.py` / `run_p6_trigger_eval.py` / `p6_samples.jsonl` / `p6_trigger_eval_20260520_152021.{json,md}` 全部保留作为历史评测 artifact，不删除。

### 15.3 重启条件

P6 永久关闭意味着**当前产品形态下不做**，但不意味着"未来任何条件下都不做"。要重启 P6 实现必须同时满足：

- 出现新的 corpus / 用户场景，**aiops + manuals（或类似两类知识）必须共存于同一 KB** 而不能拆分（典型新场景：跨域 RAG 助手、统一搜索面），且
- 评测在这个新场景下重新跑出 trigger=True，且
- 写独立 design 文档（不复用本设计）阐明 scope 与边界。

不允许"P6 凑合塞回当前 release 的 backlog"或"等下次 sprint 再说"——本决策是产品边界判断，不是优先级排期。

### 15.4 不允许的事

- **不允许把 P6 永久关闭悄悄改回 deferred**: 后续若有人在 PR / 设计里再提 `domain_metadata`，必须在 PR 描述里明确引用 §15 并给出新的 trigger 证据，不能靠"原来设计文档里有"作为依据。
- **不允许把 corpus v2 包装成"重启 P6 的前置"**: corpus v2 是 corpus 评测方法学，与 P6 实现无关；本决策已显式声明二者解耦。
- **不允许在评测脚本 / `RetrievalService` 上"顺手加" `domain_filter` 参数**: 即便看起来 "API 更通用"，没有 §15.3 三个重启条件全部满足，不允许动 schema / API surface。
