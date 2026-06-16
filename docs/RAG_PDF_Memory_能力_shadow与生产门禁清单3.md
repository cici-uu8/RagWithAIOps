# RAG/PDF/Memory 能力 shadow 与生产门禁清单 3

日期：2026-06-09

状态：执行中。S3-P0 report freshness gate 已完成；S3-0 B4 local recheck 已按 owner 要求提前执行并通过。清单 2.1 已关闭；本清单不是重开清单 2.1。

适用范围：清单 2.1 完成 E1/C4/C5/B4/D1 后，对 RAG、PDF、Memory/AIOps offload 能力做 shadow 观测、评测扩展、生产启用门禁和回滚闭环。

---

## 0. 总结

清单 3 的目标不是继续堆功能，而是把已经接入但默认关闭的能力，变成“能观察、能证明、能回滚、能小范围启用”的能力。

当前基线：

- 清单 2.1 主体已提交：`de5f68c feat: complete checklist2 memory rag pdf gates`
- 清单 2.1 closeout 已提交：`ec6d586 docs: record checklist2 closeout commit`
- B4 indexed-PDF smoke / eval gates 已提交：`f52dcbe feat: complete B4 indexed-PDF smoke and eval gates`
- B4 G7 local-only 启用已提交：`2d704f1 chore: record B4 G7 local PDF tool enablement`
- B4 G7 rollback drill 已提交：`fcb4e4a docs: record B4 G7 rollback drill`

本清单的第一原则：

> shadow 可以建设，active 必须等证据。

换句话说：

- 可以做更强的评测、诊断、shadow 报告。
- 可以做 memory/offload/PDF 的生产门禁补强。
- 可以做 query rewrite / hybrid / rerank 的 shadow 对比。
- 不能因为 current-scope 18/18 或 B4 local 通过，就直接打开默认检索、query rewrite、memory active、tool offload active 或 staging/production PDF 工具。

---

## 1. 当前硬边界

| 能力 | 当前源码默认值 | 当前允许状态 | 禁止事项 |
|---|---:|---|---|
| RAG 默认检索 | `rag_default_retrieval_mode="dense_only"` | dense-only 继续作为默认主链路 | 禁止直接改成 `hybrid` 或 `hybrid_rerank` |
| Query rewrite | `rag_query_rewrite_mode="off"` | 可做 shadow 诊断，不改真实 query | 禁止直接 `rules_active` |
| RAG session memory | `rag_session_memory_mode="off"` | 可做 shadow / 本地长会话观测 | 禁止生产 active 注入 prompt |
| AIOps tool offload | `tool_result_offload_enabled=False` | 可做本地长日志 shadow / 门禁验证 | 禁止 summary-only offload |
| PDF Agent tools | `pdf_agent_tools_enabled=False` | local `.env` 已按 G7 最小范围启用 | 禁止改 `app/config.py` 默认值，禁止 staging/production 无审批启用 |

B4 的特殊状态：

- local `.env` 已批准启用 `PDF_AGENT_TOOLS_ENABLED=true`。
- 启用范围只限 `admin + craft_dept + doc_27b282ca-97c3-5170-af0a-282f2e9122a1`。
- `app/config.py` 默认仍必须保持 `pdf_agent_tools_enabled=False`。
- staging / production 未启用，不能把 local G7 说成生产上线。

---

## 2. 本清单要解决的问题

清单 2.1 已经把能力接入系统，但长期运行风险还没有全部生产化：

| 风险 | 清单 2.1 当前状态 | 清单 3 要补的东西 |
|---|---|---|
| eval 样本过小 | 18q current-scope + E1 30q 是小样本 | 扩展系统能力评测和 PDF 工具评测，建立 report freshness 规则 |
| Memory/offload SQLite 增长 | 有 cleanup 函数，但没有定时任务/容量观测 | TTL 调度、owner 清理、DB size 报告、容量阈值 |
| L0 evidence 长期增长 | durable memory 证据层是长期审计来源，不应随 session cleanup 一起误删 | 单独 retention/归档策略，active 前验证 L0 cleanup 或冷归档 |
| Memory summary 污染 prompt | active 有 stale/长度门禁，但没真实长会话校准 | shadow 长会话报告、stale 命中率、prompt 成本和幻觉回归 |
| Tool offload 破坏审计 | owner-checked store 存原文，但 trace/eval 回查链还要验证 | result_ref 审计回查 smoke、长日志样本、retention 策略 |
| PDF doc_id/page 泄露 | B4 local no-leak 已通过 | local 观察复核、staging/prod 单独审批、更多 PDF 样本 smoke |
| RAG rewrite/hybrid/rerank 误开 | 默认 dense-only/off | shadow 对比报告、收益/退化分类、默认切换门禁 |

---

## 3. 非目标

本清单明确不做这些事：

- 不重开清单 2.1 的实现章节。
- 不把 `app/config.py` 中任何默认开关改成启用。
- 不把 `rag_default_retrieval_mode` 默认改成 `hybrid`。
- 不把 `rag_query_rewrite_mode` 改成 active。
- 不把 rerank 直接接成真实排序。
- 不把 memory summary 当成 RAG citation 或 `SourceRef`。
- 不把 tool offload 的摘要当成审计证据。
- 不扩大 B4 PDF tools 到 staging / production。
- 不导入已拒绝的环保/监测 PDF，除非产品 owner 重新批准当前 KB 范围。

---

## 4. 架构边界

### 4.1 RAG 层

RAG 层负责 retrieval / ranking / citation evidence。

允许：

- dense-only / sparse-only / hybrid / hybrid-rerank 的 shadow 对比。
- query rewrite 的 shadow 候选生成。
- 检索诊断字段记录 original query、shadow query、protected terms、retrieval mode、ranking delta。

禁止：

- 用 memory summary 直接改写 query。
- 让模型通过工具参数随意选择 retrieval mode。
- 绕过 `RagAdapter` / `DocumentAccessService` 的可见文档过滤。
- 在 source_ref 不可解析时声称 citation gate 通过。

### 4.2 Memory 层

Memory 层负责会话上下文、摘要、长会话工作记忆和工具结果回查。

允许：

- shadow 读取 memory snapshot，但不注入 prompt。
- active 候选在本地或测试环境开启并记录注入长度、stale 状态、命中情况。
- offload 长工具结果时保留 owner-checked 原文回查。

禁止：

- 把 memory 文本标成资料依据。
- 让 memory 替代 RAG source_ref。
- 只保留摘要、不保留原始工具结果。
- 无 TTL/容量/回滚记录时生产 active。

### 4.3 PDF 层

PDF 层负责 artifact page/table 工具、source_ref 回查和 no-leak 权限门禁。

允许：

- local 已批准范围继续观察。
- 对新 indexed PDF 增加 smoke matrix。
- staging / production 启用前单独走 G7 类审批记录。

禁止：

- 修改源码默认值来启用。
- 把 local `.env` 启用当成 production 启用。
- 在无权限错误中泄露文件名、正文、表格值、artifact path、source_ref 或 chunk 信息。

### 4.4 诊断与评测层

诊断与评测层是本清单的集成层。

它负责回答四个问题：

1. 能力有没有改变真实回答链路？
2. 改变后有没有收益？
3. 有没有权限、scope、citation 或 no-leak 退化？
4. 如果出事，能不能快速关闭并证明关闭生效？

---

