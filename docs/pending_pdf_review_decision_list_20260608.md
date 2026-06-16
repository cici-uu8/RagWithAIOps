# Pending PDF Review Decision List

日期：2026-06-08

性质：只读决策清单。本文只读取 `data/knowledge_ingestion/original_files_manifest.json`、`data/knowledge_ingestion/current_import_state.json` 和 after-fix triage 报告，不修改 manifest、不启用 import、不改 `current_import_state.json`。

## 当前结论

- Manifest 资产数：12。
- 当前 pending / disabled：12。
- 唯一 PDF 文件组：6（按 SHA1 去重）。
- 当前 import state：`{'total_documents': 3, 'status_counts': {'indexed': 3}, 'pdf_documents': 1, 'pdf_with_job_id': 0}`。
- RAG-12/RAG-13 已被判定为当前助手定位外样本：环保监测 / 合规披露不属于当前 oncall + 工艺 + AIOps 小样本基线。
- 这 6 个唯一 PDF 文件组当前决策为 `rejected_current_kb`：不导入当前知识库；如未来产品要覆盖 EHS/环保合规问答，应另建知识库/权限口径和 evalset。
- 清单中同 SHA1 的文件只应择一导入；当前同一批资料同时出现在 `05_调研记录` 和 `08_长客真实资料` 两个来源目录。

## 人工决策规则

- `approve_import`：确认资料属于目标知识库、权限可见、内容适合被 RAG 检索和引用后，再进入 dry-run / apply。
- `rejected_current_kb`：资料不属于当前知识库或不适合当前助手定位，后续应把相关 eval 标记为 out_of_scope 或移出当前 baseline。
- `defer`：资料定位、权限、密级、重复来源或解析风险未确认，保持 pending。
- 不要为了让 RAG-12/RAG-13 通过而批量放行全部 PDF；先决策唯一文件组，再决定是否导入其中一个来源路径。

## 唯一文件组视图

| group | file_name | kb_id | size_mb | duplicate_rows | source_roots | related_eval | suggested_decision | reviewer_notes |
|---|---|---|---:|---:|---|---|---|---|
| G01 | 2021_中车长春轨道客车_温室气体排放报告.pdf | process_digital_dept | 0.63 | 2 | 05_调研记录, 08_长客真实资料 | RAG-13 | rejected_current_kb | 环保合规资料，当前 oncall + 工艺 + AIOps 小样本不覆盖 |
| G02 | 2023_中车长春轨道客车_友商合规承诺书中英对照.pdf | process_digital_dept | 0.16 | 2 | 05_调研记录, 08_长客真实资料 | - | rejected_current_kb | 法务/合规资料，当前小样本不覆盖 |
| G03 | 2024_中车长春轨道客车_土壤地下水自行监测方案.pdf | craft_dept | 2.72 | 2 | 05_调研记录, 08_长客真实资料 | RAG-12, RAG-13 | rejected_current_kb | 环保监测资料，当前小样本不覆盖 |
| G04 | 2025_中车长春轨道客车_土壤地下水自行监测方案.pdf | craft_dept | 4.04 | 2 | 05_调研记录, 08_长客真实资料 | RAG-12, RAG-13 | rejected_current_kb | 环保监测资料，当前小样本不覆盖 |
| G05 | 2025_中车长春轨道客车_环境信息依法披露临时报告1.pdf | process_digital_dept | 0.10 | 2 | 05_调研记录, 08_长客真实资料 | RAG-13 | rejected_current_kb | 环保合规披露资料，当前小样本不覆盖 |
| G06 | 2025_中车长春轨道客车_监测报告.pdf | craft_dept | 15.89 | 2 | 05_调研记录, 08_长客真实资料 | RAG-13 | rejected_current_kb | 环保监测资料，当前小样本不覆盖 |

## 逐条 manifest 记录

