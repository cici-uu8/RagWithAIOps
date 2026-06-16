# RAG Corpus 清单6 C6-P1a 第一批批准记录

日期：2026-06-12

状态：`c6_p1a_owner_approved_local_first_batch`

## 1. 批次信息

- 批次名称：C6-P1a local-first batch
- 批准范围：10 个本地文件，4 个 Markdown + 6 个 PDF
- 目标：部分扩充 corpus，从 18 个 baseline indexed doc 推进到最多 28 个 doc
- 后续：仍需补充 2+ 个真实业务 Markdown，达到 30+ doc 后才进入 C6 readiness / formal mixed 50q rerun

## 2. 批准文件

### Markdown：4 个

| candidate_id | source_file | kb_id | coverage | owner_approved | notes |
|---|---|---|---|---|---|
| C6-LOCAL-MD-001 | `docs/aiops_真实模拟执行清单.md` | process_digital_dept | AIOps 场景 | yes | 补充故障链路 |
| C6-LOCAL-MD-002 | `aiops_lab/README.md` | process_digital_dept | 运维实验环境 | yes | 补充操作场景 |
| C6-LOCAL-MD-004 | `docs/数据库操作能力.md` | process_digital_dept | DB ops | yes | 补充 DB 场景 |
| C6-LOCAL-MD-005 | `docs/数据库操作能力执行步骤清单.md` | process_digital_dept | DB SOP | yes | 适合 answer eval |

### PDF：6 个（Craft 工艺类）

| candidate_id | source_file | kb_id | coverage | owner_approved | notes |
|---|---|---|---|---|---|
| C6-LOCAL-PDF-001 | `2024_中车长春轨道客车_土壤地下水自行监测方案.pdf` | craft_dept | 监测方案 | yes | 真实企业资料 |
| C6-LOCAL-PDF-002 | `2025_中车长春轨道客车_土壤地下水自行监测方案.pdf` | craft_dept | 监测方案 | yes | 版本对比测试 |
| C6-LOCAL-PDF-003 | `2025_中车长春轨道客车_监测报告.pdf` | craft_dept | 监测报告 | yes | 表格抽取价值 |
| C6-LOCAL-PDF-004 | `2025_中车长春轨道客车_环境信息依法披露临时报告1.pdf` | craft_dept | 合规披露 | yes | 补充 craft 场景 |
| C6-LOCAL-PDF-005 | `2021_中车长春轨道客车_温室气体排放报告.pdf` | craft_dept | 环境报告 | yes | 补充 craft 数据 |
| C6-LOCAL-PDF-006 | `2023_中车长春轨道客车_友商合规承诺书中英对照.pdf` | craft_dept | 合规/双语 | yes | 跨语言测试 |

## 3. Craft PDF 用途和边界

- 覆盖范围：环境监测、合规报告、温室气体、双语文档。
- 不是典型 oncall：这些 PDF 偏环境/合规，不是故障排查 runbook。
- Eval 价值：补充 `craft_dept` 数据，测试 PDF 表格、页码、`source_ref`，并支持跨年份版本对比。
- Scope 边界：仅用于 `craft_dept` KB，不混入 `process_digital_dept`。

## 4. 本批次做什么

- Import & index 这 10 个文件。
- 生成 reviewed import manifest。
- 生成 artifact manifest。
- 验证 `source_ref` 可回查。
- 运行 import / index / artifact sanity check。

## 5. 本批次不做什么

- 不称为 C6 readiness passed，因为 28 < 30。
- 不重跑正式 Mixed 50q retrieval baseline。
- 不宣称 corpus 扩充完成。
- 不用 MCP / SSE 开发文档凑数。
- 不导入 AWS 827 页或 PostgreSQL 3040 页长文档。
- 不修改 `rag_default_retrieval_mode`、`rag_query_rewrite_mode` 或 `rerank_enabled`。

## 6. 批准后状态

```text
c6_p1a_status = partial_corpus_expansion_28_docs_pending_2plus_owner_sources
c6_p1a_imported_target = 10
c6_p1a_imported_format = 4 Markdown + 6 PDF
total_indexed_target = 28
target_indexed = 30-50
gap = 2+ docs
```

推荐 C6-P1b 补充 2+ 个 B 组真实业务 Markdown：

- C6-SRC-MD-001：Redis high memory runbook
- C6-SRC-MD-003：MySQL slow query runbook

达到 30+ doc 后，再跑正式 Mixed 50q baseline。