## 5. P0：评测护栏加固

优先级：最高。

目标：先让系统能力评测更像门禁，而不是只看“内容题答对了多少”。

### P0.1 PDF page/table/source_ref eval 扩展

动作：

- 保留现有 `pdf_page_table_eval_report`。
- 增加多 PDF 样本时，按 PDF 类型区分：
  - 有表 PDF：必须验证 page/table/source_ref。
  - 无表 PDF：page/source_ref 必须通过，table 可标记 `not_applicable`。
  - 非 PDF：不进入 PDF table gate。
- 对每个样本记录 `doc_id`、`kb_id`、`page`、`table_id`、`source_ref_resolvable`、`artifact_missing_count`。

通过条件：

- `artifact_missing_count=0`
- page 样本全部通过。
- 有表样本 table presence / extract 全部通过。
- source_ref 全部可解析。

禁止：

- 不允许用 synthetic artifact 替代真实 indexed PDF。
- 不允许把 `not_applicable` 当成 success 数字凑满。

### P0.2 E1 permission/scope/citation 扩展

动作：

- 继续保留三组 E1 eval：
  - permission isolation
  - scope lock
  - citation accuracy
- 增加更强系统能力题：
  - 无权限用户传入已知 `doc_id` 不能得到内容。
  - 指定 KB 后不能串到其他 KB。
  - citation 的 `kb_id/doc_id/chunk_id/source_ref` 必须能回查。
  - PDF page/table 工具的 denied 响应不泄露 metadata。

通过条件：

- permission isolation 不能退化。
- scope lock 不允许出现 `wrong_scope`。
- citation accuracy 不允许出现 `citation_unresolvable`。
- 任何 no-leak 失败都是阻塞。

说明：

- 允许保留已知内容题失败，例如当前 scope lock 的 `SCOPE-08 answer_wrong`，但必须明确它不是 wrong-scope 或 citation 退化。
- 不允许用“改题让它通过”的方式处理真实系统能力失败。

### P0.3 Report freshness 规则

动作：

- 当前第一切片已实现 `evals/knowledge_base/checklist3_gate_report.py`：
  - 汇总 `pdf_page_table_eval_b4_g4_20260609.json`
  - 汇总 `department_rag_permission_isolation_b4_g5_20260609.json`
  - 汇总 `department_rag_scope_lock_b4_g5_20260609.json`
  - 汇总 `department_rag_citation_accuracy_b4_g5_20260609.json`
  - 判断 report 是否缺失、过期、阻塞。
  - 允许 scope lock 保留已知 `answer_wrong` 内容失败，但不允许 `wrong_scope`、`citation_unresolvable`、`not_ready` 或 `asset_blocked`。
- 每个关键 report 记录：
  - evalset 路径
  - 生成日期
  - commit hash
  - indexed 文档数
  - 运行配置
  - 是否默认关闭 / shadow / active
- `PROJECT_STATE.md` 只引用最新有效 report，不把旧 report 当成当前事实。

通过条件：

- 任何 active 或默认值变更前，必须有同日或同 commit 的 gate report。
- `checklist3_gate_report` 输出 `status=passed` 且 `summary.blockers=[]`。

当前本地证据：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.checklist3_gate_report \
  --as-of 2026-06-09T12:00:00+00:00 \
  --max-age-days 7 \
  --output-json evals/knowledge_base/reports/checklist3_s3_p0_gate_20260609.json \
  --output-md evals/knowledge_base/reports/checklist3_s3_p0_gate_20260609.md
```

当前结果：4/4 reports fresh，4/4 gate passed，`blockers=[]`。生成的 report 位于 ignored `evals/knowledge_base/reports/`，作为本地证据，不纳入提交。

### P0.4 Eval coverage / inventory

动作：

- 当前第二切片已实现 `evals/knowledge_base/checklist3_eval_coverage_report.py`：
  - 读取 E1 permission / scope / citation evalsets。
  - 读取 PDF page/table/source_ref evalset。
  - 读取 B4-G7 PDF tool smoke report。
  - 汇总样本数、KB 覆盖、doc 覆盖、source_ref 字段覆盖、PDF page/table 覆盖、denied no-leak smoke 覆盖。
- 该 report 是 inventory，不是 gate：
  - `status=needs_expansion` 表示样本覆盖还薄，不代表当前系统失败。
  - 不重跑 eval，不访问 Milvus / LLM，不修改数据，不改变配置。

当前本地证据：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.checklist3_eval_coverage_report \
  --output-json evals/knowledge_base/reports/checklist3_s3_p0_eval_coverage_20260609.json \
  --output-md evals/knowledge_base/reports/checklist3_s3_p0_eval_coverage_20260609.md
```

当前结果：

- `status=needs_expansion`
- E1 permission/scope/citation：各 `10` 题，基础 permission_filtered / wrong_scope_guard / citation_resolvable 都已覆盖。
- PDF page/table/source_ref：`1` 个样本，`1` 个 PDF 文档。
- B4-G7 PDF smoke：schema safe、authorized page/table、denied page/table no-leak 均已覆盖。
- 当前明确缺口：`pdf_page_table_eval_needs_more_samples`、`pdf_page_table_eval_needs_more_docs`。

下一步样本扩展优先级：

1. 优先补 PDF page/table/source_ref 的多文档样本。
2. 如果当前 indexed PDF 不足，不要硬凑；先登记为 corpus/eval coverage 缺口。
3. E1 三组可以后续扩展，但当前最薄的不是 E1 数量，而是 PDF eval 只覆盖单文档。

### P0.5 Indexed PDF artifact inventory

动作：

- 当前第三切片已实现 `evals/knowledge_base/checklist3_pdf_artifact_inventory_report.py`：
  - 读取 `uploads/_metadata/knowledge_metadata_store.json`。
  - 交叉参考 `data/knowledge_ingestion/current_import_state.json`。
  - 只筛选 `status=indexed` 且 `file_ext=pdf` 的文档。
  - 检查每个 PDF 的 `blocks.json` / `tables.json`。
  - 输出页码覆盖率、可用表数量、候选 page/table eval 文档和 corpus gap。
- 该 report 是只读 inventory，不修改 metadata、artifact、Milvus 或 `.env`。

当前本地证据：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.checklist3_pdf_artifact_inventory_report \
  --output-json evals/knowledge_base/reports/checklist3_s3_p0_pdf_artifact_inventory_20260609.json \
  --output-md evals/knowledge_base/reports/checklist3_s3_p0_pdf_artifact_inventory_20260609.md
