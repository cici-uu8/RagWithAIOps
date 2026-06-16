# B4 真实 indexed-PDF smoke 与生产启用门禁清单

日期：2026-06-09

适用范围：B4 PDF Agent 工具链生产启用前的真实数据 smoke、评测复跑、启用记录和回滚门禁。

当前结论：

- B4 模块级开发已经完成：`pdf.read_document_page` / `pdf.extract_document_table` 已通过 `ToolGateway` 默认关闭接入。
- 本清单不是继续实现 B4 工具本体，也不是把 staging / production 开关打开。
- 本清单的目标是回答一个更具体的问题：这些工具在真实 indexed PDF 上能否安全启用。
- 截至 2026-06-09，B4-G1 到 B4-G6 的本地门禁已完成，结论见第 13.4 节；B4-G7 已按用户批准在 local `.env` 最小范围启用，记录见 `docs/B4 PDF Agent 工具生产启用与回滚记录.md`。staging / production 未启用。

---

## 1. 背景

清单 2.1 已完成 B4 的 default-off 接入：

- 默认配置仍是 `pdf_agent_tools_enabled=False`。
- 工具只在显式启用时注册到 local Agent tool gateway。
- 模型可见参数只有 `doc_id`、`page`、`table_id`。
- `RequestContext` 由后端 `ToolGateway` 注入，模型不能伪造。
- artifact 读取前必须经过 `DocumentAccessService.can_read_document(context, document)`。
- 无权限返回固定错误，不泄露标题、正文、表格内容或 artifact path。

在本清单启动时，这只证明“模块行为和权限单测”成立，还没有证明“真实 indexed PDF 数据”能安全运行。

所以 B4 的生产启用前需要四类证据：

1. 真实 indexed PDF smoke：真实文档、真实 metadata、真实 artifact、真实权限上下文。
2. 无权限不泄露：跨部门或无授权用户拿同一个 `doc_id/page/table_id` 不能得到内容和元数据。
3. 评测复跑：E1 permission/scope/citation eval 和 PDF page/table/source_ref eval 仍然通过。
4. 启用与回滚记录：谁启用、在哪个环境启用、如何回滚、回滚后如何验证。

当前状态：第 1-3 类证据已由 B4-G1 到 B4-G6 补齐；第 4 类证据已由 B4-G7 在 local 环境最小范围补齐。任何 staging / production 启用仍需要单独审批和记录。

---

## 2. 硬边界

| 边界 | 必须保持 | 禁止事项 |
|---|---|---|
| 默认开关 | `pdf_agent_tools_enabled=False` | 禁止把默认值改成 `True` 后提交 |
| smoke 启用 | 只能在测试进程、smoke runner 或指定测试环境里临时启用 | 禁止用 smoke 结果直接代表生产已启用 |
| 工具入口 | 必须走 `ToolGateway` / `ToolExecutionFacade` | 禁止直接调用 provider 私有方法作为唯一验收 |
| 权限校验 | artifact 读取前必须调用 `DocumentAccessService.can_read_document(...)` | 禁止用模型传入的 `doc_id/page/table_id` 绕过后端权限 |
| 模型参数 | 只暴露 `doc_id`、`page`、`table_id` | 禁止暴露 `RequestContext`、`owner_id`、部门、权限对象、artifact path |
| 错误响应 | 无权限只能返回 `permission_denied` 等安全错误 | 禁止在错误中泄露文件名、标题、正文、表头、行数据、路径 |
| source_ref | 成功读取页或表时必须能回到真实文档证据 | 禁止把不可解析的 fallback 当成生产通过 |
| 表格 smoke | 只对确实有表的 PDF 要求表格成功 | 禁止要求每个 indexed 文档都必须有表 |

通过本清单后也不自动扩大启用范围。当前只批准 local `.env` 最小范围启用；staging / production 仍需要明确批准，并在目标环境单独设置 `pdf_agent_tools_enabled=True`。

---

## 3. 当前前置事实

截至本清单编写时，当前 import state 中 indexed 资产包括：