| group | asset_id | file_name | kb_id | status | import_enabled | size_mb | related_eval | relative_path | current_decision |
|---|---|---|---|---|---|---:|---|---|---|
| G01 | orig_6ac06b607109 | 2021_中车长春轨道客车_温室气体排放报告.pdf | process_digital_dept | pending | false | 0.63 | RAG-13 | `05_调研记录/crrc_changchun_20260603/downloads/2021_中车长春轨道客车_温室气体排放报告.pdf` | rejected_current_kb |
| G01 | orig_b089e289ab38 | 2021_中车长春轨道客车_温室气体排放报告.pdf | process_digital_dept | pending | false | 0.63 | RAG-13 | `08_长客真实资料/crrc_changchun_20260603/downloads/2021_中车长春轨道客车_温室气体排放报告.pdf` | rejected_current_kb |
| G02 | orig_026f2d3922f9 | 2023_中车长春轨道客车_友商合规承诺书中英对照.pdf | process_digital_dept | pending | false | 0.16 | - | `05_调研记录/crrc_changchun_20260603/downloads/2023_中车长春轨道客车_友商合规承诺书中英对照.pdf` | rejected_current_kb |
| G02 | orig_8b2100b5c091 | 2023_中车长春轨道客车_友商合规承诺书中英对照.pdf | process_digital_dept | pending | false | 0.16 | - | `08_长客真实资料/crrc_changchun_20260603/downloads/2023_中车长春轨道客车_友商合规承诺书中英对照.pdf` | rejected_current_kb |
| G03 | orig_efe1d25b2215 | 2024_中车长春轨道客车_土壤地下水自行监测方案.pdf | craft_dept | pending | false | 2.72 | RAG-12, RAG-13 | `05_调研记录/crrc_changchun_20260603/downloads/2024_中车长春轨道客车_土壤地下水自行监测方案.pdf` | rejected_current_kb |
| G03 | orig_9c58abf62bd0 | 2024_中车长春轨道客车_土壤地下水自行监测方案.pdf | craft_dept | pending | false | 2.72 | RAG-12, RAG-13 | `08_长客真实资料/crrc_changchun_20260603/downloads/2024_中车长春轨道客车_土壤地下水自行监测方案.pdf` | rejected_current_kb |
| G04 | orig_c3cebc6a7d1e | 2025_中车长春轨道客车_土壤地下水自行监测方案.pdf | craft_dept | pending | false | 4.04 | RAG-12, RAG-13 | `05_调研记录/crrc_changchun_20260603/downloads/2025_中车长春轨道客车_土壤地下水自行监测方案.pdf` | rejected_current_kb |
| G04 | orig_1082637ffd58 | 2025_中车长春轨道客车_土壤地下水自行监测方案.pdf | craft_dept | pending | false | 4.04 | RAG-12, RAG-13 | `08_长客真实资料/crrc_changchun_20260603/downloads/2025_中车长春轨道客车_土壤地下水自行监测方案.pdf` | rejected_current_kb |
| G05 | orig_ba4221e3d168 | 2025_中车长春轨道客车_环境信息依法披露临时报告1.pdf | process_digital_dept | pending | false | 0.10 | RAG-13 | `05_调研记录/crrc_changchun_20260603/downloads/2025_中车长春轨道客车_环境信息依法披露临时报告1.pdf` | rejected_current_kb |
| G05 | orig_b79954c4421e | 2025_中车长春轨道客车_环境信息依法披露临时报告1.pdf | process_digital_dept | pending | false | 0.10 | RAG-13 | `08_长客真实资料/crrc_changchun_20260603/downloads/2025_中车长春轨道客车_环境信息依法披露临时报告1.pdf` | rejected_current_kb |
| G06 | orig_cdfddb79d476 | 2025_中车长春轨道客车_监测报告.pdf | craft_dept | pending | false | 15.89 | RAG-13 | `05_调研记录/crrc_changchun_20260603/downloads/2025_中车长春轨道客车_监测报告.pdf` | rejected_current_kb |
| G06 | orig_88206feff61a | 2025_中车长春轨道客车_监测报告.pdf | craft_dept | pending | false | 15.89 | RAG-13 | `08_长客真实资料/crrc_changchun_20260603/downloads/2025_中车长春轨道客车_监测报告.pdf` | rejected_current_kb |

## 对 RAG-12/RAG-13 的影响

- RAG-12 直接关联 `土壤地下水自行监测方案` 文件组；这些文件当前属于环保监测范围，本轮决策为 `rejected_current_kb`，不导入当前知识库。
- RAG-13 的 triage 使用 `监测` / `报告` 关键词，会匹配多个报告类 PDF；这些报告类 PDF 当前按环保/合规资料处理，全部标记为 `rejected_current_kb`。
- 本轮选择不导入：RAG-12/RAG-13 作为 out_of_scope 处理，不继续修改 expected keywords 让它们通过。
- 如未来产品明确要覆盖环保/EHS/合规问答，应另立知识库范围、权限口径、导入计划和 evalset；届时再从唯一文件组中选择来源路径，走 dry-run -> apply -> metadata/source_ref/RAG eval 复核。