```

当前结果：

- `status=corpus_limited`
- 当前 indexed PDF：`1`
- 当前 import_state indexed PDF：`1`
- artifact present：`1`
- page sample candidate：`1`
- table sample candidate：`1`
- 唯一候选：`doc_27b282ca-97c3-5170-af0a-282f2e9122a1`
- blocks：`27/27` 有页码，`page_coverage_rate=1.0`
- tables：`1` 张可用表，`table_id=t00001`
- 当前明确缺口：
  - `indexed_pdf_corpus_single_doc`
  - `pdf_page_eval_candidate_single_doc`
  - `pdf_table_eval_candidate_single_doc`

结论：

- 不是 artifact 质量阻塞；唯一 PDF 的 artifact 是健康的。
- 阻塞更大规模 PDF eval 的是真实语料覆盖：只有一个一页 PDF、一张表。
- 不应把同一个 PDF 重复拆成大量样本来制造“15-20q”的假覆盖。
- 下一步应记录 `pdf_eval_corpus_limited`，等待更多合格 indexed PDF，或只做极小的补充样本并明确它仍是单 PDF 覆盖。

---

## 6. P1：C4/C5 Memory 与 Offload 生产门槛

优先级：高，但不抢在 B4 local recheck 和 P0 eval 之前。

目标：让 memory / offload 从“default-off 可接入”走向“可小范围 shadow 观测”，不是直接生产 active。

### P1.1 TTL 定时清理

动作：

- 为 `SessionMemoryStore.cleanup_expired(...)` 和 `SessionToolResultOffloadStore.cleanup_expired(...)` 增加可运行入口。
- 默认 retention 建议：
  - session snapshot / archive：30 天。
  - tool result offload：7 天。
  - L0 evidence 不跟随 session/offload 清理，见 P1.5。
- 支持 dry-run 输出：
  - owner 数
  - 待删 snapshot/archive/offload 数
  - 预计释放字节数
- 支持 apply 后输出实际删除数量。
- staging / production active 前必须明确 cleanup 责任：
  - 谁配置定时任务。
  - 运行频率。
  - 失败告警位置。
  - 最近一次成功执行时间。

通过条件：

- dry-run 不改数据。
- apply 只删除过期数据。
- owner 过滤正确。
- 默认不自动启动生产定时任务。
- 长期 staging / production active 前，定时清理任务必须至少完成一次 apply 验证；持续运行 7 天以上的 active 观察期必须能看到 >= 7 天的定时任务成功记录。

当前本地证据：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.checklist3_cleanup_runner \
  --as-of 2026-06-09T12:00:00+00:00 \
  --output-json evals/knowledge_base/reports/checklist3_s3_p1_cleanup_dry_run_20260609.json \
  --output-md evals/knowledge_base/reports/checklist3_s3_p1_cleanup_dry_run_20260609.md
```

当前结果：

- `mode=dry_run`
- `status=warning`
- DB exists：`true`
- expired rows：`0`
- deleted rows：`0`
- estimated bytes to free：`0`
- existing tables：`1`
- missing tables：`2`
- warnings：`session_memory_snapshots_missing`、`session_memory_archives_missing`

结论：

- 默认 dry-run 已可运行，且没有删除数据。
- 真实 local DB 当前没有可清理的过期 rows。
- warning 语义与 P1.2 一致：snapshot/archive 表尚未初始化。
- `--apply` 已在单测临时 DB 中验证 owner 过滤和删除行为；未对真实 local DB 执行 apply。

### P1.2 DB size / capacity 报告

动作：

- 增加 SQLite size report：
  - DB 文件大小
  - snapshot/archive/offload 行数
  - 按 owner 聚合
  - 最老/最新记录时间
  - 超 TTL 数量
- 记录初始阈值：
  - local warning：DB 文件 > 100MB。
  - staging / production alert：DB 文件 > 500MB。
  - 单表行数 warning：snapshot / archive / offload 任一表 > 1,000,000 行。
- 明确部署边界：
  - SQLite session/offload store 只适合作为本地或小规模单实例 gate。
  - 多实例部署 active 前，需要外部持久化或明确的单写入者/锁策略。
  - 若仍使用 SQLite，必须记录单实例上限，例如 QPS < 10 的本地或 staging 观察范围。

通过条件：

- 报告只读。
- 不读取或打印完整 memory/offload 内容。
- 不泄露 owner 之外的原始工具结果。
- 监控接入不是本地开发阻塞项，但 staging / production active 前必须有 DB size / 行数告警。

当前本地证据：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.checklist3_db_size_report \
  --as-of 2026-06-09T12:00:00+00:00 \
  --output-json evals/knowledge_base/reports/checklist3_s3_p1_db_size_20260609.json \
  --output-md evals/knowledge_base/reports/checklist3_s3_p1_db_size_20260609.md
```

当前结果：

- `status=warning`
- DB：`logs/enterprise_chat_sessions.sqlite`
- DB exists：`true`
- DB size：`110592` bytes
- total rows：`0`
- total expired rows：`0`
- existing tables：`1`
- missing tables：`2`
- existing table：`session_tool_result_offloads`
- missing tables：`session_memory_snapshots`、`session_memory_archives`

结论：

- 当前不是容量超限；DB 很小且没有 memory/offload rows。
- 当前 warning 来自缺表：`session_memory_snapshots` / `session_memory_archives` 尚未初始化。
- P1.1 cleanup runner 必须把缺表当成可报告状态，而不是崩溃或偷偷创建表。
- 本地报告不能替代 staging / production 监控；active 前仍需定时任务和告警配置。

### P1.3 长会话 shadow 校准

动作：

- 构造或采集长会话样本。长会话第一版定义为：
  - >= 50 轮 user/assistant 对话；或
  - 估算上下文 > 20K tokens；或
  - 真实会话中 live tail 已触发 snapshot/archive 边界。
- 在 `rag_session_memory_mode=shadow` 下观察：
  - snapshot stale 率
  - live tail 增长速度
  - active 候选注入长度
  - prompt 成本估计
  - 是否出现伪 citation / source_ref 文本
- 成本估计先用 token 数估算；如果后续引入 LLM summary 生成，再要求记录每 session 成本和月度预算上限。

通过条件：

- shadow 不改变最终回答。
- stale snapshot 不进入 active 候选。
- memory 文本不能被评测当成 citation evidence。
- active 候选注入长度默认 < 2,000 tokens。
- stale snapshot 命中率建议 < 5%；超过时先调 TTL / snapshot 策略，不进入 active。
- memory 注入导致的首 token 延迟增加建议 < 20%；超过时只能继续 shadow。

当前本地证据：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.checklist3_long_session_shadow_report \
  --output-json evals/knowledge_base/reports/checklist3_s3_p1_long_session_shadow_20260609.json \
  --output-md evals/knowledge_base/reports/checklist3_s3_p1_long_session_shadow_20260609.md
```

当前结果：

- `status=passed`
- 构造长会话：`turn_count=50`，满足 `turn_count >= 50`
- shadow：`snapshot_read=true`，`cleanup_called=true`，`prompt_injected=false`
- active candidate：`prompt_injected=true`，`truncated=true`，`within_max_prompt_chars=true`
- 污染检查：`forbidden_hits=[]`，没有把 `source_ref` / `citation` 带进 memory candidate
- stale candidate：`prompt_injected=false`
- gaps：`[]`

结论：

- P1.3 证明当前 RAG session memory shadow 读取链路可观测，但不改变 prompt。
- active candidate 的长度和 citation/source_ref 污染门禁有效；这不是生产 active 批准。
- stale snapshot 不进入候选；下一步仍需 P1.4 长日志 offload shadow 和后续 scheduler / retention 门禁。

### P1.4 长日志 offload shadow

动作：

- 用真实或准真实 AIOps 长工具结果跑 offload shadow。长工具结果第一版定义为：
  - 原始结果 > 10KB；或
  - 估算 > 2,000 tokens；或
  - 超过当前 `tool_result_offload_threshold`。
- 验证：
  - `past_steps` 仍是 JSON/string-compatible。
  - `tool_result:*` ref 可以按 owner 回查完整原文。
  - 写失败、超 max bytes、缺 session/owner 时保留原文。
  - SSE、audit、eval matcher 不因为摘要丢证据。