| doc_id | kb_id | 文件 | B4 smoke 角色 |
|---|---|---|---|
| `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `craft_dept` | `线上故障处理_现场设备工艺版.pdf` | 必须覆盖的真实 indexed PDF |
| `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `process_digital_dept` | `2024_人民网聚焦中车长客数字化转型成果.md` | RAG/E1 回归样本，不作为 PDF 表格成功样本 |
| `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `process_digital_dept` | `superbiz_oncall_handbook.md` | RAG/E1 回归样本，不作为 PDF 表格成功样本 |

如果后续新增 indexed PDF，本清单的 PDF smoke matrix 要扩展到新 PDF。非 PDF 文档不要求 `extract_document_table` 成功。

---

## 4. 前置核对

### 4.1 工作区核对

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
git status --short
```

通过条件：

- 只允许存在与本轮 B4 smoke 工作相关的改动。
- 已知无关本地草稿或资产不纳入本轮提交。

### 4.2 默认关闭核对

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run pytest tests/test_pdf_document_tools.py tests/test_checklist2_production_defaults.py -q --no-cov
```

通过条件：

- PDF 工具默认不注册。
- `pdf_agent_tools_enabled` 仍为 `False`。
- 模型可见 schema 不包含 `RequestContext`、`owner_id`、权限对象或 artifact path。
- 现有无权限 no-leak 单测通过。

### 4.3 indexed PDF 清单核对

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python - <<'PY'
import json
from pathlib import Path

state_path = Path("data/knowledge_ingestion/current_import_state.json")
payload = json.loads(state_path.read_text(encoding="utf-8"))
rows = payload.get("documents") or payload.get("items") or payload.get("assets") or []
if isinstance(rows, dict):
    rows = list(rows.values())

for row in rows:
    status = row.get("status") or row.get("index_status") or row.get("import_status")
    file_name = row.get("source_file") or row.get("file_name") or row.get("filename") or ""
    if status == "indexed":
        print(
            row.get("doc_id") or row.get("document_id"),
            row.get("kb_id"),
            file_name,
        )
PY
```

通过条件：

- 至少能看到 `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` 是 indexed。
- 如果没有 indexed PDF，B4 生产启用阻塞，不能用 synthetic artifact 代替真实 smoke。

---

## 5. Smoke Runner 要求

本清单建议新增或复用一个 runner，例如：

```text
evals/knowledge_base/pdf_agent_tool_smoke.py
```

如果该脚本尚不存在，下一步开发应先实现它。本清单不声称该脚本当前已经存在。

### 5.1 最小输入参数

```bash
uv run python -m evals.knowledge_base.pdf_agent_tool_smoke \
  --doc-id doc_27b282ca-97c3-5170-af0a-282f2e9122a1 \
  --valid-page 1 \
  --invalid-page 9999 \
  --table-id t_expected_if_known \
  --authorized-user admin \
  --denied-user user-denied \
  --output-json evals/knowledge_base/reports/pdf_agent_tool_smoke_20260609.json \
  --output-md evals/knowledge_base/reports/pdf_agent_tool_smoke_20260609.md
```

说明：

- `--table-id` 只有在真实 artifact 中存在稳定 table_id 时才必填。
- 如果真实 PDF 没有表，runner 应把表格成功场景记为 `not_applicable`，不能记为失败。
- runner 可以在进程内临时构造 `PdfDocumentToolProvider(enabled=True)`，但不能修改并提交 `app/config.py` 默认值。

### 5.2 Runner 必须走的代码路径

Runner 必须通过以下链路调用工具：

```text
RequestContext
  -> ToolExecutionFacade.execute(...)
  -> ToolGateway.execute(...)
  -> PdfDocumentToolProvider.execute_tool_with_context(...)
  -> DocumentAccessService.can_read_document(...)
  -> blocks.json / tables.json
```

禁止把 `PdfDocumentToolProvider._read_document_page(...)` 或 `_extract_document_table(...)` 的直接调用结果作为唯一验收。

### 5.3 Runner 最小报告字段

JSON 报告至少包含：

```json
{
  "status": "passed_or_failed",
  "doc_id": "doc_27b282ca-97c3-5170-af0a-282f2e9122a1",
  "default_enabled": false,
  "temporary_smoke_enabled": true,
  "schema_has_no_context_or_owner": true,
  "authorized_page_read": {
    "status": "success",
    "content_non_empty": true,
    "source_refs_resolvable": true
  },
  "authorized_table_extract": {
    "status": "success_or_not_applicable",
    "rows_non_empty": true,
    "source_refs_resolvable": true
  },
  "invalid_page": {
    "status": "error",
    "error": "page_out_of_range"
  },
  "invalid_table": {
    "status": "error_or_not_applicable",
    "error": "table_not_found"
  },
  "denied_page_read": {
    "status": "error",
    "error": "permission_denied",
    "leak_detected": false
  },
  "denied_table_extract": {
    "status": "error_or_not_applicable",
    "error": "permission_denied",
    "leak_detected": false
  }
}
```

