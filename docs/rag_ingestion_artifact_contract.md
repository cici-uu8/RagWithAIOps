# RAG Ingestion Artifact Contract

日期: 2026-05-13

## 1. 目的

本文档是 `oncall_rag_weknora_fusion_analysis_plan.md` 中 P1/P2 的执行前硬约束，用来防止文档接入链路出现以下问题:

- 下游想读取的文件，上游没有产出。
- 上游产出了文件，但没有任何阶段消费。
- `cleaned.md`、`chunks.json`、`tables.json`、`quality_report.json` 职责混用。
- PDF/DOCX/XLSX 被静默当成普通文本入库。
- 检索结果缺少稳定 `doc_id`、`chunk_id`、页码和引用来源。

本契约只约束 P1/P2 的最小闭环，不提前规定 P3 之后的混合检索、rerank、GraphRAG 或独立 WeKnora 服务接入。

## 2. 范围

### 2.1 覆盖阶段

| 阶段 | 范围 | 本契约要求 |
|---|---|---|
| P1 | 建立知识库领域对象，不改变现有 md/txt 上传行为 | 增加稳定 `kb_id`、`doc_id`、`chunk_id`、状态和 metadata 字段 |
| P2 | MinerU-first 解析链路产品化进主项目 | PDF/DOCX/XLSX 通过 parser adapter 产出固定 artifacts，再进入索引 |

### 2.2 不覆盖阶段

- BM25 / hybrid search / rerank。
- grounded answer prompt 细节。
- 用户反馈、评测集和长期观测闭环。
- 是否接入完整 WeKnora 服务。

这些能力可以在 P3-P6 继续扩展，但不能改变本文档定义的 P1/P2 artifact 语义。

## 3. 总体原则

1. 上传阶段只负责保存原始文件和创建文档记录，不直接把非文本文件当文本读。
2. 解析阶段必须产出固定 artifact 集合，不能让索引阶段猜路径。
3. 索引阶段只能读取本契约允许的 artifact。
4. 检索阶段必须返回可追溯来源，不能只返回裸文本。
5. 缺少必需 artifact 时，文档状态必须失败，不允许静默降级入库。
6. `pdf_eval` 是已验证实验资产来源，但主项目运行时 artifact 必须落在主项目自己的稳定目录下。

## 4. 推荐目录结构

主项目首版固定使用以下目录:

```text
uploads/
  legacy/
    <safe_filename>
  documents/
    <kb_id>/
      <doc_id>/
        original/
          <safe_filename>
        artifacts/
          artifact_manifest.json
          cleaned.md
          chunks.json
          tables.json
          blocks.json
          quality_report.json
          raw/
            ...
```

说明:

- `uploads/legacy/` 保留给现有 md/txt 兼容路径。
- `uploads/documents/<kb_id>/<doc_id>/original/` 保存上传原件。
- `uploads/documents/<kb_id>/<doc_id>/artifacts/` 是主项目后续解析、索引和检索引用的唯一 artifact 根目录。
- `raw/` 可保存 MinerU 原始输出、中间 JSON、图片、版面文件等，但索引阶段不能依赖 `raw/` 中的非契约文件。

如果后续把 artifact 根目录改为 `data/rag_artifacts/` 或对象存储，必须保持 artifact 文件名和 JSON 字段语义不变。

## 5. 阶段输入输出契约

### 5.1 Upload / Directory Ingestion

输入:

- 用户上传文件。
- 或目录批量接入时扫描出的单个文件。
- `kb_id`，生产入口必须显式传入；eval / 临时隔离集合可以显式使用 `default`。
- 原始文件名。

允许扩展名:

- P1 兼容路径: `md`、`txt`。
- P2 新解析路径: `pdf`、`docx`、`xlsx`。

输出:

- 原始文件: `uploads/documents/<kb_id>/<doc_id>/original/<safe_filename>`。
- `DocumentRecord`。
- 目录批量接入返回 `DirectoryIngestionResult`，其中每个文件仍然必须通过 `DocumentIngestionService.ingest_upload()` 建立 `DocumentRecord`。