通过条件：

- 不出现 summary-only 状态。
- result_ref 回查链可复现。
- 无权限 owner 不能读取别人的 offload 原文。
- offload 后 eval / audit / incident review 能按 `tool_result:*` ref 找回完整原文。

当前本地证据：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.checklist3_long_log_offload_shadow_report \
  --output-json evals/knowledge_base/reports/checklist3_s3_p1_long_log_offload_shadow_20260609.json \
  --output-md evals/knowledge_base/reports/checklist3_s3_p1_long_log_offload_shadow_20260609.md
```

当前结果：

- `status=passed`
- synthetic long log：`original_result_bytes=12288`，满足 `>10KB`
- prompt payload：`result_ref_present=true`，`json_string_compatible=true`
- prompt 泄露检查：`tail_sentinel_leaked=false`
- owner 回查：`owner_can_read_full_original=true`
- 跨 owner：`other_owner_can_read=false`
- summary-only：`summary_only_state=false`
- gaps：`[]`

结论：

- P1.4 证明当前 AIOps long-log offload 可以保持 `past_steps` string-compatible，同时把完整原文留在 owner-checked store。
- offload 后 prompt 只保留摘要和 `tool_result:*` ref，不把完整尾部证据塞回 prompt。
- 该报告使用 synthetic long log 和临时 SQLite DB；它不是生产启用 `tool_result_offload_enabled=true` 的批准。

### P1.5 L0 evidence retention

动作：

- 单独盘点 durable memory 的 L0 evidence 表或 store。
- 制定与 session/offload 不同的 retention 策略：
  - 默认保留 90 天。
  - 超过 retention 后优先冷归档；如果删除，必须保留审计摘要和 owner / evidence id / 删除时间。
  - 按 owner 支持清理和导出。
- 如果当前实现尚无 L0 cleanup 入口，登记为 P4 backlog，但 C4/C5 production active 不能绕过这个风险说明。

通过条件：

- L0 evidence 不被 session cleanup 误删。
- L0 cleanup / archive 有 dry-run。
- 不打印 evidence 原文。
- active 前要么验证 L0 retention，要么明确限制 active 观察期和容量上限。

---

## 7. P2：RAG 检索增强 shadow

优先级：中。可以与 P1 并行，但不能早于 P0 基线。

目标：建设 query rewrite / hybrid / rerank 的 shadow 证据，不改变当前 dense-only 默认主链路。

### P2.1 现有能力盘点

已知当前能力：

- `RetrievalMode` 已支持 `dense_only`、`sparse_only`、`hybrid`、`hybrid_rerank`。
- `HybridSearchService` 已支持 dense / sparse / RRF / optional rerank。
- `RerankService` 已有 enabled / disabled / fallback / timeout 语义。
- `rag_default_retrieval_mode` 默认是 `dense_only`。
- `rag_query_rewrite_mode` 默认是 `off`。

动作：

- 先列出当前主链路到底在哪里读取 `rag_default_retrieval_mode`。
- 先确认 comparison runner 是否能稳定比较 dense-only / sparse-only / hybrid / hybrid-rerank。
- 先记录 latency、wrong_scope、citation_unresolvable、source_ref_resolvable。
- 如果发现 hybrid / rerank 现有路径不能稳定运行，先单独修 bug 和补测试；不能一边修 retrieval bug 一边下 active 结论。

通过条件：

- 不修改默认检索结果。
- 不让模型可见 retrieval mode 参数。

当前本地证据：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.retrieval_mode_comparison_report \
  --samples evals/knowledge_base/evalsets/retrieval_mode_comparison_samples_20260608.json \
  --output-json evals/knowledge_base/reports/retrieval_mode_comparison_p2_inventory_20260609.json \
  --output-md evals/knowledge_base/reports/retrieval_mode_comparison_p2_inventory_20260609.md

uv run python -m evals.knowledge_base.checklist3_rag_shadow_inventory_report \
  --comparison-report evals/knowledge_base/reports/retrieval_mode_comparison_p2_inventory_20260609.json \
  --output-json evals/knowledge_base/reports/checklist3_s3_p2_rag_shadow_inventory_20260609.json \
  --output-md evals/knowledge_base/reports/checklist3_s3_p2_rag_shadow_inventory_20260609.md
```

当前结果：

- `status=needs_shadow_expansion`
- `RetrievalMode` values：`dense_only`、`sparse_only`、`hybrid`、`hybrid_rerank`
- 默认边界：`rag_default_retrieval_mode=dense_only`、`rag_query_rewrite_mode=off`、`rerank_enabled=false`
- `retrieve_knowledge` 工具 schema 未暴露 `retrieval_mode`
- `HybridSearchService` / `RerankService` 存在，且 hybrid 路径支持 RRF + optional rerank
- comparison runner 已在 P2.3 扩展到 `dense_only`、`sparse_only`、`hybrid`、`hybrid_rerank`
- 最新 18q 四模式 comparison 真实复跑通过：`not_ready_count=0`、`wrong_scope_count=0`、`citation_incomplete_count=0`
- query rewrite：`not_implemented`
- gaps：`query_rewrite_not_implemented`

结论：

- P2.1 盘点完成，P2.3 已补齐 runner 对 sparse-only / hybrid-rerank 的覆盖。
- 这不是 default hybrid / rerank active 的证据；当前四模式报告只有 18q current-scope 小样本，且 `hybrid_rerank` 在 `rerank_enabled=false` 下走的是 disabled rerank 路径。
- 下一步应继续 P2.2 query rewrite shadow 或继续扩展 P2.3 到 50q / 3 evalset 稳定性证据；不能直接切默认 retrieval mode。

### P2.2 Query rewrite shadow

动作：

- 新增或完善 `query_rewrite` shadow 模块。
- 只生成候选 query，不替换真实 query。
- 记录：
  - original_query
  - rewritten_query
  - protected_terms
  - dropped_protected_terms
  - rewrite_reason
  - skip_reason

通过条件：

- protected terms 丢失则 shadow 判失败。
- scope 词、部门词、doc_id、kb_id 不允许被 rewrite 扩大。
- shadow trace 可见，但真实检索仍使用 original query。

禁止：

- 当前不允许 `rules_active`。
- 不允许接 LLM rewrite 作为默认。

### P2.3 Retrieval mode shadow comparison

动作：

- 在同一 evalset 上比较：
  - dense-only
  - sparse-only
  - hybrid
  - hybrid-rerank
- 输出每题差异：
  - 目标 doc 是否进入 top-k
  - top chunk 是否变化
  - source_ref 是否仍可解析
  - wrong_scope 是否增加
  - latency 是否增加
- 每个样本要标注 failure class，说明它为什么可能受益于 hybrid / rerank。corpus gap、out_of_scope、eval expectation 问题不能拿来证明检索增强有效。

通过条件：

- hybrid 或 rerank 只有在不增加 wrong_scope/citation 失败，且对真实 failure 类别有稳定收益时，才进入 active 候选。
- 第一版收益门槛：
  - evalset 至少 50q，或覆盖 3 个独立 evalset。
  - recall@5 或 expected-doc top-k 有稳定提升，建议提升幅度 > 10%。
  - 不要求在小样本阶段做 p-value 结论；样本规模足够后再补统计显著性检验。

当前执行结果（2026-06-09）：