如果 `source_refs` 只返回 `artifact_source=blocks_json` 这类不可解析 fallback，不能算 `source_refs_resolvable=true`。

---

## 6. Smoke Matrix

| 编号 | 场景 | 输入 | 期望 | 失败是否阻塞 |
|---|---|---|---|---|
| B4-S1 | 默认关闭 | `pdf_agent_tools_enabled=False` | ToolGateway 不列出 PDF 工具 | 是 |
| B4-S2 | schema 安全 | list tools | schema 只有 `doc_id/page/table_id` | 是 |
| B4-S3 | 有权限读有效页 | indexed PDF + valid page | `success`，content 非空，source_refs 可解析 | 是 |
| B4-S4 | 有权限读无效页 | indexed PDF + out-of-range page | `page_out_of_range`，不返回 artifact path | 是 |
| B4-S5 | 无权限读有效页 | denied user + same doc/page | `permission_denied`，不泄露标题/正文/路径 | 是 |
| B4-S6 | 有权限抽有效表 | indexed PDF + known table_id 或 table page | 有表时 `success`，rows/markdown 非空 | 仅有表时阻塞 |
| B4-S7 | 有权限抽不存在表 | invalid table_id | `table_not_found`，不返回内部路径 | 是 |
| B4-S8 | 无权限抽表 | denied user + same doc/table | `permission_denied`，不泄露表头/行数据/路径 | 有表时阻塞 |
| B4-S9 | PDF page/table eval | current PDF sample | page/table/source_ref 全通过 | 是 |
| B4-S10 | E1 permission eval | permission isolation 10q | 10/10，`permission_filtered_passed=10` | 是 |
| B4-S11 | E1 scope eval | scope lock 10q | 不出现跨 scope 命中或错误引用 | 是 |
| B4-S12 | E1 citation eval | citation accuracy 10q | citation/source_ref 可解析 | 是 |

---

## 7. 评测复跑命令

### 7.1 E1 permission isolation

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_permission_isolation_10q.jsonl \
  --report evals/knowledge_base/reports/department_rag_permission_isolation_b4_smoke_20260609.json
```

通过条件：

- `not_ready=0`
- `passed=10`
- `permission_filtered_passed=10`

### 7.2 E1 scope lock

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_scope_lock_10q.jsonl \
  --report evals/knowledge_base/reports/department_rag_scope_lock_b4_smoke_20260609.json
```

通过条件：

- `not_ready=0`
- 不允许出现 wrong-scope evidence。
- 如果仍有内容题 answer_wrong，必须确认不是 B4 工具引起的权限或 citation 退化。

### 7.3 E1 citation accuracy

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_citation_accuracy_10q.jsonl \
  --report evals/knowledge_base/reports/department_rag_citation_accuracy_b4_smoke_20260609.json
```

通过条件：

- `not_ready=0`
- `citation_unresolvable_count=0`
- source_ref 可解析。

### 7.4 PDF page/table/source_ref eval

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.pdf_page_table_eval_report \
  --samples evals/knowledge_base/evalsets/pdf_page_table_eval_current_failure_20260608.json \
  --output-json evals/knowledge_base/reports/pdf_page_table_eval_b4_smoke_20260609.json \
  --output-md evals/knowledge_base/reports/pdf_page_table_eval_b4_smoke_20260609.md
```

通过条件：

- `artifact_missing_count=0`
- `page_accuracy_passed=total`
- `source_ref_resolvable_passed=total`
- 对有表样本，`table_presence_passed=total`

---

## 8. 失败分类与处理

