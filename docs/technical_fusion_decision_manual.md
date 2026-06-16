# oncall agent 与 WeKnora 技术融合决策手册

日期: 2026-05-13

## 1. 这份手册是干什么的

这份手册不是再重复介绍 WeKnora 或 oncall agent 的背景，而是把已经确认下来的融合判断，正式落成一份“后续怎么排顺序、怎么控风险、怎么做清单”的执行参考资料。

它主要回答 4 个问题:

1. 哪些方向已经定了，不要再反复摇摆。
2. 哪些模块应该先做，哪些模块必须后做。
3. 每一步最大的风险是什么，怎么提前防。
4. 后面写计划清单和真正实施时，应该拿什么作为判断标准。

这份手册可以同时服务两种场景:

- 写计划和拆任务时，作为决策边界说明。
- 真正做 P1/P2 开发时，作为执行顺序和风险检查表。

---

## 2. 已确认的 5 个决策

这 5 个决策已经可以视为当前阶段的固定前提，后续计划和开发都应以它们为准。

| 决策问题 | 已确认答案 | 对后续意味着什么 |
|---|---|---|
| 保留 oncall agent 的应用主栈，还是迁移成新的知识平台主栈? | 保留应用主栈 | 不做整体主框架迁移，不把当前主仓库改造成 Go 主服务平台。 |
| 现在最缺的是 parser，还是知识库层? | 最缺知识库层 | 当前重点不是先换解析器，而是补 Knowledge / Document / Chunk / Retrieval / Citation 这些系统层。 |
| P1/P2 是否接受先不做完整 WeKnora 服务接入? | 接受 | 当前阶段按“本地复制成熟实现 + 最小修改接入 Python”推进，不做整库接入。 |
| 是否接受 `pdf_eval` 的 MinerU 产物语义作为主项目运行时标准? | 接受 | P2 以 `cleaned.md/chunks.json/tables.json/quality_report.json` 的既有语义为运行标准。 |
| 是否接受“复制 WeKnora 成熟实现后最小修改”，而不是“从零自己设计一套”? | 接受 | 实施时优先复制 WeKnora 成熟代码/结构，再做最小 Python 化，不重新发明平行链路。 |

可以把这 5 条浓缩成一句话:

```text
保留 oncall agent 的 Python 应用骨架，
优先补知识库层，
以 MinerU-first + pdf_eval 产物语义为运行标准，
通过复制 WeKnora 成熟实现并做最小修改来完成 P1/P2。
```

---

## 3. 总体决策框架

### 3.1 当前阶段到底在做什么

当前阶段不是在做下面这些事:

- 不是重做主系统
- 不是把 WeKnora 整体迁进来
- 不是追求一口气做成完整知识平台
- 不是优先做更复杂的检索效果优化

当前阶段真正要做的是:

```text
在不破坏 oncall agent 应用主栈的前提下，
把它的知识库层从“轻量 RAG”补成“有正式对象、正式产物、正式状态、正式引用”的 WeKnora-style 结构。
```

### 3.2 当前阶段的主任务拆分

从系统分层看，当前要补的核心是 4 层:

1. 领域对象层
2. 文档接入与 artifact 层
3. 索引与幂等层
4. 检索与引用层

其中最重要的顺序原则是:

```text
先把对象和产物固定，
再把索引接稳，
最后再把检索和引用做结构化。
```

原因很简单:

- 如果对象没定，后面每层都会改字段。
- 如果 artifact 没定，下游模块根本不知道该读什么。
- 如果索引没稳，检索结果再漂亮也不可信。
- 如果检索没结构化，回答层就没法做稳定 citation。

---

## 4. 模块优先级总表

下面这张表是这份手册最核心的“先后顺序图”。

| 优先级 | 模块 | 是否当前必须做 | 为什么 |
|---|---|---:|---|
| P0 | 决策边界与 artifact 契约 | 是 | 没有这个，后面每一层都会反复返工。 |
| P1 | `KnowledgeBase / DocumentRecord / ChunkRecord` 最小模型 | 是 | 不先建对象层，后面所有状态、artifact、检索结果都挂不住。 |
| P1 | `KnowledgeMetadataStore` | 是 | 没有 metadata store，文档和 chunk 只有 Milvus 里的散 metadata，不够稳。 |
| P1 | md/txt 兼容索引改造 | 是 | 必须先保住旧链路，再往上叠新能力。 |
| P2 | `ParserEngineRouter` | 是 | 不先定 parser 路由，PDF/DOCX/XLSX 入口会变得混乱。 |
| P2 | `DocumentIngestionService` | 是 | 需要把“上传 -> 解析 -> artifact -> 索引”变成正式工作流。 |
| P2 | `MinerUParserAdapter` | 是 | 这是 PDF/DOCX/XLSX 接入主链路的关键接缝。 |
| P2 | `ChunkBuilder / Indexer` | 是 | 必须把 artifact 六件套稳定地变成索引数据。 |
| P2 | `RetrievalServiceV2` 与 citation 基线 | 是 | 不把来源结构化，RAG 还是停在轻量阶段。 |
| P3 | hybrid search / rerank | 否 | 当前不是主要矛盾，过早进入会扩大问题面。 |
| P3 | grounded answer prompt 强约束 | 否，但建议紧随其后 | 要在检索结果结构化后再做，否则引用不稳。 |
| P4+ | 完整 WeKnora 服务接入 | 否 | 只有在 P1/P2/P3 跑稳后，才值得评估。 |