- `evals/knowledge_base/retrieval_mode_comparison_report.py` 已支持 `--evalset` / `--samples`、`--modes`、`--output-json` / `--output`，并支持 JSONL current-scope evalset。
- 本轮 18q 四模式报告：`evals/knowledge_base/reports/retrieval_4mode_comparison_20260609.json` / `.md`（reports 目录为 ignored evidence）。
- 真实复跑结果：
  - `total=18`
  - `mode_result_counts`: dense-only `43`、sparse-only `54`、hybrid `48`、hybrid-rerank `48`
  - `mode_expected_doc_found_counts`: dense-only `17`、sparse-only `18`、hybrid `18`、hybrid-rerank `18`
  - `mode_not_ready_counts`: 四模式均 `0`
  - `mode_wrong_scope_counts`: 四模式均 `0`
  - `mode_citation_incomplete_counts`: 四模式均 `0`
  - `rerank_status_counts_by_mode.hybrid_rerank.disabled=48`
  - 本次 latency p95：dense-only `1691ms`、sparse-only `9ms`、hybrid `1199ms`、hybrid-rerank `1070ms`
- 本轮发现并修复 `RerankService.rerank()` disabled 分支的 `top_k` 契约问题：旧代码会先扩到 `max(query.top_k, rerank_top_k)` 再返回 disabled candidates，导致 `hybrid_rerank` 在 rerank 关闭时可能返回超过 `top_k` 的结果。修复后 disabled 分支返回 `candidates[: query.top_k]`，并由 `tests/test_p3_rerank_service.py` 回归锁定。
- P2.1 inventory 已用上述 4-mode report 刷新，`comparison_runner_missing_sparse_only` 和 `comparison_runner_missing_hybrid_rerank` 消失，当前唯一 gap 为 `query_rewrite_not_implemented`。

边界：

- `hybrid_rerank` 本次只是证明路径、source_ref、scope 和 `top_k` 契约可观测；因为 `rerank_enabled=false`，它不代表 rerank 模型质量收益。
- 本轮没有修改 `app/config.py` 默认值，没有把 `rag_default_retrieval_mode` 切到 hybrid / hybrid-rerank，没有启用 query rewrite active，也没有把 `retrieval_mode` 暴露给模型工具参数。

### P2.4 Rerank shadow

动作：

- 对 hybrid 候选集记录 rerank 后排序，但不改变实际回答排序。
- 记录 rerank status：
  - disabled
  - success
  - fallback
  - timeout
- 记录 p50/p95 latency。

通过条件：

- rerank 不改变 citation identity，只比较排序。
- fallback 不影响 dense-only 主链路。
- p95 latency 不越过门槛。第一版门槛：
  - rerank 增量 p95 < 500ms；且
  - hybrid / hybrid-rerank 总 p95 <= dense-only p95 * 1.3。
- 外部 rerank API 如果启用，必须记录单次成本估算和月度预算上限；预算未定时只能本地 shadow。

当前执行结果（2026-06-09）：

- 新增 `evals/knowledge_base/checklist3_rerank_shadow_report.py`，读取 P2.3 的 4-mode comparison，并用合成候选在本进程内临时跑 `RerankService(enabled=True)`。
- 真实报告：`evals/knowledge_base/reports/checklist3_s3_p2_rerank_shadow_20260609.json` / `.md`（reports 目录为 ignored evidence）。
- 结论：
  - `status=passed`
  - P2.3 最新 comparison 中 `hybrid_rerank_status_counts={"disabled": 48}`
  - disabled 原因：`runtime_rerank_disabled`
  - source default：`rerank_enabled=false`
  - runtime config：`rerank_enabled=false`
  - 当前 scorer：`LexicalRerankScorer`
  - 当前 model：`local_lexical_v1`
  - 当前 scorer 不需要外部 API：`external_dependency_required_for_current_scorer=false`
  - synthetic active shadow：`applied=2`、`top_k_respected=true`、强相关候选排到第一、`source_ref_identity_preserved=true`
  - synthetic fallback shadow：`fallback=2`、`top_k_respected=true`、`error_recorded=true`、`source_ref_identity_preserved=true`
  - `gaps=[]`

边界：

- P2.4 解释了为什么 P2.3 中 rerank 全部 disabled：这是默认关闭的预期行为，不是缺外部 API。
- P2.4 只证明本地 lexical rerank 可以在 synthetic shadow 中 `applied` / `fallback`，不证明真实 18q 上 rerank active 有稳定收益。
- 不允许因为 P2.4 `status=passed` 就设置 `rerank_enabled=true` 或把默认检索切到 `hybrid_rerank`。真实 active 候选仍需要 50q / 3 evalset、latency/cost、permission/scope/citation、回滚记录和 owner 批准。

### P2.5 默认切换门禁

任何默认检索变更都必须满足：

1. current-scope baseline 不退化。
2. E1 permission/scope/citation 不退化。
3. PDF page/table/source_ref 不退化。
4. 新增 failure-class eval 显示收益不是偶然：至少 50q 或 3 个 evalset 稳定提升，且不是靠 out_of_scope / corpus gap 样本制造收益。
5. latency 和成本可接受：hybrid p95 不超过 dense-only 的 1.3 倍；rerank 增量 p95 < 500ms；外部 API 有预算上限。
6. 有 rollback 记录。
7. `PROJECT_STATE.md` 明确记录变更范围。

未满足前，默认保持：

```text
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
```

当前判定（2026-06-09）：

```text
default_switch_eligibility = not_eligible_for_default_switch
```

判定依据：

| 门禁项 | 当前证据 | 是否满足 | 说明 |
|---|---|---:|---|
| current-scope baseline 不退化 | 18q 四模式 comparison 无 `not_ready` / `wrong_scope` / `citation_incomplete` | 部分满足 | 只覆盖 18q 小样本，不能代表长期分布 |
| E1 permission/scope/citation 不退化 | B4-G5 三组 E1 eval 已复跑 | 部分满足 | E1 是系统护栏，不是 retrieval 收益证明 |
| PDF page/table/source_ref 不退化 | PDF eval 1/1，artifact 健康 | 部分满足 | 当前 indexed PDF corpus 只有 1 个 PDF，仍是 `corpus_limited` |
| failure-class 稳定收益 | sparse/hybrid 在 18q 上 expected doc 18/18，dense-only 17/18 | 未满足 | 样本太少，且没有 failure-class 均衡；不能排除偶然收益 |
| latency / cost 可接受 | 18q 报告记录 p95；rerank 当前 synthetic only | 未满足 | 缺 50q / 3 evalset 的稳定 latency；缺真实 rerank enabled 数据 |
| rollback 记录 | PDF B4 有 rollback drill | 未满足 | retrieval 默认切换还没有独立 rollback 记录 |
| `PROJECT_STATE.md` 记录范围 | 已记录 default-off/shadow 边界 | 部分满足 | 需要在真正申请 active 时记录目标环境、范围、回滚方式 |

结论：

- 当前 P2.1 / P2.3 / P2.4 证据只能说明 retrieval mode 和 rerank 路径可观测，且在 18q 小样本上没有发现 scope/citation 退化。
- 18q 结果可以作为 shadow baseline，不能作为默认切换依据。
- `hybrid_rerank` 在 P2.3 中实际仍是 `rerank_enabled=false` 的 disabled 路径；P2.4 的 synthetic applied/fallback 只证明本地 rerank 可被观测，不证明真实检索质量收益。
- P2.2 Query Rewrite 不在清单 3 内推进 active；当前没有证据说明主要失败模式是 query 表达问题。清单 3 收口后，Query Rewrite 应另开新阶段，先做“用户表达不佳”failure-class 评测，再决定是否实现 shadow。