| 失败类型 | 表现 | 处理 |
|---|---|---|
| `tool_not_listed_when_enabled` | 临时启用后 gateway 看不到 PDF 工具 | 查 `build_local_agent_tool_gateway()` / provider 注册 |
| `default_opened` | 默认配置变成 `True` | 立即回滚配置，阻塞生产启用 |
| `schema_leak` | schema 出现 context、owner、权限、path | 收紧 `ToolDefinition.input_schema` |
| `permission_bypass` | 无权限用户读到页或表 | 硬阻塞，修 `DocumentAccessService` 调用顺序 |
| `metadata_leak_on_denied` | denied 错误含标题、正文、表格值、artifact path | 硬阻塞，统一错误响应 |
| `source_ref_unresolvable` | 成功结果没有可解析 source_ref | 阻塞，修 metadata/chunk/source_ref 映射 |
| `artifact_missing` | indexed PDF 找不到 blocks/tables artifact | 阻塞，回到 PDF artifact validation |
| `page_number_mismatch` | 返回页码和 source_ref 页码不一致 | 阻塞，修 blocks/chunks 页码映射 |
| `table_not_found` | 目标 PDF 明确有表但工具找不到 | 阻塞，修 table_id/page 选择逻辑 |
| `table_not_applicable` | 目标 PDF 本来无表 | 不阻塞，但必须在报告里写清楚 |
| `eval_regression` | E1 或 PDF eval 退化 | 阻塞，定位是否由 B4 工具、权限或 source_ref 引起 |

安全失败优先级最高。只要出现 `permission_bypass` 或 `metadata_leak_on_denied`，停止启用流程，不继续讨论效果。

---

## 9. 生产启用记录要求

只有全部 smoke 和 eval 通过后，才允许提出生产启用申请。申请记录至少写入 `PROJECT_STATE.md`，并包含：

| 字段 | 要求 |
|---|---|
| 启用环境 | local / staging / production，必须写清 |
| 启用配置 | `pdf_agent_tools_enabled=True` 的设置位置 |
| 启用范围 | 哪些用户、部门、KB、doc_id 可见 |
| smoke 报告 | JSON/MD 报告路径 |
| E1 eval 报告 | 三组报告路径和摘要 |
| PDF eval 报告 | page/table/source_ref 报告路径和摘要 |
| 风险确认 | 权限、source_ref、表格、日志泄露检查结果 |
| 回滚方式 | 如何把 `pdf_agent_tools_enabled` 改回 `False`，是否需要重启服务 |
| 回滚验证 | 回滚后跑哪些命令确认工具不再注册 |
| 负责人和日期 | 谁批准、谁执行、何时复核 |

生产启用记录必须明确写一句：

```text
B4 PDF Agent tools were enabled only after indexed-PDF smoke and E1/PDF eval gates passed. Default source code config remains pdf_agent_tools_enabled=False.
```

---

## 10. 回滚门禁

回滚不是“把开关关掉”一句话。最小回滚流程：

1. 将目标环境的 `pdf_agent_tools_enabled` 改回 `False`。
2. 重启或刷新对应服务进程。
3. 运行默认关闭测试。

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run pytest tests/test_pdf_document_tools.py tests/test_checklist2_production_defaults.py -q --no-cov
```

4. 用同一用户再次 list tools，确认 `pdf.read_document_page` 和 `pdf.extract_document_table` 不可见。
5. 在 `PROJECT_STATE.md` 记录回滚时间、原因、验证命令和结果。

如果回滚后工具仍可见，必须当作配置或服务刷新失败处理，不能继续让用户访问。

---

## 11. 最小完成定义

本清单完成需要同时满足：

- 新增或复用 B4 indexed-PDF smoke runner，并生成 JSON/MD 报告。
- 真实 indexed PDF `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` 的授权页读取通过。
- 无权限页读取不泄露标题、正文、路径或可推断内部位置的信息。
- 如目标 PDF 有表，授权抽表通过，无权限抽表不泄露表头或行数据。
- invalid page/table 返回稳定安全错误。
- `tests/test_pdf_document_tools.py` 和 `tests/test_checklist2_production_defaults.py` 通过。
- E1 三组 eval 复跑，未出现权限、scope、citation 退化。
- PDF page/table/source_ref eval 复跑通过。
- `PROJECT_STATE.md` 写入启用或继续禁用的结论。
- `git diff --check` 通过。

即使全部满足，也只能说明“具备申请启用条件”。是否真正打开生产开关，需要用户或项目 owner 另行批准。

---

## 12. 开发顺序

建议顺序：

1. B4-G1：补 smoke runner，先只跑 default-off/schema/authorized page。
2. B4-G2：加入 denied page no-leak。
3. B4-G3：加入 table success / table not applicable / denied table no-leak。
4. B4-G4：跑 PDF page/table/source_ref eval。
5. B4-G5：跑 E1 permission/scope/citation eval。
6. B4-G6：更新 `PROJECT_STATE.md`，记录“继续禁用”或“申请启用”的结论。
7. B4-G7：如申请启用，补启用和回滚记录，再单独执行目标环境配置。

不要把 B4-G7 和 runner 开发混在一个提交里。工具验证和生产启用必须分开留痕。

---

## 13. 当前执行结果

### 13.1 B4-G1（2026-06-09）

已完成：

- 新增 `evals/knowledge_base/pdf_agent_tool_smoke.py`。
- 新增 `tests/test_pdf_agent_tool_smoke.py`。
- runner 通过真实 `ToolExecutionFacade -> ToolGateway -> PdfDocumentToolProvider -> DocumentAccessService` 路径执行，不直接调用 provider 私有方法作为验收。
- runner 在进程内临时启用 `PdfDocumentToolProvider(enabled=True)`，但源代码默认配置仍保持 `pdf_agent_tools_enabled=False`。
- G2/G3 场景现在明确输出 `not_run`，不假装 denied/no-leak 或 table smoke 已完成。

真实 indexed PDF smoke：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.pdf_agent_tool_smoke \
  --doc-id doc_27b282ca-97c3-5170-af0a-282f2e9122a1 \
  --valid-page 1 \
  --invalid-page 9999 \
  --table-id t_expected_if_known \
  --authorized-user admin \
  --denied-user user-denied \
  --output-json evals/knowledge_base/reports/pdf_agent_tool_smoke_b4_g1_20260609.json \
  --output-md evals/knowledge_base/reports/pdf_agent_tool_smoke_b4_g1_20260609.md
```

