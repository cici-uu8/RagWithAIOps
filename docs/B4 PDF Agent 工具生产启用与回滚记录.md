# B4 PDF Agent 工具生产启用与回滚记录

日期：2026-06-09

状态：`local_enabled`

结论：B4 PDF Agent 工具已通过本地 G1-G6 门禁，并在用户明确批准后完成 G7 local 环境最小范围启用。启用方式仅为本仓库 local `.env` 设置 `PDF_AGENT_TOOLS_ENABLED=true`；`app/config.py` 源码默认值仍为 `False`，staging / production 未启用。

---

## 1. 当前状态

| 项目 | 状态 |
|---|---|
| `pdf_agent_tools_enabled` 源码默认值 | `False` |
| B4-G1/G2/G3 real indexed-PDF smoke | 已通过 |
| B4-G4 PDF page/table/source_ref eval | 已通过 |
| B4-G5 E1 permission/scope/citation eval | 已复跑，无 B4 引入的权限、scope 或 citation 退化 |
| B4-G6 状态记录 | 已更新 |
| B4-G7 local 启用 | 已批准，已执行，已通过启用后 smoke |
| staging / production 启用 | 未批准，未执行 |

当前不得把 `app/config.py` 的 `pdf_agent_tools_enabled` 源码默认值改成 `True`。本次只允许 local `.env` 在批准范围内启用；任何 staging / production 启用都必须另走审批、范围记录和回滚验证。

---

## 2. 已通过门禁证据

### 2.1 Real indexed-PDF smoke

报告：

- `evals/knowledge_base/reports/pdf_agent_tool_smoke_b4_g3_20260609.json`
- `evals/knowledge_base/reports/pdf_agent_tool_smoke_b4_g3_20260609.md`

摘要：

| 场景 | 结果 |
|---|---|
| B4-S1 默认关闭 | `default_enabled=false`，默认工具列表为空 |
| B4-S2 schema 安全 | `forbidden_hits=[]` |
| B4-S3 有权限读有效页 | `success`，1277 字符，6 个可解析 source_ref |
| B4-S4 有权限读无效页 | `page_out_of_range`，无泄露 |
| B4-S5 无权限读有效页 | `permission_denied`，无泄露 |
| B4-S6 有权限抽有效表 | `success`，4 行，markdown 非空，source_ref 可解析 |
| B4-S7 有权限抽不存在表 | `table_not_found`，无泄露 |
| B4-S8 无权限抽表 | `permission_denied`，无泄露 |

目标 PDF：

- `doc_id=doc_27b282ca-97c3-5170-af0a-282f2e9122a1`
- 文件：`线上故障处理_现场设备工艺版.pdf`
- 表格：`table_id=t00001`

### 2.2 PDF eval

报告：

- `evals/knowledge_base/reports/pdf_page_table_eval_b4_g4_20260609.json`
- `evals/knowledge_base/reports/pdf_page_table_eval_b4_g4_20260609.md`

摘要：

| 字段 | 值 |
|---|---|
| total | `1` |
| page_accuracy_passed | `1` |
| table_presence_passed | `1` |
| source_ref_resolvable_passed | `1` |
| artifact_missing_count | `0` |

### 2.3 E1 eval

报告：

- `evals/knowledge_base/reports/department_rag_permission_isolation_b4_g5_20260609.json`
- `evals/knowledge_base/reports/department_rag_scope_lock_b4_g5_20260609.json`
- `evals/knowledge_base/reports/department_rag_citation_accuracy_b4_g5_20260609.json`

摘要：

| eval | 结果 | G7 判断 |
|---|---|---|
| Permission isolation | `10/10 passed`, `permission_filtered_passed=10` | 通过 |
| Scope lock | `9/10 passed`, `wrong_scope_count=0`, `citation_unresolvable_count=0` | 通过 scope/citation 门禁；保留既有内容失败 |
| Citation accuracy | `10/10 passed`, `citation_unresolvable_count=0` | 通过 |

`SCOPE-08` 仍是已知内容题 `answer_wrong`，不是 PDF 工具导致的 wrong-scope 或 citation 退化。启用记录中不能把 scope lock 写成 10/10。