---

## 5. 建议实施顺序

这一节不是泛泛而谈，而是明确建议后续计划清单按什么顺序写。

### 5.1 阶段 0: 固化决策边界

先做什么:

- 固化这份决策手册
- 固化融合分析计划
- 固化 artifact contract
- 固化教材解释文档

为什么一定先做:

- 因为后面很多实现分歧，本质不是代码分歧，而是边界没写死。

这一阶段的输出:

- `docs/oncall_rag_weknora_fusion_analysis_plan.md`
- `docs/rag_ingestion_artifact_contract.md`
- `docs/weknora_r0_reuse_review.md`
- `docs/weknora_oncall_agent_textbook_guide.md`
- 本手册

这一阶段的风险:

- 风险 1: 文档之间口径不一致。
- 风险 2: 计划写的是“复用边界”，开发做成“自己重写一套”。

控制方式:

- 新增实现前，先指认它对应的 WeKnora 来源文件。
- 以后写计划清单时，先引用本手册的优先级和风险表。

### 5.2 阶段 1: 建对象，不改主行为

先做什么:

- 建 `KnowledgeBase`
- 建 `DocumentRecord`
- 建 `ChunkRecord`
- 建 `KnowledgeMetadataStore`
- 改 `md/txt` 入库时的 metadata 补齐

为什么这一步必须先于 PDF 接入:

- 因为 PDF 接入带来的复杂度更高。
- 如果对象层没先立起来，后面 PDF 产物、状态、chunk、citation 都会挂在旧散结构上，迟早返工。

这一阶段的目标:

```text
不改变旧 md/txt 主链路的表面行为，
只在系统内部把“知识库对象层”补出来。
```

这一阶段的风险:

| 风险 | 表现 | 后果 |
|---|---|---|
| 只加新模型，不回填现有 metadata | 新对象在代码里有，Milvus 里没有 | 检索结果结构化不了 |
| 顺手改了旧切分逻辑 | md/txt 行为回退 | 旧样本结果不稳定 |
| 只在应用内存里维护文档状态 | 重启后状态丢失 | 生命周期不可追踪 |

控制方式:

- P1 只允许“加字段、加状态、加对象”，不允许替换旧 md/txt 切分算法。
- 每个新增字段都必须能进入 LangChain `Document.metadata`。
- md/txt 回归检查必须作为 P1 门禁。

### 5.3 阶段 2: 建正式文档接入链路

先做什么:

- 建 `ParserEngineRouter`
- 建 `DocumentIngestionService`
- 建 `MinerUParserAdapter`
- 接上 artifact 六件套生成

为什么这一步排在对象层后面:

- 因为文档接入一旦变复杂，就必须依赖正式的 `DocumentRecord.status`、`artifact_dir`、`parser_engine`、`doc_id`。

这一阶段的目标:

```text
让 PDF/DOCX/XLSX 第一次成为主项目的正式输入，
而不是实验目录里的旁路产物。
```

这一阶段的风险:

| 风险 | 表现 | 后果 |
|---|---|---|
| parser 路由没定清 | PDF 有时走 MinerU，有时被当文本读 | 行为不稳定，难排错 |
| 直接重写后处理逻辑 | 主仓库产物与 `pdf_eval` 语义分叉 | 解析质量与索引语义同时失控 |
| 只产出 Markdown，不产出六件套 | 下游继续靠猜文件 | artifact 契约失效 |
| 失败时偷偷回退到 plain_text | 表面成功，实际脏数据入库 | 后续检索和引用都不可信 |

控制方式:

- `.md/.txt -> plain_text`，`.pdf/.docx/.xlsx -> mineru` 作为固定主路由。
- `MinerUParserAdapter` 先复制 WeKnora `MinerUReader` 结构，再最小修改。
- 运行时只认主项目自己的 artifact 目录，不读 `pdf_eval/outputs/` 历史实验目录。
- 缺任一关键 artifact 时，直接失败，不允许降级入库。