结果：

| 字段 | 值 |
|---|---|
| status | `passed` |
| default_enabled | `false` |
| default_tools_visible | `[]` |
| visible_pdf_tool_ids | `pdf.extract_document_table`, `pdf.read_document_page` |
| schema forbidden hits | `[]` |
| authorized page read | `success` |
| content chars | `1277` |
| source_ref_count | `6` |
| source_refs_resolvable | `true` |

验证：

```bash
uv run pytest tests/test_pdf_agent_tool_smoke.py -q --no-cov
uv run python -m compileall -q evals/knowledge_base/pdf_agent_tool_smoke.py tests/test_pdf_agent_tool_smoke.py
uv run ruff check evals/knowledge_base/pdf_agent_tool_smoke.py tests/test_pdf_agent_tool_smoke.py --select F,E9,I
```

通过情况：

- `tests/test_pdf_agent_tool_smoke.py`：3/3 passed。
- compileall：通过。
- ruff `F,E9,I`：通过。

G1 当时仍未完成：

- B4-G2：denied page no-leak。
- B4-G3：table success / not applicable / denied table no-leak。
- B4-G4：PDF page/table/source_ref eval 复跑。
- B4-G5：E1 permission/scope/citation eval 复跑。
- B4-G6/G7：启用或继续禁用结论、生产启用申请和回滚记录。

结论：B4-G1 已通过；其中 B4-G2 已在 13.2 补齐，生产 active 仍然禁止。

### 13.2 B4-G2（2026-06-09）

已完成：

- `evals/knowledge_base/pdf_agent_tool_smoke.py` 将 stage 升级为 `B4-G2`。
- 新增 invalid page 安全错误场景：admin 用户读取 `--invalid-page 9999`，必须返回 `page_out_of_range` 且不泄露内部信息。
- 新增 denied page no-leak 场景：普通 `roles=["user"]` 用户使用同一个 `doc_id/page` 调用 `pdf.read_document_page`。
- 新增泄露检测：文件名、原始路径、artifact 路径、`blocks.json`、`tables.json`、正文片段、source_ref/chunk/parser 字段只要出现在 denied 响应中，就判定 `leak_detected=true`。
- `doc_id` 是调用方输入参数，不单独作为泄露词；其他内部证据仍然按泄露处理。

真实 indexed PDF smoke：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.pdf_agent_tool_smoke \
  --doc-id doc_27b282ca-97c3-5170-af0a-282f2e9122a1 \
  --valid-page 1 \
  --invalid-page 9999 \
  --table-id t_expected_if_known \
  --authorized-user admin \
  --denied-user user-denied \
  --output-json evals/knowledge_base/reports/pdf_agent_tool_smoke_b4_g2_20260609.json \
  --output-md evals/knowledge_base/reports/pdf_agent_tool_smoke_b4_g2_20260609.md