禁止:

- 不允许把 `pdf`、`docx`、`xlsx` 直接传给当前 `VectorIndexService.index_single_file()`。
- 不允许目录入口绕过 `DocumentIngestionService.ingest_upload()` 自己按后缀分叉索引。
- 不允许只保存文件、不落 `doc_id`。

### 5.2 DocumentRecord

首版最小字段:

| 字段 | 必需 | 说明 |
|---|---:|---|
| `kb_id` | 是 | 知识库 ID，生产入口必须显式传入；`default` 只作为 eval / test 的显式隔离值 |
| `doc_id` | 是 | 文档稳定 ID |
| `file_name` | 是 | 用户原始文件名或清洗后文件名 |
| `file_ext` | 是 | 小写扩展名 |
| `original_path` | 是 | 原始文件绝对或项目内相对路径 |
| `artifact_dir` | 是 | 本文档 artifact 根目录 |
| `parser_engine` | 是 | `plain_text`、`mineru` 或后续扩展值 |
| `status` | 是 | 文档处理状态 |
| `created_at` | 是 | 创建时间 |
| `updated_at` | 是 | 更新时间 |
| `error_message` | 否 | 失败原因 |

状态枚举:

```text
uploaded
upload_failed
parse_pending
enqueue_failed
parsing
parsed
parse_failed
index_pending
indexing
indexed
index_failed
```

### 5.3 ParserEngineRouter

输入:

- `DocumentRecord`。
- `original_path`。

路由规则:

| 文件类型 | parser_engine | 说明 |
|---|---|---|
| `.md` | `plain_text` | 可继续兼容现有 Markdown 切分逻辑 |
| `.txt` | `plain_text` | 可继续兼容现有文本切分逻辑 |
| `.pdf` | `mineru` | 默认走 MinerU-first |
| `.docx` | `mineru` | 默认走 MinerU-first |
| `.xlsx` | `mineru` | 默认走 MinerU-first |

禁止:

- PDF/DOCX/XLSX 解析失败后静默回退为普通文本入库。
- 使用 `MarkItDown` 作为 P2 默认 Office 主路径。
- 运行时直接读取 `pdf_eval/outputs/` 里的历史实验结果。

### 5.4 Parser Adapter

输入:

- `original_path`。
- `artifact_dir`。
- `parser_engine`。

必需输出:

```text
artifact_manifest.json
cleaned.md
chunks.json
tables.json
blocks.json
quality_report.json
```

输出职责:

| 文件 | 产出方 | 读取方 | 是否必需 | 用途 |
|---|---|---|---:|---|
| `artifact_manifest.json` | Parser Adapter | DocumentIngestionService / Indexer | 是 | 声明本次解析产物、版本、状态和路径 |
| `cleaned.md` | Parser Adapter | 人工审阅 / fallback 展示 | 是 | 人类可读清洗稿，不作为表格抽取主输入 |
| `chunks.json` | Parser Adapter | ChunkBuilder / Indexer | 是 | 正文 chunk 入库主输入 |
| `tables.json` | Parser Adapter | ChunkBuilder / Indexer | 是 | 表格 chunk 入库主输入，可为空数组 |
| `blocks.json` | Parser Adapter | 调试 / QA | 是 | 解析块检查，不作为检索主输入 |
| `quality_report.json` | Parser Adapter | QA / 状态判断 | 是 | 质量、告警、失败原因，不作为检索主输入 |
| `raw/` | Parser Adapter | 调试 / 复跑 | 否 | 原始解析中间产物 |

### 5.5 artifact_manifest.json

最小结构:

```json
{
  "schema_version": "artifact_manifest_v1",
  "kb_id": "default",
  "doc_id": "doc_...",
  "source_file": "uploads/documents/default/doc_.../original/example.pdf",
  "artifact_dir": "uploads/documents/default/doc_.../artifacts",
  "parser_engine": "mineru",
  "parser_version": "mineru-3.1.11",
  "postprocess_version": "rag_postprocess_v1",
  "status": "parsed",
  "required_files": {
    "cleaned_md": "cleaned.md",
    "chunks_json": "chunks.json",
    "tables_json": "tables.json",
    "blocks_json": "blocks.json",
    "quality_report_json": "quality_report.json"
  },
  "created_at": "2026-05-13T00:00:00+08:00"
}
```

规则:

- `artifact_manifest.json` 中声明的必需文件必须真实存在。
- 下游读取路径必须来自 `DocumentRecord.artifact_dir` 和 manifest，不允许硬编码临时输出目录。
- `status != parsed` 时，索引阶段不得继续。

## 6. chunks.json 契约

`chunks.json` 是正文入库主输入。首版每条记录至少包含:

| 字段 | 必需 | 说明 |
|---|---:|---|
| `schema_version` | 是 | 建议 `chunk_v1` |
| `chunk_id` | 是 | 文档内稳定 chunk ID |
| `kb_id` | 是 | 知识库 ID |
| `doc_id` | 是 | 文档 ID |
| `source_file` | 是 | 原始文件路径 |
| `content` | 是 | 入库文本 |
| `content_type` | 是 | `text`、`manual_section`、`paper_section` 等 |
| `heading_path` | 是 | 标题路径数组，可为空 |
| `page_start` | 是 | 起始页，无页码时为 `null` |
| `page_end` | 是 | 结束页，无页码时为 `null` |
| `parser_engine` | 是 | `plain_text` 或 `mineru` |
| `quality_flags` | 是 | 质量标记数组，可为空 |
| `source_ref` | 是 | 稳定引用对象 |

`source_ref` 最小结构:

```json
{
  "kb_id": "default",
  "doc_id": "doc_...",
  "chunk_id": "c00001",
  "source_file": "example.pdf",
  "page_start": 1,
  "page_end": 2,
  "heading_path": ["第一章", "系统概述"],
  "content_type": "manual_section",
  "parser_engine": "mineru"
}
```

## 7. tables.json 契约

`tables.json` 是表格入库主输入，沿用 `pdf_eval/docs/table_schema_v1.md` 的 `table_v1` 语义。每条记录至少包含:

| 字段 | 必需 | 说明 |
|---|---:|---|
| `schema_version` | 是 | 固定 `table_v1` |
| `table_id` | 是 | 文档内稳定表格 ID |
| `source_file` | 是 | 原始文件路径 |
| `page` | 是 | MinerU 原始页码，可为 `null` |
| `page_start` | 是 | 起始页 |
| `page_end` | 是 | 结束页 |
| `heading_path` | 是 | 表格所在章节路径 |
| `content_type` | 是 | 检索侧内容类型 |
| `classification` | 是 | 表格分类 |
| `caption` | 是 | 表题数组，可为空 |
| `rows` | 是 | 结构化行列 |
| `markdown` | 是 | 用于表格 chunk 的展示文本 |
| `raw_html` | 是 | 原始表格 HTML |
| `quality_flags` | 是 | 表格质量标记 |
| `source_ref` | 是 | 稳定引用对象 |

表格入库规则:

- 表格 chunk 的 `chunk_id` 使用 `table:<table_id>` 或 `<doc_id>:table:<table_id>`，实现时二选一后固定。
- `display_text` 使用 `markdown`。
- `structured_payload` 使用 `rows + caption + quality_flags`。
- 不允许从 `cleaned.md` 重新正则抽表。

## 8. quality_report.json 契约

`quality_report.json` 用于 QA、观测和是否允许进入索引的判断，不作为检索输入。

首版最小字段:

| 字段 | 必需 | 说明 |
|---|---:|---|
| `doc_id` | 是 | 文档 ID |
| `parser_engine` | 是 | 解析器 |
| `doc_type` | 否 | 文档类型识别结果 |
| `block_count` | 是 | block 数 |
| `chunk_count` | 是 | chunk 数 |
| `table_count` | 是 | table 数 |
| `quality_flags` | 是 | 文档级质量标记 |
| `fatal_errors` | 是 | 致命错误数组，可为空 |
| `warnings` | 是 | 警告数组，可为空 |

索引准入规则:

- `fatal_errors` 非空时，状态进入 `parse_failed` 或 `index_failed`，不得入库。
- `warnings` 非空时可以入库，但必须保留到 DocumentRecord 或后续观测记录中。
- `quality_report.json` 缺失时，不得入库。

## 9. Indexer 契约

输入:

- `DocumentRecord`。
- `artifact_manifest.json`。
- `chunks.json`。
- `tables.json`。
- `quality_report.json`。

输出:

- Milvus `biz` collection 中的向量记录。
- 每条向量记录的 metadata。
- 文档状态更新为 `indexed` 或 `index_failed`。

向量记录 metadata 至少包含:

| 字段 | 必需 | 说明 |
|---|---:|---|
| `kb_id` | 是 | 知识库 ID |
| `doc_id` | 是 | 文档 ID |
| `chunk_id` | 是 | chunk 或 table chunk ID |
| `_source` | 是 | 保留当前删除旧数据逻辑需要的来源字段 |
| `_file_name` | 是 | 展示来源 |
| `_extension` | 是 | 原始扩展名 |
| `content_type` | 是 | `text`、`table` 等 |
| `page_start` | 是 | 起始页 |
| `page_end` | 是 | 结束页 |
| `heading_path` | 是 | 标题路径数组 |
| `parser_engine` | 是 | 解析器 |
| `source_ref` | 是 | 稳定引用对象 |

禁止:

- 不允许只写 `_source`、`_file_name` 而缺少 `doc_id/chunk_id`。
- 不允许将 `quality_report.json` 的内容直接向量化。
- 不允许在 `chunks.json` 缺失时临时读取 `cleaned.md` 顶上。

## 10. Retriever 契约

`retrieve_knowledge` 或后续 `retrieve_knowledge_v2` 必须返回:

- 给模型看的上下文文本。
- 给调用方保留的结构化 artifact。

结构化 artifact 每条至少包含:

| 字段 | 必需 | 说明 |
|---|---:|---|
| `kb_id` | 是 | 知识库 ID |
| `doc_id` | 是 | 文档 ID |
| `chunk_id` | 是 | chunk ID |
| `content` | 是 | 检索命中的内容 |
| `score` | 否 | 检索分数，当前 Milvus/LangChain 不易取时可后补 |
| `source_ref` | 是 | 引用对象 |
| `citation_text` | 是 | 可展示引用文本 |

推荐引用格式:

```text
[来源: <file_name>, 页码: <page_start>-<page_end>, 章节: <heading_path>, chunk: <chunk_id>]
```

没有检索结果时:

- 返回空 artifact。
- 文本明确说明没有找到相关信息。
- 不允许生成伪引用。

## 11. 缺失文件和失败处理

| 场景 | 状态 | 是否入库 | 处理 |
|---|---|---:|---|
| 原始文件保存失败 | 请求失败 | 否 | API 返回失败，不创建 `DocumentRecord` |
| 异步任务投递失败 | `enqueue_failed` | 是 | 原始文件和 record 已存在，记录队列错误后 API 返回失败 |
| parser 不支持扩展名 | `parse_failed` | 否 | 记录错误 |
| parser 运行失败 | `parse_failed` | 否 | 保留错误日志 |
| 缺少 `artifact_manifest.json` | `parse_failed` | 否 | 不进入索引 |
| manifest 声明文件不存在 | `parse_failed` | 否 | 不进入索引 |
| 缺少 `chunks.json` | `parse_failed` | 否 | 不用 `cleaned.md` 顶替 |
| 缺少 `tables.json` | `parse_failed` | 否 | 即使无表格也必须产出空数组文件 |
| 缺少 `quality_report.json` | `parse_failed` | 否 | 不进入索引 |
| `quality_report.fatal_errors` 非空 | `parse_failed` | 否 | 人工或规则修复后重跑 |
| embedding 或 Milvus 写入失败 | `index_failed` | 否 | 原 artifacts 保留，可重试索引 |