### P2.6 Retrieval / rerank evalset 扩充设计

目标：

- 先设计 50q / 3 evalset coverage matrix，再创建样本。
- 不为了凑 50q 硬拆当前 3 个 indexed 文档；样本必须能被当前或明确纳入 scope 的语料支持。
- 不把 `out_of_scope`、`corpus_gap`、`eval_expectation_issue` 样本计入 retrieval / rerank 收益。

扩充策略：

| 层级 | 建议 evalset | 目标样本量 | 目的 | 必填标注 | 进入默认切换证据的条件 |
|---|---|---:|---|---|---|
| Benefit-A | `department_rag_retrieval_content_recall_20q.jsonl` | 20 | 覆盖当前 scope 内真实内容召回 | `expected_doc_ids`、`expected_keywords`、`failure_class=content_recall` | 目标文档必须存在且 indexed |
| Benefit-B | `department_rag_retrieval_sparse_hybrid_lift_15q.jsonl` | 15 | 专门覆盖 sparse/hybrid 可能优于 dense 的词面、缩写、编号、术语样本 | `failure_class=lexical_lift|acronym|identifier|exact_term` | dense 可失败，但必须证明不是 corpus gap |
| Benefit-C | `department_rag_rerank_rank_lift_15q.jsonl` | 15 | 覆盖目标文档已召回但排序靠后的 rerank 候选 | `failure_class=rank_lift`、`expected_doc_ids`、`expected_top_k_before` | 需要真实 rerank enabled shadow，不用 synthetic 结果代替 |
| Guardrail-D | 现有 E1 permission/scope/citation 三组 + 后续扩展 | 30+ | 检查新检索策略不破坏权限、scope、citation | `forbidden_kb_ids`、`selected_kb_ids`、`expected_source_ref` | 作为回归门禁，不单独证明收益 |
| PDF-E | PDF page/table/source_ref 扩展 | 视 corpus 而定 | 检查 retrieval 变更不破坏 PDF 引用链 | `doc_id`、`page`、`table_id`、`expected_source_ref` | 当前 blocked by `pdf_eval_corpus_limited` |

执行顺序：

1. 先生成 coverage matrix / 样本清单草案，不直接写入正式 evalset。
2. 对每个候选样本做 corpus support 检查：目标 doc 是否 indexed、关键词是否在目标 doc 或其 chunk 中可验证、source_ref 是否可解析。
3. 剔除或标记 `out_of_scope`、`corpus_gap`、`eval_expectation_issue`；这些样本只能进入 backlog 或历史审计，不能计入 retrieval mode 收益。
4. 创建正式 evalset 后，使用同一 runner 对 `dense_only`、`sparse_only`、`hybrid`、`hybrid_rerank` 复跑。
5. 如果要评估真实 rerank，必须在受控 report 进程中临时启用 `rerank_enabled=true`，并同时记录 latency、fallback、source_ref identity、wrong_scope 和 citation 完整性；不得修改 `app/config.py` 默认值。

通过条件：

- Benefit 层至少达到 50q，或覆盖 3 个独立 benefit evalset 且结论一致。
- `wrong_scope_count=0`，`citation_incomplete_count=0`，`citation_unresolvable_count=0`。
- expected-doc / recall@5 稳定提升，建议提升幅度 > 10%，且不是由 out-of-scope / corpus-gap 样本制造。
- hybrid p95 不超过 dense-only 的 1.3 倍；真实 rerank 增量 p95 < 500ms。
- 形成 retrieval default rollback 记录草案后，才允许提出默认切换申请。

当前状态：

```text
evalset_expansion_status = candidate_review_done_bc_probe_no_upgrade
formal_evalsets_created = partial
created_evalsets = department_rag_retrieval_content_recall_20q.jsonl
deferred_evalsets = sparse_hybrid_lift_15q, rerank_rank_lift_15q
schema_support_check = passed
content_recall_20q_eval_status = passed_no_lift_evidence
bc_shadow_probe_status = passed_no_formal_upgrade
benefit_b_effective_lift_count = 0
benefit_c_effective_rank_lift_count = 0
query_rewrite_shadow_status = next_stage_expression_gap_eval_required
```

人工 review 结论：

- Benefit-A content recall 20q 已通过人工 review，并创建正式 JSONL：`evals/knowledge_base/evalsets/department_rag_retrieval_content_recall_20q.jsonl`。
- 创建后只做 schema / corpus support 校验：20 行、`P26-A-001` 到 `P26-A-020` 唯一、目标 doc 均 indexed、关键词缺失数为 0。
- 2026-06-09 已复跑 A-20q 普通 department RAG eval：20/20 passed，`not_ready=0`、`wrong_scope_count=0`、`citation_unresolvable_count=0`、`all_source_ref_resolvable=true`。
- 2026-06-09 已复跑 A-20q 四模式 comparison：dense-only / sparse-only / hybrid / hybrid-rerank 均 expected-doc 20/20，四模式均无 not-ready、wrong-scope、citation-incomplete；`hybrid_rerank` 仍为 disabled (`disabled=55`)。
- 因 dense-only 已 20/20，且 rerank 未真实生效，A-20q 只能证明 content recall evalset 健康，不能证明 Benefit-B/C 有收益。
- 2026-06-09 已跑 Benefit-B/C shadow probe，报告位于 ignored `evals/knowledge_base/reports/checklist3_p26_bc_shadow_probe_20260609.json` 和 `.md`。
- Benefit-B sparse/hybrid lift 15q：`effective_lift_count=0`，15/15 verdict 为 `no_lift`，没有出现 dense miss 后由 sparse/hybrid 捞回的样本；不创建正式 JSONL，降级为 `lexical_lift_observation_report`。
- Benefit-C rerank rank_lift 15q：受控进程内真实 `rerank_service.enabled=True`，`hybrid_rerank.applied=41`，但 `effective_rank_lift_count=0`；14/15 为 `no_rank_lift`，1/15 为 `not_true_rerank`；不创建正式 JSONL，降级为 `rank_lift_observation_report`。
- B/C probe 无 blocker，但 `status=passed_no_formal_upgrade`；这只说明候选检查闭环完成，不说明 hybrid/rerank 有稳定收益。

---

## 8. P3：PDF 工具 local 观察与更大范围启用

优先级：跟随 B4 local 观察窗口。

当前 local G7 已完成，但还处于观察期。

### P3.1 local recheck

动作：

当前已批准的 B4 local G7 于 2026-06-09 启用。原定复核日是 2026-06-11，但 owner 已明确取消等待 block，允许在 2026-06-09 立即执行 local recheck；后续恢复执行时，按 owner 指定时间或“G7 启用后 48-72 小时”复核，不把固定日期当成硬阻塞。

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run pytest tests/test_pdf_agent_tool_smoke.py tests/test_pdf_document_tools.py tests/test_checklist2_production_defaults.py -q --no-cov
```

并重跑或等价验证：

- local `.env` 生效时 PDF 工具对 admin/craft_dept 可见。
- 授权 page/table 调用成功。
- denied page/table 仍然 `permission_denied` 且 no-leak。
- `app/config.py` 默认仍是 `False`。

通过条件：

- local 观察无异常。
- rollback drill 仍可执行。

当前本地证据：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run pytest tests/test_pdf_agent_tool_smoke.py tests/test_pdf_document_tools.py tests/test_checklist2_production_defaults.py -q --no-cov
```

