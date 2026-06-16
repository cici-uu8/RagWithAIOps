# RAG/PDF/Memory P2.6 evalset 候选样本草案

日期：2026-06-09

状态：

```text
status = candidate_draft
formal_evalsets_created = no
retrieval_rerank_eval_rerun = no
default_switch_eligibility = not_eligible_for_default_switch
next_review_required = yes
```

## 1. 草案边界

本文件是 P2.6 的候选样本草案，不是正式 evalset。

本文件做：

- 按 `docs/RAG_PDF_Memory_P2.6_evalset扩充coverage_matrix设计.md` 生成候选样本矩阵。
- 先列出 50 个 Benefit 候选，覆盖 content recall、sparse/hybrid lift、rerank rank lift。
- 标记每个候选的 support 状态、failure class 和是否可计入未来收益证据。
- 列出 guardrail / PDF 候选方向，但不把它们计入 retrieval/rerank 收益。

本文件不做：

- 不创建 `evals/knowledge_base/evalsets/*.jsonl` 正式文件。
- 不重跑 `retrieval_mode_comparison_report.py`。
- 不临时启用真实 rerank。
- 不修改 `app/config.py`。
- 不推进 P2.2 Query Rewrite。

## 2. 当前可用语料

| KB | doc_id | 文档 | 状态 | 用途 |
|---|---|---|---|---|
| `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `superbiz_oncall_handbook.md` | `indexed` | on-call、告警、升级、Runbook、变更窗口 |
| `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `2024_人民网聚焦中车长客数字化转型成果.md` | `indexed` | 数字化转型、智能产线、AI 视觉、数智医生、业数融合 |
| `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `线上故障处理_现场设备工艺版.pdf` | `indexed` | 工艺部现场设备、压力系统、安全隔离、LOTO、PDF source_ref/table |

排除说明：

- pending / disabled / `rejected_current_kb` 的环保、合规、监测 PDF 不进入本轮 Benefit 候选。
- 它们只能进入 backlog 或历史审计，不用于证明 hybrid/rerank 收益。

## 3. 状态枚举

`support_check_status`：

| 值 | 说明 |
|---|---|
| `supported` | 当前 indexed 文档中有明确支撑，可进入人工 review |
| `existing_shadow_seed` | 已在 18q 四模式 report 中出现过差异，可作为 rank/lift 种子 |
| `needs_shadow_probe` | 内容有支撑，但是否形成 rank/lift 需要后续四模式复跑确认 |
| `blocked_corpus_limited` | 当前语料不足，不进入正式 Benefit evalset |
| `reject_duplicate` | 与已有样本过近，建议合并 |

`benefit_counted_now`：

- `no`：当前只是候选，不计入收益。
- 后续只有正式 evalset 创建、复跑并通过 support/gate 后，才允许转为 `yes`。
- 本草案的所有候选默认都是 `no`，表格中不逐行重复该列。

## 4. Benefit-A: content recall 20q 候选

目标 evalset 草案：`department_rag_retrieval_content_recall_20q.jsonl`

| candidate_id | query | allowed_kb_ids | expected_doc_ids | keywords | failure_class | support_check_status | notes |
|---|---|---|---|---|---|---|---|
| P26-A-001 | P0 告警响应时限和恢复目标是什么 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `P0`, `5 分钟`, `1 小时` | `content_recall` | `supported` | 覆盖 SLA 表 |
| P26-A-002 | P1 告警什么情况下升级到负责人 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `P1`, `升级`, `2 小时` | `content_recall` | `supported` | 覆盖升级矩阵 |
| P26-A-003 | on-call 交接会议每周什么时候进行 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `每周一`, `09:30`, `10:00` | `content_recall` | `supported` | 覆盖交接 checklist |
| P26-A-004 | 主值班和备份值班分别负责什么 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Primary`, `Secondary`, `告警` | `content_recall` | `supported` | 覆盖轮换规则 |
| P26-A-005 | P0 事故的 Commander 要做哪些事 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Commander`, `War Room`, `Scribe` | `content_recall` | `supported` | 覆盖 IC 章节 |
| P26-A-006 | 生产数据库 Schema 变更允许在哪个窗口执行 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `数据库 Schema`, `周四`, `DBA` | `content_recall` | `supported` | 覆盖变更窗口 |
| P26-A-007 | 常用 Runbook 里有哪些数据库和回滚相关文档 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `数据库主从切换`, `发布回滚`, `Runbook` | `content_recall` | `supported` | 覆盖 Runbook 索引 |
| P26-A-008 | 告警静默期 Silence 需要提前配置什么信息 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Silence`, `维护单号`, `预计结束时间` | `content_recall` | `supported` | 覆盖 Alertmanager Silence |
| P26-A-009 | 中车长客转向架装配数字化产线用了哪些智能设备 | `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `转向架`, `智能力矩`, `智能监控` | `content_recall` | `supported` | 覆盖数字化产线 |
| P26-A-010 | 智能扭矩系统如何减少质量问题 | `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `智能扭矩`, `拧紧记录`, `质量` | `content_recall` | `supported` | 覆盖质量改进 |
| P26-A-011 | AI 视觉识别在中车长客产线里做什么 | `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `AI视觉`, `操作规范`, `过程管控` | `content_recall` | `supported` | 覆盖 AI 视觉 |
| P26-A-012 | 中车长客数据中心贯通了哪些平台数据 | `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `数据中心`, `能源监控`, `质量管控` | `content_recall` | `supported` | 覆盖平台贯通 |
| P26-A-013 | 数智医生平台如何支持列车健康管理 | `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `数智医生`, `健康管理`, `运维支持` | `content_recall` | `supported` | 覆盖 PHM |
| P26-A-014 | 工艺部线上故障文档中的线上故障指什么 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `生产线`, `装置`, `DCS/PLC` | `content_recall` | `supported` | 覆盖 PDF 适用范围 |
| P26-A-015 | 工艺部现场异常触发条件有哪些 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `停线`, `联锁`, `设备异响` | `content_recall` | `supported` | 覆盖触发条件 |
| P26-A-016 | 工艺异常处理前为什么要先做安全隔离 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `安全隔离`, `LOTO`, `零能量` | `content_recall` | `supported` | 覆盖 LOTO |
| P26-A-017 | 工艺部判断现场故障原因时要哪些专业一起看 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `工艺`, `设备`, `仪表` | `content_recall` | `supported` | 覆盖联合判断 |
| P26-A-018 | 工艺临时处置方案要同时评估哪些风险 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `产品质量`, `环境排放`, `压力系统` | `content_recall` | `supported` | 覆盖临时方案 |
| P26-A-019 | 现场设备维修完成后启动前检查什么 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `联锁恢复`, `泄漏检查`, `试运转` | `content_recall` | `supported` | 覆盖恢复生产验证 |
| P26-A-020 | 工艺故障复盘需要记录哪些信息 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `设备编号`, `报警时间`, `防复发` | `content_recall` | `supported` | 覆盖复盘记录 |

## 5. Benefit-B: sparse / hybrid lift 15q 候选

目标 evalset 草案：`department_rag_retrieval_sparse_hybrid_lift_15q.jsonl`

| candidate_id | query | allowed_kb_ids | expected_doc_ids | keywords | failure_class | support_check_status | notes |
|---|---|---|---|---|---|---|---|
| P26-B-001 | SRE Primary Secondary 分别是什么意思 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Primary`, `Secondary`, `On-call` | `acronym` | `needs_shadow_probe` | 英文术语候选 |
| P26-B-002 | Ack 超时后 PagerDuty 如何升级 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Ack`, `PagerDuty`, `升级` | `exact_term` | `needs_shadow_probe` | 精确词候选 |
| P26-B-003 | Alertmanager Silence 应该什么时候配置 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Alertmanager`, `Silence`, `维护` | `exact_term` | `needs_shadow_probe` | 英文工具名 |
| P26-B-004 | Grafana 和 Datadog 在值班中分别查什么 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Grafana`, `Datadog`, `APM` | `exact_term` | `needs_shadow_probe` | 观测平台词面 |
| P26-B-005 | ArgoCD 回滚操作 SOP 在哪个 Runbook | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `ArgoCD`, `发布回滚`, `SOP` | `identifier` | `needs_shadow_probe` | Runbook 名称 |
| P26-B-006 | TiDB Redis RDS 故障应该找哪个 Owner | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `TiDB`, `Redis`, `RDS` | `acronym` | `needs_shadow_probe` | 数据库服务词面 |
| P26-B-007 | Cloudflare CDN 回源失败查哪个 Runbook | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Cloudflare`, `CDN`, `回源失败` | `exact_term` | `needs_shadow_probe` | CDN 精确术语 |
| P26-B-008 | 5G 高清演播室复兴号京张高铁智能动车组属于什么成果 | `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `5G`, `复兴号`, `智能动车组` | `identifier` | `needs_shadow_probe` | 数字化文章精确短语 |
| P26-B-009 | PHM 数智医生如何监测列车健康 | `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `数智医生`, `健康管理`, `故障预测` | `exact_term` | `needs_shadow_probe` | 术语召回 |
| P26-B-010 | 业数融合做了哪些数据治理工作 | `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `业数融合`, `数据治理`, `流程` | `exact_term` | `needs_shadow_probe` | 标题/术语 |
| P26-B-011 | LOTO 隔离和零能量状态怎么验证 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `LOTO`, `零能量`, `隔离` | `acronym` | `needs_shadow_probe` | 工艺 PDF 精确术语 |
| P26-B-012 | DCS PLC 报警属于工艺部哪类线上故障 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `DCS/PLC`, `报警`, `现场设备` | `acronym` | `needs_shadow_probe` | 控制系统缩写 |
| P26-B-013 | 高温高压有毒易燃风险下能不能拆卸设备 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `高温`, `高压`, `不得拆卸` | `exact_term` | `needs_shadow_probe` | 安全场景 |
| P26-B-014 | t00001 表说明这个 PDF 的评测意图是什么 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `t00001`, `评测意图`, `部门定向检索` | `identifier` | `needs_shadow_probe` | PDF table id 候选 |
| P26-B-015 | 线上故障在工艺部和运维部语境有什么区别 | `process_digital_dept`, `craft_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90`, `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `线上故障`, `Kubernetes`, `现场设备` | `lexical_lift` | `needs_shadow_probe` | 多 KB 近义词对照 |