### 2.4 G7 local 启用后 smoke

报告：

- `evals/knowledge_base/reports/pdf_agent_tool_smoke_b4_g7_local_enabled_20260609.json`
- `evals/knowledge_base/reports/pdf_agent_tool_smoke_b4_g7_local_enabled_20260609.md`

摘要：

| 字段 | 值 |
|---|---|
| stage | `B4-G7` |
| status | `passed` |
| expected_default_enabled / default_enabled | `true / true` |
| default_tools_visible | `["pdf.read_document_page", "pdf.extract_document_table"]` |
| authorized page read | `success`, 1277 字符，6 个可解析 source_ref |
| denied page read | `permission_denied`, `leak_detected=false`, response keys `["error", "status"]` |
| authorized table extract | `success`, 4 行，markdown 非空，6 个可解析 source_ref |
| denied table extract | `permission_denied`, `leak_detected=false`, response keys `["error", "status"]` |

另行用 local `ToolExecutionFacade` 对 `admin/craft_dept` 上下文 list tools，确认可见 PDF 工具为 `["pdf.read_document_page", "pdf.extract_document_table"]`。

---

## 3. 生产启用申请状态

| 字段 | 当前值 |
|---|---|
| 申请状态 | `requested` |
| 批准状态 | `approved_for_local_only` |
| 目标环境 | `local` |
| 批准人 | `cici` |
| 执行人 | `Codex` |
| 启用时间 | `2026-06-09` |
| 启用配置位置 | local `.env`，键名 `PDF_AGENT_TOOLS_ENABLED=true` |
| 启用范围 | `admin + craft_dept + doc_27b282ca-97c3-5170-af0a-282f2e9122a1` |
| 回滚负责人 | `cici` |
| 回滚验证窗口 | `2026-06-09` 已完成 rollback drill；owner 已将 local 观察复核提前到 `2026-06-09` 并通过 |

本批准只覆盖 local 环境和上表范围。staging / production 仍是 `not_approved`。

---

## 4. 启用范围模板

生产启用前必须把范围写成可审计的白名单。

| 范围项 | 目标值 |
|---|---|
| 用户 | `admin` |
| 部门 | `craft_dept` |
| KB | `craft_dept` |
| doc_id | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` |
| 功能 | `pdf.read_document_page` / `pdf.extract_document_table` |
| 是否灰度 | 是，local 单用户 / 单 KB / 单 PDF |
| 灰度观察时长 | 原计划 2 天；owner 已批准提前复核，`2026-06-09` local recheck 通过 |
| 日志/审计检查方式 | G7 smoke 报告 + local ToolGateway visible-tools 检查 + denied no-leak 检查 |

默认建议：先在 staging 或受控 local 环境做 1 个部门、1 个 KB、1 个 PDF 的灰度，不直接全量打开。

---

## 5. 启用步骤模板

执行前确认：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run pytest tests/test_pdf_agent_tool_smoke.py tests/test_pdf_document_tools.py tests/test_checklist2_production_defaults.py -q --no-cov
uv run ruff check evals/knowledge_base/pdf_agent_tool_smoke.py tests/test_pdf_agent_tool_smoke.py --select F,E9,I
uv run python -m compileall -q evals/knowledge_base/pdf_agent_tool_smoke.py tests/test_pdf_agent_tool_smoke.py
git diff --check
```

启用步骤：

1. 在 local `.env` 设置 `PDF_AGENT_TOOLS_ENABLED=true`。
2. 用新进程读取 `app.config.config.pdf_agent_tools_enabled`，确认值为 `True`。
3. 用授权用户 list tools，确认出现 `pdf.read_document_page` 和 `pdf.extract_document_table`。
4. 用授权用户读取目标 PDF 的有效页和有效表，确认 source_ref 可解析。
5. 用无权限用户读取同一页和同一表，确认只返回 `permission_denied` 且无泄露。
6. 记录启用时间、执行人、批准人、验证命令和结果。

必须写入的启用声明：