```

结果：

| 字段 | 值 |
|---|---|
| status | `passed` |
| stage | `B4-G2` |
| default_enabled | `false` |
| default_tools_visible | `[]` |
| authorized page read | `success` |
| content chars | `1277` |
| source_ref_count | `6` |
| source_refs_resolvable | `true` |
| invalid page status | `error` |
| invalid page error | `page_out_of_range` |
| invalid page leak_detected | `false` |
| denied page status | `error` |
| denied page error | `permission_denied` |
| denied response keys | `error`, `status` |
| leak_detected | `false` |
| matched_leak_terms | `[]` |

验证：

```bash
uv run pytest tests/test_pdf_agent_tool_smoke.py tests/test_pdf_document_tools.py tests/test_checklist2_production_defaults.py -q --no-cov
uv run python -m compileall -q evals/knowledge_base/pdf_agent_tool_smoke.py tests/test_pdf_agent_tool_smoke.py
uv run ruff check evals/knowledge_base/pdf_agent_tool_smoke.py tests/test_pdf_agent_tool_smoke.py --select F,E9,I
```

通过情况：

- PDF smoke / PDF tools / production defaults：13/13 passed。
- compileall：通过。
- ruff `F,E9,I`：通过。

仍未完成：

- B4-G4：PDF page/table/source_ref eval 复跑。
- B4-G5：E1 permission/scope/citation eval 复跑。
- B4-G6/G7：启用或继续禁用结论、生产启用申请和回滚记录。

结论：B4-S1/S2/S3/S4/S5 已通过；其中 B4-G3 已在 13.3 补齐，生产 active 仍然禁止。

### 13.3 B4-G3（2026-06-09）

已完成：

- `evals/knowledge_base/pdf_agent_tool_smoke.py` 将 stage 升级为 `B4-G3`。
- 新增真实表发现：读取目标 PDF 的 `tables.json`，自动选择真实表；如果传入 `--table-id t_expected_if_known` 或不传 table_id，则使用第一张表。
- 当前真实工艺 PDF 有 1 张表，实际使用 `table_id=t00001`，`page=1`。
- 新增 authorized table success：有表时必须 rows 或 markdown 非空，且 source_refs 可解析。
- 新增 invalid table 安全错误：不存在表必须返回 `table_not_found`，且不泄露表格内容或路径。
- 新增 denied table no-leak：无权限用户抽同一张表必须返回 `permission_denied`，且不泄露 table_id、表头、行数据、markdown、source_ref 或 artifact 路径。
- 新增 no-table 单测：如果未来目标 PDF 无表，authorized table 可标为 `not_applicable`，但 invalid / denied table 仍要安全返回。

真实 indexed PDF smoke：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.pdf_agent_tool_smoke \
  --doc-id doc_27b282ca-97c3-5170-af0a-282f2e9122a1 \
  --valid-page 1 \
  --invalid-page 9999 \
  --table-id t00001 \
  --invalid-table-id __missing_table__ \
  --authorized-user admin \
  --denied-user user-denied \
  --output-json evals/knowledge_base/reports/pdf_agent_tool_smoke_b4_g3_20260609.json \
  --output-md evals/knowledge_base/reports/pdf_agent_tool_smoke_b4_g3_20260609.md
```

结果：

| 字段 | 值 |
|---|---|
| status | `passed` |
| stage | `B4-G3` |
| default_enabled | `false` |
| default_tools_visible | `[]` |
| table_available | `true` |
| table_count | `1` |
| selected_table_id | `t00001` |
| authorized table status | `success` |
| authorized table row_count | `4` |
| authorized table markdown_non_empty | `true` |
| authorized table source_refs_resolvable | `true` |
| invalid table error | `table_not_found` |
| invalid table leak_detected | `false` |
| denied table error | `permission_denied` |
| denied table response keys | `error`, `status` |
| denied table leak_detected | `false` |

验证：

```bash
uv run pytest tests/test_pdf_agent_tool_smoke.py -q --no-cov
uv run python -m compileall -q evals/knowledge_base/pdf_agent_tool_smoke.py tests/test_pdf_agent_tool_smoke.py
uv run ruff check evals/knowledge_base/pdf_agent_tool_smoke.py tests/test_pdf_agent_tool_smoke.py --select F,E9,I
```

通过情况：

- `tests/test_pdf_agent_tool_smoke.py`：4/4 passed。
- compileall：通过。
- ruff `F,E9,I`：通过。