当前结果：`15 passed`。本次提前复核只证明 local G7 最小范围仍安全，不扩大到 staging / production，也不改变 `app/config.py` 默认值。

失败处理：

- 如果工具不可见、授权失败、无权限泄露或 source_ref 不可解析，按 `docs/B4 PDF Agent 工具生产启用与回滚记录.md` 回滚 local `.env`。

### P3.2 staging / production 启用条件

任何 staging / production 启用必须重新填写启用记录：

- 环境
- 批准人
- 负责人
- 用户范围
- 部门 / KB 范围
- 文档范围
- 功能范围
- 观测窗口
- rollback 命令
- rollback 验证报告

禁止：

- 拿 local G7 记录直接替代 staging / production 记录。
- 一次性开放所有用户、所有 KB、所有 indexed PDF。

---

## 9. P4：Memory 深化 backlog

优先级：低于 P0/P1/P2。只登记，不在本清单第一轮实现。

可选方向：

- durable memory 候选从 `MemoryEvidenceStore` L0 evidence 回溯。
- session archive 到 long-term memory 的人工 review 流程。
- memory guidance 与 RAG citation 的 UI/日志区分。
- owner 级 memory export / deletion / deprecation。
- memory shadow 报告进入统一 eval dashboard。

边界：

- Memory 不是 RAG 文档证据。
- Memory 不是 PDF source_ref。
- Memory 不是 query rewrite 的默认输入。

---

## 10. 执行顺序

推荐顺序：

1. **S3-0：B4 local 观察复核**
   - 状态：已按 owner 要求在 2026-06-09 提前复核，`15 passed`。
   - 目标：确认 local G7 启用仍安全，rollback 仍有效。
   - 结论：S3-0 不再阻塞清单 3 后续工作；后续仍可做日常观察，但不能把 local 结果当成 staging / production 启用依据。

2. **S3-P0：评测护栏加固**
   - 下一步先做 eval coverage / inventory：盘点现有 PDF/E1 样本覆盖了哪些 KB、doc、source_ref、denied no-leak、wrong-scope 场景。
   - 再按真实缺口扩展 PDF/E1 系统能力评测，避免机械凑题。
   - Report freshness 规则第一切片已完成，后续扩展样本要继续接入同一 gate 汇总。

3. **S3-P1：C4/C5 生产门槛**
   - TTL cleanup runner。
   - DB size report。
   - 长会话 / 长日志 shadow。
   - result_ref 审计回查。
   - L0 evidence retention / archive 策略。

4. **S3-P2：RAG shadow**
   - retrieval mode comparison 扩展。
   - query rewrite shadow。
   - rerank shadow。
   - 默认切换门禁。

5. **S3-P3：PDF 更大范围启用**
   - 只有 local 观察和 P0 gate 稳定后才申请。

6. **S3-P4：Memory 深化**
   - 作为单独后续阶段，不夹在 P0/P1/P2 中。

可并行项：

- P1 的 cleanup/report 可以和 P2 的 shadow report 并行。
- P2 的设计和只读 shadow report 可以和 P1 并行。
- P0 eval 扩展可以和 P1/P2 并行设计，但 P1/P2 的 active 结论必须依赖 P0 gate；P2 active 还必须等 P1 的 TTL/capacity/audit 门禁不阻塞。

不可并行项：

- query rewrite active 不能早于 query rewrite shadow。
- hybrid/rerank 默认切换不能早于 dense/hybrid/rerank 对比报告。
- staging/production PDF 启用不能早于 local 观察复核。
- memory/offload active 不能早于 TTL/capacity/L0 retention/audit 回查门禁。

---

## 11. 验收总表

| 阶段 | 通过条件 | 阻塞失败 |
|---|---|---|
| S3-0 B4 local recheck | local PDF tools 可见、授权成功、denied no-leak、source_ref 可解析、rollback 可用 | permission bypass、metadata leak、工具不可回滚 |
| S3-P0 Eval | permission/scope/citation/PDF gates 可复跑，report freshness 清楚 | wrong_scope、citation_unresolvable、no-leak fail、旧报告冒充当前事实 |
| S3-P1 Memory/offload gates | cleanup dry-run/apply、安全容量报告、长会话/长日志 shadow、result_ref 可回查、L0 retention 有策略 | summary-only offload、跨 owner 读原文、无 TTL/容量/L0 retention 门禁 |
| S3-P2 RAG shadow | rewrite/hybrid/rerank 都是 shadow，不改主链路，收益和退化分类清楚，latency/cost 门槛明确 | 默认模式误改、protected terms 丢失、wrong_scope 增加、收益来自 corpus gap/out_of_scope |
| S3-P3 PDF rollout | 每个环境有单独批准、范围、观测、回滚记录 | local 记录冒充生产记录、全量无门禁启用 |
| S3-P4 Memory backlog | 只登记或单独开阶段 | 和当前门禁混做，导致 active 边界变模糊 |

---

## 12. 需要更新的文件

本清单创建时必须同步：

- `PROJECT_STATE.md`
- `docs/rag_fusion_development_record.md`

后续实现阶段按实际改动再同步：

- `docs/B4 PDF Agent 工具生产启用与回滚记录.md`
- `docs/B4 真实 indexed-PDF smoke 与生产启用门禁清单.md`
- `docs/记忆_ragpdf_并行开发_执行步骤清单2.md` 只作为历史完成记录，不继续追加新任务。

---

## 13. 复核命令