## 6. Benefit-C: rerank rank lift 15q 候选

目标 evalset 草案：`department_rag_rerank_rank_lift_15q.jsonl`

说明：

- Benefit-C 的候选只能说明“值得后续 shadow probe”。
- 只有真实四模式复跑显示目标 chunk 已召回但排序靠后，才允许进入正式 rank-lift evalset。
- 不能用 P2.4 synthetic rerank 结果替代真实 retrieval 候选。

| candidate_id | query | allowed_kb_ids | expected_doc_ids | keywords | failure_class | support_check_status | seed_evidence |
|---|---|---|---|---|---|---|---|
| P26-C-001 | 线上故障怎么处理时应优先看哪个 Runbook | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `线上故障`, `Runbook`, `处理` | `rank_lift` | `existing_shadow_seed` | RAG-02 dense 0 hits, sparse/hybrid 命中 |
| P26-C-002 | Prometheus 告警定位时 Grafana 和 Runbook 哪个信息更相关 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Prometheus`, `Grafana`, `Runbook` | `rank_lift` | `existing_shadow_seed` | RAG-03 模式间 rank diff |
| P26-C-003 | Runbook 索引里主站 5xx 和数据库主从切换怎么找 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Runbook`, `主站 5xx`, `数据库主从切换` | `rank_lift` | `existing_shadow_seed` | RAG-06 模式间 rank diff |
| P26-C-004 | API 异常升级时 Ack 和 L1 触发条件哪个更关键 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `API`, `Ack`, `L1` | `rank_lift` | `existing_shadow_seed` | RAG-07 模式间 rank diff |
| P26-C-005 | 数据库同步服务告警应先看服务矩阵还是 Runbook 索引 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `数据库`, `服务矩阵`, `Runbook` | `rank_lift` | `existing_shadow_seed` | RAG-08 模式间 rank diff |
| P26-C-006 | source_ref 回查应该优先返回值班手册哪一节 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `source_ref`, `值班`, `Runbook` | `rank_lift` | `existing_shadow_seed` | RAG-18 模式间 rank diff |
| P26-C-007 | chunk_id 可解析时应该命中 Runbook 还是数字化文章 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `chunk_id`, `Runbook`, `source_ref` | `rank_lift` | `existing_shadow_seed` | RAG-19 模式间 rank diff |
| P26-C-008 | PDF 处理失败和工艺 PDF source_ref 应该返回哪段证据 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `PDF`, `source_ref`, `工艺` | `rank_lift` | `existing_shadow_seed` | RAG-20 模式间 chunk 差异 |
| P26-C-009 | P0 事故 Commander 分配 Scribe 和 Operations Lead 的证据在哪 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Commander`, `Scribe`, `Operations Lead` | `rank_lift` | `needs_shadow_probe` | 内容支持，需复跑确认排序 |
| P26-C-010 | 数据库 Schema 变更审批和生产变更窗口哪段更相关 | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `Schema`, `周四`, `DBA` | `rank_lift` | `needs_shadow_probe` | 内容支持，需复跑确认排序 |
| P26-C-011 | 智能扭矩系统和 AI 视觉哪个段落回答质量问题更好 | `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `智能扭矩`, `AI视觉`, `质量` | `rank_lift` | `needs_shadow_probe` | 同文档多段排序 |
| P26-C-012 | 数智医生和业数融合哪个段落回答列车全生命周期管理 | `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `数智医生`, `全生命周期`, `业数融合` | `rank_lift` | `needs_shadow_probe` | 同文档多段排序 |
| P26-C-013 | 工艺异常先停机撤离还是先查 DCS 报警 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `停机`, `撤离`, `DCS/PLC` | `rank_lift` | `needs_shadow_probe` | PDF 多块排序 |
| P26-C-014 | 工艺故障处理里的 LOTO 和联锁恢复哪个步骤先出现 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `LOTO`, `联锁恢复`, `步骤` | `rank_lift` | `needs_shadow_probe` | PDF 顺序/排序 |
| P26-C-015 | 工艺故障复盘记录和恢复生产验证哪个段落更适合回答防复发 | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `复盘`, `防复发`, `恢复生产` | `rank_lift` | `needs_shadow_probe` | PDF 多块排序 |

## 7. Guardrail-D 候选方向

这些样本用于回归，不计入 retrieval/rerank 收益。

| candidate_id | query | allowed_kb_ids | target | guardrail_class | support_check_status | notes |
|---|---|---|---|---|---|---|
| P26-D-001 | 只给运维库权限时读取工艺 PDF t00001 表 | `process_digital_dept` | `craft_dept` | `permission_guardrail` | `supported` | 应 permission_filtered / denied |
| P26-D-002 | 锁定工艺库时搜索 Kubernetes Node 宕机 Runbook | `craft_dept` | `process_digital_dept` | `scope_guardrail` | `supported` | 不应串到运维手册 |
| P26-D-003 | 锁定运维库时搜索 LOTO 现场隔离步骤 | `process_digital_dept` | `craft_dept` | `scope_guardrail` | `supported` | 不应串到工艺 PDF |
| P26-D-004 | citation 必须包含 source_file 和 chunk_id | `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `citation_guardrail` | `supported` | 扩 CITE 类 |
| P26-D-005 | PDF source_ref 必须包含 page_start | `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `citation_guardrail` | `supported` | PDF 回归 |

## 8. PDF-E 候选方向

当前 PDF-E 不进入 50q Benefit，因为只有 1 个 indexed PDF。

| candidate_id | query | doc_id | pdf_check | status | notes |
|---|---|---|---|---|---|
| P26-E-001 | 读取工艺 PDF 第 1 页适用范围 | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | page source_ref | `supported_single_pdf` | 可做 smoke，不代表多 PDF coverage |
| P26-E-002 | 抽取工艺 PDF t00001 表的评测意图 | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | table source_ref | `supported_single_pdf` | 可做 smoke，不代表多 PDF coverage |
| P26-E-003 | 新增第二个 indexed PDF 后扩 page/table eval | TBD | corpus expansion | `blocked_corpus_limited` | 等新增 indexed PDF |

## 9. 当前草案统计

| 类别 | 候选数 | 可直接进入人工 review | 需要 shadow probe | 当前计入收益 |
|---|---:|---:|---:|---:|
| Benefit-A content recall | 20 | 20 | 0 | 0 |
| Benefit-B sparse/hybrid lift | 15 | 0 | 15 | 0 |
| Benefit-C rerank rank lift | 15 | 8 | 7 | 0 |
| Guardrail-D | 5 | 5 | 0 | 0 |
| PDF-E | 3 | 2 | 0 | 0 |

说明：

- Benefit-A 可优先人工 review，因为它们主要验证内容召回。
- Benefit-B/C 必须先通过四模式 shadow probe，不能直接进入正式收益评估。
- 所有 `benefit_counted_now` 均为 `no`。

## 10. 人工 review 清单

正式创建 evalset 前，逐条检查：

- [ ] 是否和现有 18q 样本重复过近。
- [ ] `expected_doc_ids` 是否均为 indexed。
- [ ] `expected_answer_keywords` 是否确实来自目标文档。
- [ ] `allowed_kb_ids` 是否体现真实 scope。
- [ ] `failure_class` 是否准确。
- [ ] Benefit-B/C 是否已经做过 shadow probe。
- [ ] Guardrail 样本是否被错误计入收益。
- [ ] PDF 样本是否被错误包装成多 PDF coverage。

## 11. 下一步

建议下一步：

```text
next_step = review_candidate_matrix
formal_evalsets_created = no
```

人工 review 通过后，再做：

1. 把 Benefit-A 转成正式 `department_rag_retrieval_content_recall_20q.jsonl`。
2. 对 Benefit-B/C 做四模式 shadow probe。
3. 根据 probe 结果筛掉不能证明 lift/rank_lift 的样本。
4. 再决定是否创建 Benefit-B/C 正式 evalset。

## 12. 长期限制与降级策略

### 12.1 Corpus 限制

当前 50 个 Benefit 候选全部基于 3 个 indexed 文档：

- `superbiz_oncall_handbook.md`
- `2024_人民网聚焦中车长客数字化转型成果.md`
- `线上故障处理_现场设备工艺版.pdf`

长期影响：

- 即使后续 50q 显示 `sparse_only` / `hybrid` / `hybrid_rerank` 优于 `dense_only`，结论也只适用于当前小规模 KB 和当前 3 个 indexed 文档。
- 真实生产 KB 如果扩展到 10+ 或 100+ 文档，chunk 分布、同义词冲突、跨文档相似度和权限过滤压力都会变化，当前 50q 不能自动外推。
- 当前 PDF 侧仍是 `corpus_limited`：只有 1 个 indexed PDF、1 页、1 张表，不能证明多 PDF page/table/source_ref 稳定性。

缓解要求：

- 默认检索模式切换前，至少需要补充到 10+ indexed 文档，或在变更记录中明确限定为“小规模 KB（少于 5 个 indexed 文档）场景”。
- 任何默认切换都必须重新跑 E1 permission/scope/citation、PDF page/table/source_ref、四模式 retrieval/rerank 对比和 latency gate。
- 如果新增语料后 failure_class 分布明显变化，必须重审本草案样本，不得直接沿用当前 50q 结论。

### 12.2 Shadow Probe 降级策略

Benefit-B / Benefit-C 当前不是收益证据，只是候选。

Benefit-B sparse/hybrid lift：

- 如果 shadow probe 后少于 10 个样本能证明 `sparse_only` / `hybrid` 相对 `dense_only` 有稳定 lift，则 Benefit-B 降级为 `lexical_lift_observation_report`。
- 降级后只能说明“存在部分词面/缩写/编号观测差异”，不能作为默认切换主要依据。

Benefit-C rerank rank lift：

- 如果 shadow probe 后少于 10 个样本能证明真实 rerank active 有稳定 rank lift，则 Benefit-C 降级为 `rank_lift_observation_report`。
- 降级后只能说明“排序路径具备观测价值”，不能证明 rerank 应默认启用。

Benefit-A content recall：

- 如果 Benefit-A 人工 review 后可保留样本少于 15 个，则不得创建正式 50q benefit evalset。
- 如果 Benefit-A 保留 15 个以上，但 Benefit-B/C 均降级，只能得出“当前小语料下内容召回有改进迹象”，不能得出“词面召回和排序整体更优”。

最终判定规则：

- Benefit-A >= 15q 且 Benefit-B/C 均达到最低有效样本数：可以进入正式 evalset 创建和复跑阶段。
- Benefit-A >= 15q 但 Benefit-B 或 Benefit-C 降级：只生成观测报告，不用于默认切换。
- Benefit-A < 15q：停止创建正式 50q，回到候选设计或语料扩充。
- 任何情况下，只要出现 `wrong_scope`、permission bypass、citation/source_ref 退化或 latency 不可接受，都不能推进默认切换。