```text
B4 PDF Agent tools were enabled only after indexed-PDF smoke and E1/PDF eval gates passed. Default source code config remains pdf_agent_tools_enabled=False.
```

---

## 6. 回滚步骤模板

触发回滚的条件：

- 无权限用户拿到标题、正文、表格、source_ref、artifact path 或 source file path。
- 授权用户读取页/表返回不可解析 source_ref。
- 工具在未批准用户、部门、KB 或 doc_id 范围内可见。
- E1 permission/scope/citation 或 PDF eval 出现新退化，且无法证明与 B4 无关。
- 目标服务刷新失败，导致关闭配置后工具仍可见。

回滚步骤：

1. 将目标环境的 `pdf_agent_tools_enabled` 改回 `False`。
2. 重启或刷新对应服务进程。
3. 运行默认关闭测试。

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
uv run pytest tests/test_pdf_document_tools.py tests/test_checklist2_production_defaults.py -q --no-cov
```

4. 用同一用户再次 list tools，确认 `pdf.read_document_page` 和 `pdf.extract_document_table` 不可见。
5. 用此前的无权限用户重试同一 doc/page/table，确认仍为 `permission_denied` 或工具不可见。
6. 在 `PROJECT_STATE.md` 记录回滚时间、原因、配置位置、执行人、验证命令和结果。

### 6.1 Local rollback drill 结果

本轮未永久关闭 local `.env`，而是用单次进程环境覆盖 `PDF_AGENT_TOOLS_ENABLED=false` 演练回滚效果。

验证命令：

```bash
PDF_AGENT_TOOLS_ENABLED=false uv run python - <<'PY'
import asyncio
import json
from app.config import config
from app.enterprise.context import RequestContext
from app.enterprise.tools.local_provider import build_local_agent_tool_execution_facade

async def main():
    ctx = RequestContext(
        request_id="g7-rollback-drill-admin",
        trace_id="g7-rollback-drill-admin",
        user_id="admin",
        username="admin",
        department_id="craft_dept",
        department_name="craft_dept",
        roles=["admin"],
    )
    facade = build_local_agent_tool_execution_facade()
    tools = await facade.list_visible_tools(ctx, capability="rag")
    pdf_tools = [tool.resource_id for tool in tools if tool.resource_id.startswith("pdf.")]
    print(json.dumps({
        "pdf_agent_tools_enabled": config.pdf_agent_tools_enabled,
        "pdf_tools_visible": pdf_tools,
        "passed": config.pdf_agent_tools_enabled is False and pdf_tools == [],
    }, ensure_ascii=False, sort_keys=True))

asyncio.run(main())
PY
```

结果：

```json
{"passed": true, "pdf_agent_tools_enabled": false, "pdf_tools_visible": []}
```

回归验证：

```bash
PDF_AGENT_TOOLS_ENABLED=false uv run pytest tests/test_pdf_document_tools.py tests/test_checklist2_production_defaults.py -q --no-cov
```

结果：`10 passed`。

演练后再次用普通 `.env` 读取配置，`config.pdf_agent_tools_enabled=True`，说明 rollback drill 没有破坏当前 local 启用状态。

---

## 7. 最终签署区

| 字段 | 值 |
|---|---|
| 是否批准启用 | `yes_local_only` |
| 批准人 | `cici` |
| 批准时间 | `2026-06-09` |
| 实际启用环境 | `local` |
| 实际启用范围 | `admin + craft_dept + doc_27b282ca-97c3-5170-af0a-282f2e9122a1` |
| 实际回滚方式 | 删除或改写 local `.env` 中 `PDF_AGENT_TOOLS_ENABLED=true` 为 `false`，重启/刷新服务进程后复跑默认关闭和工具不可见检查；该方式已通过进程环境覆盖 drill 验证 |
| 启用后复核人 | `cici` |
| 复核结果 | G7 local smoke 已通过；rollback drill 已通过；owner 提前触发的 `2026-06-09` local recheck 已通过 |

当前签署结论：local 最小范围已批准并启用；staging / production 未批准、不启用。