### 5.4 阶段 3: 建索引幂等与 chunk 生命周期

先做什么:

- 按 `doc_id` 删除旧 chunk / 旧索引
- 从 `chunks.json`、`tables.json` 建 chunk
- 补齐 chunk metadata 到 Milvus

为什么这一步不能提前也不能跳过:

- 因为没有幂等，就没有可靠重传。
- 没有 chunk 生命周期，后面 citation 只能拼字符串，无法稳定追踪。

这一阶段的目标:

```text
让“同一文档重复上传、重新解析、重新索引”都能稳定落到同一套对象和同一套来源结构上。
```

这一阶段的风险:

| 风险 | 表现 | 后果 |
|---|---|---|
| 继续只按 `_source` 做弱清理 | 重命名、重传时旧数据残留 | 向量库脏数据累积 |
| 表格和正文都从 `cleaned.md` 猜 | 表格语义丢失 | 检索结果不可控 |
| `chunk_id/doc_id/source_ref` 不完整 | 检索结果能显示文字，不能稳定追源 | citation 做不稳 |

控制方式:

- `chunks.json` 是正文主输入，`tables.json` 是表格主输入。
- `cleaned.md` 仅作人工审阅和 fallback 展示，不允许顶替主输入。
- 重传同一文档时，必须保证“不增加重复脏数据”是硬验收项。

### 5.5 阶段 4: 建 RetrievalService 与 citation 基线

先做什么:

- 建 `RetrievalQuery`
- 建 `SearchResult` 等价结构
- 检索后补齐 `file_name/page/heading_path/source_ref`
- 给 `retrieve_knowledge` 或 `retrieve_knowledge_v2` 返回结构化 artifact

为什么这一步必须晚于对象层和索引层:

- 因为 retrieval 的结构化结果，本质上是吃上游对象、artifact 和 metadata 的。
- 如果上游身份信息不稳，下游再怎么封装也只是漂亮的壳。

这一阶段的目标:

```text
让检索结果第一次真正成为“证据对象”，
而不只是几段拼好的上下文字符串。
```

这一阶段的风险:

| 风险 | 表现 | 后果 |
|---|---|---|
| 只改输出文案，不改结果结构 | 看起来有来源，底层没有稳定引用对象 | 后续回答层仍不可靠 |
| 没有 `source_ref` 延续链 | artifact 有来源，Milvus 或工具返回丢了 | 引用断裂 |
| 先做 answer prompt，再补 citation | 提示词要求模型引用，但数据层给不出稳定来源 | 形成伪引用 |

控制方式:

- `source_ref` 必须从 artifact 进入 chunk metadata，再进入检索结果。
- citation 不是 UI 附加项，而是检索结果的正式字段。
- 至少有一条端到端样本可以展示 `doc_id/chunk_id/page/source_ref/citation_text`。

### 5.6 阶段 5: 再决定要不要进更重能力

只有在前面 4 个阶段都稳定后，才讨论:

- hybrid search
- rerank
- grounded answer 强约束
- 评测闭环
- 完整 WeKnora 服务接入

为什么必须后置:

- 因为这些能力都是“在主链路已经稳定”的前提上增益。
- 如果主链路不稳，越加复杂能力，越难知道问题在哪。

---

## 6. 现在不该先做的模块

这一节的目的，是防止后续计划清单跑偏。

### 6.1 不该先做的方向

| 不该先做 | 原因 |
|---|---|
| 完整 WeKnora 服务接入 | 会把当前问题从“补知识库层”升级成“系统迁移”。 |
| 改主框架为 Go | 与“保留应用主栈”的已定决策冲突。 |
| 自己重写一套 chunker | 与“接受 `pdf_eval` 产物语义为运行标准”冲突。 |
| 提前做 hybrid/rerank | 当前主要矛盾不是召回花样，而是对象、产物、引用没定稳。 |
| 先重写 answer prompt | 如果引用链路还不稳，提示词改得再好也只会逼出伪引用。 |
| 重新把 `MarkItDown` 拉回主路径 | 与“MinerU-first”已定标准冲突。 |
| 现在就把图片多模态检索/图片问答混进 P1/P2 主线 | 当前先保证图片信息不丢，完整多模态能力应进入扩展池，避免主线扩面。 |

### 6.2 一句话判断法

如果后续某个任务让你犹豫“现在要不要做”，先问一句:

```text
它是在补知识库主链路，
还是在给一条还不稳的主链路继续叠复杂功能?
```

如果答案是后者，就应该后置。

补充规则:

- 已明确后置、但未来大概率要做的能力，不应散落在聊天或零散 TODO 中。
- 统一追加到 `docs/oncall_rag_weknora_fusion_analysis_plan.md` 的“扩展内容池”章节。

---

## 7. 每阶段的关键决策门

下面这部分很适合直接拿去做计划清单里的“进入下一阶段前检查”。

### 7.1 进入 P1 前

必须确认:

- 已接受保留 Python 应用主栈。
- 已接受当前最缺的是知识库层，而不是先换 parser。
- 已接受复制 WeKnora 成熟实现后最小修改。

如果这 3 条没定，P1 会边做边摇摆。

### 7.2 进入 P2 前

必须确认:

- `KnowledgeBase / DocumentRecord / ChunkRecord` 已有最小落地。
- md/txt 兼容路径没回退。
- artifact contract 已经固定。
- 已接受 `pdf_eval` 产物语义作为运行标准。

如果这些没定，P2 会出现“新解析链进来了，但没有正式接住它”的情况。

### 7.3 进入 retrieval 结构化前

必须确认:

- `doc_id/chunk_id/source_ref` 已经能稳定进入 Milvus metadata。
- 重传文档不会制造重复脏数据。
- `chunks.json/tables.json` 已成为正式主输入。

如果这些没定，citation 很容易变成伪结构化。

### 7.4 进入更重能力前

必须确认:

- md/txt 回归通过
- PDF/DOCX/XLSX 主路径稳定
- artifact 六件套稳定
- citation 端到端稳定

如果这些没过，就不该继续推进 hybrid/rerank/完整服务接入。

---

## 8. 风险地图

这一节把风险按“最可能伤到哪里”整理成一张图。

| 风险类型 | 最容易出问题的阶段 | 典型症状 | 优先处理方式 |
|---|---|---|---|
| 边界漂移风险 | P1 | 新模型字段和 Milvus metadata 对不上 | 先校正对象和 metadata 对齐 |
| parser 漂移风险 | P2 | 同类文件走不同引擎，结果不稳定 | 锁死路由规则 |
| artifact 漂移风险 | P2 | 上游产物名字变了，下游读不到 | 先保 artifact contract，不改文件语义 |
| 幂等风险 | P2/P3 | 重传后 Milvus 数据重复 | 先修 doc_id 清理逻辑 |
| 引用断裂风险 | P3/P4 | 回答里有“来源”，但追不到真实 chunk | 先补 source_ref 延续链 |
| 复杂度爆炸风险 | 任意阶段 | 一边补主链路，一边上 hybrid/rerank | 先砍后置需求，回到主链路 |

---

## 9. 这份手册如何配合计划清单使用

后续如果你要写更细的计划清单，建议按下面方式使用这份手册。

### 9.1 写任务标题时

任务标题尽量写成“层 + 动作”，例如:

- `P1-1 最小领域对象落地`
- `P2-1 ParserEngineRouter 固化`
- `P2-2 MinerU artifact 六件套接入`
- `P2-3 doc_id 幂等清理`
- `P2-4 Retrieval citation 基线`

这样可以直接对照本手册的阶段顺序。

### 9.2 写任务描述时

每个任务描述都建议包含:

1. 它属于哪一层
2. 它引用哪份 WeKnora 来源实现
3. 它不能破坏什么旧行为
4. 它最大的风险是什么
5. 它的验收门是什么

### 9.3 写验收项时

不要只写“功能可用”，而要写:

- 旧行为是否保持
- 新对象是否落地
- artifact 是否齐全
- metadata 是否完整
- citation 是否端到端稳定

这会让计划清单真正可执行，而不是停留在愿景层。

---

## 10. 当前推荐的实施主线

如果把整份手册压缩成一条非常明确的实施主线，就是:

```text
先固对象，
再固 artifact，
再固索引幂等，
最后固 retrieval/citation；
在这之前不做完整 WeKnora 服务接入，不改主框架，不重写自己的平行链路。
```

换成更口语一点的话，就是:

```text
先把“这份知识在系统里是谁、产出了什么、怎么稳定进库、怎么稳定被引用”这四件事补齐，
其他更花的能力都往后放。
```

---

## 11. 关联文档

- [docs/weknora_oncall_agent_textbook_guide.md](</Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21/docs/weknora_oncall_agent_textbook_guide.md>)
- [docs/oncall_rag_weknora_fusion_analysis_plan.md](</Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21/docs/oncall_rag_weknora_fusion_analysis_plan.md>)
- [docs/weknora_r0_reuse_review.md](</Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21/docs/weknora_r0_reuse_review.md>)
- [docs/rag_ingestion_artifact_contract.md](</Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21/docs/rag_ingestion_artifact_contract.md>)