仍未完成：

- B4-G4：PDF page/table/source_ref eval 复跑。（已在 13.4 补齐）
- B4-G5：E1 permission/scope/citation eval 复跑。（已在 13.4 补齐）
- B4-G6/G7：启用或继续禁用结论、生产启用申请和回滚记录。（G6 已在 13.4 补齐，G7 未执行）

结论：B4-S1/S2/S3/S4/S5/S6/S7/S8 已通过；生产 active 仍然禁止。

### 13.4 B4-G4/G5/G6（2026-06-09）

已完成：

- G4：PDF page/table/source_ref eval 复跑。
- G5：E1 permission isolation / scope lock / citation accuracy 三组 eval 复跑。
- G6：更新 `PROJECT_STATE.md`，记录当前结论为“具备申请启用条件，但生产继续默认关闭”。

G4 命令：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run python -m evals.knowledge_base.pdf_page_table_eval_report \
  --samples evals/knowledge_base/evalsets/pdf_page_table_eval_current_failure_20260608.json \
  --output-json evals/knowledge_base/reports/pdf_page_table_eval_b4_g4_20260609.json \
  --output-md evals/knowledge_base/reports/pdf_page_table_eval_b4_g4_20260609.md
```

G4 结果：

| 字段 | 值 |
|---|---|
| total | `1` |
| page_accuracy_passed | `1` |
| table_presence_passed | `1` |
| source_ref_resolvable_passed | `1` |
| artifact_missing_count | `0` |

G5 命令：

```bash
uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_permission_isolation_10q.jsonl \
  --report evals/knowledge_base/reports/department_rag_permission_isolation_b4_g5_20260609.json

uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_scope_lock_10q.jsonl \
  --report evals/knowledge_base/reports/department_rag_scope_lock_b4_g5_20260609.json

uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_citation_accuracy_10q.jsonl \
  --report evals/knowledge_base/reports/department_rag_citation_accuracy_b4_g5_20260609.json
```

G5 结果：

| eval | 结果 | 门禁判断 |
|---|---|---|
| permission isolation 10q | `10/10 passed`, `permission_filtered_passed=10` | 通过 |
| scope lock 10q | `9/10 passed`, `wrong_scope_count=0`, `citation_unresolvable_count=0` | 通过 scope/citation 门禁；保留 1 个既有内容失败 |
| citation accuracy 10q | `10/10 passed`, `citation_unresolvable_count=0` | 通过 |

scope lock 说明：

- 失败样本：`SCOPE-08`
- query：`设备检修和故障复盘流程`
- failure_category：`answer_wrong`
- selected_kb_ids：`["craft_dept"]`
- 判断：不是 B4 引入的 wrong-scope 或 citation 退化。

G6 结论：

- B4-S1 到 B4-S12 的本地门禁已完成。
- 当前结论是：B4 已具备申请启用条件，并已完成 local-only G7。
- `app/config.py` 源码默认仍保持 `pdf_agent_tools_enabled=False`。
- local `.env` 已按批准设置 `PDF_AGENT_TOOLS_ENABLED=true`。
- staging / production 真正启用仍必须另走 G7：明确目标环境、批准人、启用范围、回滚方式和回滚验证。

G7 local 执行结果：

- B4-G7：local 启用申请和回滚记录已更新为 `docs/B4 PDF Agent 工具生产启用与回滚记录.md`，当前状态是 `local_enabled`。
- 启用范围：`admin + craft_dept + doc_27b282ca-97c3-5170-af0a-282f2e9122a1`。
- G7 smoke 报告：`evals/knowledge_base/reports/pdf_agent_tool_smoke_b4_g7_local_enabled_20260609.json` / `.md`。
- G7 smoke 结果：`status=passed`，`default_enabled=true`，默认可见工具为 `pdf.read_document_page` / `pdf.extract_document_table`，authorized page/table 成功，denied page/table 均为 `permission_denied` 且 `leak_detected=false`。
- G7 rollback drill：用单次进程环境覆盖 `PDF_AGENT_TOOLS_ENABLED=false` 验证关闭态，结果为 `pdf_agent_tools_enabled=false`、`pdf_tools_visible=[]`、`passed=true`；随后普通 `.env` 读取仍为 `true`，local 启用状态未被演练破坏。

结论：B4 本地生产启用门禁已通过，local 最小范围已启用；staging / production 未启用。