## 12. 最小验收清单

P1/P2 开发完成前，至少需要以下检查:

1. 上传 `md/txt` 后，旧路径仍可入库并能检索。
2. 上传 `pdf` 后，不会走普通文本读取路径。
3. PDF 解析后 artifact 目录中存在 6 个必需文件。
4. 删除 `chunks.json` 后，索引阶段失败，且不会改读 `cleaned.md`。
5. 删除 `tables.json` 后，索引阶段失败，即使文档没有表格。
6. `quality_report.fatal_errors` 非空时不会入库。
7. 成功入库的每条 metadata 都包含 `kb_id/doc_id/chunk_id/source_ref`。
8. 检索结果能展示文件名、页码、章节和 chunk ID。
9. 重新上传同一文档时，旧 chunk 可按 `doc_id` 或 `_source` 被清理，不产生重复脏数据。
10. `pdf_eval/outputs/` 中的历史文件不会被主项目运行时直接读取。

## 13. 与现有文件的关系

- `docs/oncall_rag_weknora_fusion_analysis_plan.md`: 总体战略和分阶段计划。
- `/Users/cici/oncall agent/pdf_eval/docs/table_schema_v1.md`: 表格 artifact 的来源契约，P2 应复用其 `table_v1` 语义。
- `app/api/file.py`: 当前上传入口，P1/P2 改造时必须保持 md/txt 兼容。
- `app/services/vector_index_service.py`: 当前索引入口，P1/P2 后不能只接受文件路径，应能消费结构化 chunks。
- `app/tools/knowledge_tool.py`: 当前检索工具，P3 前至少要保留并逐步补齐稳定 citation metadata。

## 14. 开发边界

P1/P2 不做:

- 大规模重写 Agent。
- 替换 Milvus。
- 接完整 WeKnora 服务。
- 做混合检索和 rerank。
- 做复杂表格 rowspan/colspan 归一化。

P1/P2 必须做:

- 稳定领域 ID。
- 稳定 artifact 文件名。
- 稳定 chunk/table schema。
- 稳定失败状态。
- 稳定 citation metadata。

## 15. 复用优先原则

主实现优先从本地 clone 的 WeKnora 仓库复用成熟代码，路径为:

```text
/Users/cici/oncall agent/WeKnora
```

优先复用的方向包括:

- knowledge base / document / chunk 领域模型。
- parser 适配器与 `docreader` 边界。
- chunking 与 retrieval 服务边界。
- citation / source_ref / retrieval result 结构。

开发时先找现成实现，再做最小适配；只有在 WeKnora 没有可直接复用的成熟代码时，才新增本仓库实现。新增实现也要保持与本契约字段和状态一致。

复用顺序必须固定为:

1. 先判断能否直接使用 WeKnora 原代码而不修改。
2. 不能直接使用时，优先复制到主仓库后做最小修改。
3. 只有直接使用和复制后最小修改都不成立时，才允许新增本仓库实现。

这里的“最小修改”只包括:

- 语言或运行时接缝改写，例如 Go 到 Python 的等价翻译。
- 导入路径、配置项、目录路径对齐。
- 与本文档 artifact contract 强相关的必需字段补齐。

不包括:

- 因个人偏好而重写类层次或 DTO 命名。
- 在已有成熟实现之外再造一套平行流程。
- 先按自己的接口写完，再回头宣称“参考过 WeKnora”。

具体到 document / chunk / parser / retrieval / citation 的复用来源、裁剪边界和开发顺序，按 `docs/oncall_rag_weknora_fusion_analysis_plan.md` 的 `5.5 WeKnora 本地复用映射计划` 执行。
