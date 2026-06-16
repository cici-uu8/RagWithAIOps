# 记忆 RAG/PDF 并行开发 batch0a 静态门报告

日期：2026-06-08

范围：只做文件级、报告级、配置级静态确认；不启动 Milvus、MinerU、后端服务，不执行导入和运行时 smoke。

## 1. 结论

批次 0a 通过，可以进入批次 1 的独立模块代码切片。

但这不是 RAG/PDF 效果验收通过。当前 RAG/PDF 仍受 reviewed import、一个 PDF `index_failed`、`data_not_indexed` 和 MinerU 运行时 smoke 未执行等门禁限制。

## 2. 源文档和测试入口

已确认存在：

- `docs/RAG 系统优化方案.md`
- `docs/pdf 解析优化方案.md`
- `docs/记忆系统修改指南.md`
- `docs/项目完整架构.md`
- `PROJECT_STATE.md`
- `tests/test_retrieval_service.py`
- `tests/test_p3_hybrid_retrieval.py`
- `tests/test_knowledge_search_diagnostics.py`

工作区处于 dirty 状态，本轮只允许触碰并行清单、阶段报告、开发记录和当前 C1 模块相关文件，不混入 AIOps、数据库或前端无关改动。

## 3. 子代理只读勘探结果

A 线 RAG：

- `/api/chat` 和 `/api/chat_stream` 进入 `ChatAdapter`，再进入 `RagAgentService`。
- 当前 `retrieve_knowledge()` 构造 `RetrievalQuery` 时不传 `retrieval_mode`，因此沿用模型默认值。
- `/api/knowledge-search` 已有 hybrid/diagnostics 入口。
- 第一阶段不应把 `retrieval_mode` 暴露成模型可随意传入的工具参数。

B 线 PDF：

- 上传到解析和索引路径经过 `DocumentIngestionService`、parser router、MinerU adapter、artifact manifest、chunk builder 和 vector index。
- `pdf_profile_service` 的最小安全落点是 `DocumentIngestionService.ingest_upload()` 构造 `DocumentRecord` 之后、首次 upsert 前，只写 `DocumentRecord.metadata["pdf_profile"]`。
- artifact validator 首版应是独立 warning-only service，不改现有 hard manifest validation。
- MinerU CLI 路径存在且可执行，但小 PDF runtime smoke 未执行。

C 线 Memory：

- C1 应复用现有 `SessionAccess` / enterprise session owner 边界，不新建第二套用户可见聊天历史。
- C1 最小文件为 `app/models/session_memory.py`、`app/services/session_memory_store.py`、`tests/test_session_memory_store.py`。
- C1 不接入 prompt，不触碰 `RetrievalService`、`SourceRef`、`ToolGateway` 或 parser artifact。

## 4. import gate 静态事实

`data/knowledge_ingestion/original_files_manifest.json`：

- total: 12
- `review_status=pending`: 12
- `import_enabled=false`: 12
- `file_ext=pdf`: 12

`data/knowledge_ingestion/current_import_state.json`：

- total documents: 3
- status counts: `indexed=2`、`index_failed=1`
- PDF documents: 1
- failed PDF: `craft_dept/doc_27b282ca-97c3-5170-af0a-282f2e9122a1`
- failed PDF file: `线上故障处理_现场设备工艺版.pdf`
- parser engine: `mineru`

## 5. RAG eval 静态事实

最新已存在报告：

- `evals/knowledge_base/reports/department_rag_eval_department_rag_20q_20260605_002042.json`
- `evals/knowledge_base/reports/department_rag_eval_department_rag_unscoped_4q_20260605_002331.json`

`department_rag_20q`：

- total: 20
- passed: 11
- failed: 9
- failure categories: `data_not_indexed=7`、`answer_wrong=2`
- `all_source_ref_resolvable=true`

`department_rag_unscoped_4q`：

- total: 4
- passed: 3
- failed: 1
- failure categories: `data_not_indexed=1`
- `all_source_ref_resolvable=true`

## 6. MinerU 静态事实

已确认 MinerU CLI 路径存在且可执行：

- `/Users/cici/oncall agent/pdf_eval/env/.venv/bin/mineru`

未执行：

- MinerU 小 PDF smoke
- parser version/runtime report
- artifact 六件套生成检查

因此 B0 只能记录 `mineru_cli_executable=true`，不能记录 `mineru_runtime_smoke_passed=true`。

## 7. Memory 静态事实

`PROJECT_STATE.md` 仍记录旧长期记忆主线冻结。本次只重开短期会话记忆 C1：

- 允许：`SessionMemoryStore` 接口、SQLite Adapter、InMemory fake、模块单测。
- 禁止：重启旧 P6/P7 调参、memory vector/RRF、memory hit 伪装 RAG citation、默认 prompt 注入。

## 8. 下一步

可并行进入批次 1：

- C 线：先完成 C1 模块验收，再视情况做 C2/C3 接口草图。
- A 线：做 R0/R1 baseline 或 retrieval-mode shadow 基础设施，但不改默认检索策略。
- B 线：做 `pdf_profile_service` 或 artifact validator warning-only，但不改 parser route、不写 artifact、不切 fatal。

仍需后补批次 0b：

- RAG eval 或 retrieval smoke 复跑。
- MinerU CLI health + 小 PDF smoke。
- 后端服务 smoke。