文档创建后：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
git diff --check
```

如果只改文档，不需要跑 Python 单测。

如果后续开始实现 S3-P0/P1/P2：

- 先写目标阶段的 targeted tests 或 eval report。
- 再实现。
- 最后跑对应 targeted tests、eval、`ruff --select F,E9,I`、`compileall` 和 `git diff --check`。

---

## 14. 给小白解释

清单 2 像是把几个新工具装到了系统里，但大部分工具默认还锁着：

- 记忆系统有了，但不能随便塞进 AI 回答里。
- AIOps 长日志可以存起来，但不能只留摘要丢掉原文。
- PDF 工具本地能读页和抽表，但不能直接全公司上线。
- RAG 有 hybrid、rerank、rewrite 的方向，但不能一拍脑袋改默认搜索方式。

清单 3 就是上生产前的“试车场”和“安全门”：

- 先在不影响真实回答的 shadow 模式里观察。
- 再用评测证明没有权限泄露、没有串库、引用能回查。
- 再准备好出问题怎么关掉。
- 最后才允许小范围打开。

所以它不是在说“继续加更多魔法”，而是在说：“现在开始认真证明这些能力能不能长期安全运行。”

---

## 15. 阶段性总结

当前阶段状态：

```text
checklist3_phase_status = phase_closeout_done
next_primary_track = checklist3_closed; next_stage_corpus_expansion_and_query_expression_eval
default_switch_eligibility = not_eligible_for_default_switch
```

### 15.1 评测代表性边界

清单 3 的评测不是完整真实聊天验收。

本阶段评测实际覆盖：

- `run_department_rag_eval.py` 调用 `retrieval_service.retrieve()`，根据 `expected_doc_ids`、`expected_answer_keywords`、`source_ref`、scope 和 citation 规则评分。
- `retrieval_mode_comparison_report.py` 调用同一检索服务，对 dense-only / sparse-only / hybrid / hybrid-rerank 的召回、排序、source_ref、wrong_scope 和 latency 做对比。
- `checklist3_p26_bc_shadow_probe_report.py` 复用四模式 comparison；Benefit-C 只在 report 进程内临时设置 `rerank_service.enabled=True`，并在结束后恢复。
- `RerankService` 当前使用本地 `LexicalRerankScorer`，不是外部 LLM reranker。

本阶段评测没有覆盖：

- 没有调用 LLM 生成最终自然语言答案。
- 没有用 LLM-as-judge 判断回答质量。
- 没有覆盖真实用户多轮追问、上下文记忆注入后的回答质量、工具编排、SSE 前端体验或线上并发。
- 没有覆盖大规模、多部门、多格式生产语料分布。

因此，本阶段结论只能代表“当前 indexed 小语料上的 retrieval / rerank / source_ref / 权限门禁表现”，不能代表完整生产 RAG 对话质量。它可以作为生产门禁的一层证据，但不能单独作为 active 或默认切换依据。

完成情况：

| 阶段 | 状态 | 成果 | 当前边界 |
|---|---|---|---|
| S3-0 | 完成 | B4 local recheck 提前通过，local G7 最小范围仍安全 | 不能替代 staging / production 启用记录 |
| S3-P0 | 完成 | gate freshness、coverage inventory、PDF artifact inventory | PDF eval 仍 `corpus_limited` |
| S3-P1 | 完成 | cleanup runner、DB size、长会话 shadow、长日志 offload shadow | C4/C5 仍 default-off，不能 active |
| S3-P2.1 | 完成 | RAG shadow inventory | 只读盘点，不改默认 |
| S3-P2.3 | 完成 | 18q 四模式 retrieval comparison，修复 rerank disabled top-k 契约 | 18q 只是 shadow baseline |
| S3-P2.4 | 完成 | rerank disabled 原因解释 + synthetic active/fallback shadow | 不证明真实 rerank 质量收益 |
| S3-P2.5 | 完成 | 默认切换门禁文档化，结论为不具备切换资格 | 默认仍保持 dense-only / rewrite off / rerank off |
| S3-P2.6 | 完成当前证据闭环 | Benefit-A 20q 已转正式 JSONL并复跑通过；B/C shadow probe 完成但无正式升级证据 | A-20q 未证明 lift；B/C 降级 observation |
| S3-P3 | 未开始 | PDF 更大范围启用 | 需要单独审批、范围、观察、回滚 |
| S3-P4 | backlog | Memory 深化 | 不夹在当前门禁阶段里做 |

关键决策：

1. 默认检索不切换：
   - `rag_default_retrieval_mode=dense_only`
   - `rag_query_rewrite_mode=off`
   - `rerank_enabled=false`

2. Query Rewrite 另开新阶段：
   - 清单 3 内不实现 query rewrite active，也不修改 `rag_query_rewrite_mode=off`。
   - 下一阶段要专门分析“用户表达不好”的情况，例如口语化、缩写、错别字、别名、跨中英术语、症状描述不含标准文档词、隐含部门/文档范围。
   - 先做 expression-gap eval，再决定 query rewrite shadow 方案；不能直接把 rewrite 接入真实回答链路。

3. P2.6 人工 review 已采用保守分流：
   - Benefit-A content recall 20q 已创建正式 JSONL。
   - A-20q 普通 eval 20/20；四模式 expected-doc 均 20/20，因此没有证明 sparse/hybrid/rerank 相对 dense-only 的收益。
   - Benefit-B/C shadow probe 已完成：B 组 0/15 证明 sparse/hybrid lift，C 组 0/15 证明真实 rerank rank-lift，因此暂不创建正式 JSONL。
   - 不为了凑样本拆题或重复包装同一证据。

4. PDF 扩展仍受 corpus 限制：
   - 当前只有 1 个 indexed PDF 可作为 page/table/source_ref 成功样本。
   - pending 环保/合规 PDF 已明确 `rejected_current_kb`，不能拿来证明当前 oncall/craft/RAG 小样本质量。

5. C4/C5 具备了第一层生产门槛，但还不是 active：
   - TTL / capacity / long-session / long-log shadow 已有报告。
   - 仍缺真实长会话、真实长日志、scheduler/L0 retention、回滚记录等更长期证据。

阶段性结论：

- 清单 3 的 P0/P1/P2 主体已经完成，可以作为当前安全基线封存。
- Benefit-B/C 当前 probe 没有证明稳定 lift / rank_lift，因此不创建正式 B/C evalset。
- 只有正式扩充 evalset 复跑后，才讨论 hybrid / rerank active 或默认切换。
- Query Rewrite 仍然要做，但属于清单 3 之后的新阶段：先评测用户表达缺口，再实现 shadow，最后才可能申请 active。

P2.6 设计文档：

- `docs/RAG_PDF_Memory_P2.6_evalset扩充coverage_matrix设计.md`
- `docs/RAG_PDF_Memory_P2.6_evalset候选样本草案.md`
- `docs/RAG_PDF_Memory_P2.6_evalset候选样本人工review结论.md`

P2.6 当前正式 JSONL：

- `evals/knowledge_base/evalsets/department_rag_retrieval_content_recall_20q.jsonl`

---

## 16. 清单 3 之后的建议

清单 3 到这里收口，不继续在当前 3 个 indexed 文档上硬推 B/C。

下一阶段建议拆成两条线：

1. Hybrid / rerank 价值证明新阶段
   - 先扩充到更复杂的 10+ indexed 文档。
   - 重新设计 Benefit-B / Benefit-C 候选，不沿用本轮已经证明无收益的候选。
   - 重新跑 dense-only / sparse-only / hybrid / true-rerank comparison。
   - 只有出现稳定 dense miss -> sparse/hybrid recover，或 true rerank rank-lift，才创建正式 B/C evalset。

2. Query Rewrite 表达缺口评测新阶段
   - 先收集用户表达不佳样本，不直接实现 active rewrite。
   - 样本类别至少覆盖：口语化问法、错别字/别名、缩写、中文英文混用、症状描述不含标准术语、隐含部门/文档范围、过宽问题需要 scope 锁定。
   - 对比原 query 与 rewrite candidate 的 expected-doc 命中、wrong_scope、citation/source_ref、latency、rewrite_harm_count。
   - Query Rewrite shadow 必须保留 protected terms、KB/doc scope、用户原始 query 和 rewrite trace。
   - 若 rewrite 生成使用 LLM，报告必须明确记录 `uses_llm_for_rewrite=true`；若不用 LLM，必须记录规则/词典来源。无论哪种，rewrite 结果都不能先替换真实检索 query。

下一阶段治理文档：

- `docs/RAG_QueryRewrite_语料扩充与表达缺口评测清单4.md`
- 清单 4 已把上述两条线合并成新的执行门禁：先做 10+ indexed 文档的 corpus review / import gate，再做 expression-gap eval，最后才允许 Query Rewrite shadow。

默认配置继续保持：

```text
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
default_switch_eligibility = not_eligible_for_default_switch
```
