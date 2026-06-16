# 记忆 RAG/PDF 并行开发执行步骤清单 2.1

日期：2026-06-08

状态：阶段完成，清单 2.1 实现已提交为 `de5f68c feat: complete checklist2 memory rag pdf gates`。G0 已完成；E1 第一切片和 permission-isolation 语义修复已完成；C4 default-off RAG session memory 接入已完成；C5 default-off AIOps tool-result offload 已完成；B4 default-off PDF Agent 工具链已完成；D1 routing shadow 诊断字段已完成。A3 query rewrite shadow 是条件触发项，当前 18/18 current-scope 无 query 表达失败证据，因此暂不执行。当前 E1 护栏结果为 permission isolation 10/10、scope lock 9/10、citation accuracy 10/10。C4/C5/B4 仍只能默认关闭 / shadow / 本地验证，不能生产 active。

适用范围：清单 1 已完成 A/B/C/D 基础设施、RAG/PDF 数据门和文档收口后，继续推进核心增强能力和集成工作。

## 0. 前置说明

### 0.1 本清单与清单 1 的关系

清单 1 已完成：
- A 线 R0/R1：RAG baseline + retrieval mode policy
- B 线 P0/P1/P2：PDF baseline + profile + artifact validator
- C 线 C0/C1/C2/C3：SessionMemoryStore 模块层 scaffold
- D 线路由语义升级已纳入共享边界，D0/D1/D2/D4 允许 shadow 诊断，D3 后置
- G0 工作区固化已完成：`27f4765 -> 01d686c -> df9e13a -> 868d02d -> e56567d -> 4d9cde9`

清单 2 覆盖：
- **G0：提交当前工作**（已完成，只保留为审计记录）
- **C 线集成**：memory store 接入 RAG/AIOps prompt
- **B 线 P4**：PDF Agent 工具链
- **A 线 R2**：query rewrite shadow（可选，取决于 eval 证据）
- **D 线补齐**：routing shadow 诊断字段
- **评测扩展**：系统能力维度 evalset

### 0.2 执行原则

1. **G0 已完成**：其他所有章节必须从 `4d9cde9` 之后的新分支或干净逻辑基线开始。
2. **每节独立验收**：验收标准不只是"测试通过"，而是能区分失败类别。
3. **评测护栏优先于 active 能力**：E1 可先做或与 C4 并行，为 C4/C5/B4 提供权限、scope、citation 回归护栏。
4. **shadow 优先于 active**：新能力先 shadow 观测，再根据 eval 决定是否 active。
5. **门禁明确**：每节写明"什么情况下允许进入下一节"，不能只凭感觉推进。

### 0.3 风险控制

- 每节的改动范围不超过 3 个核心模块。
- 集成步骤必须保留 degraded fallback。
- 新增配置默认值必须保持现有行为（off/shadow/context_only）。
- 涉及 prompt 注入的，必须受 memory_mode / config 开关控制。
- 不允许把 `RequestContext`、权限对象或后端内部状态作为模型可见工具参数。
- 不允许把自定义 Python 对象直接塞进 LangGraph `past_steps` / SSE / audit 等需要 JSON 兼容的状态字段。
- `SessionMemoryStore` / `SessionToolResultOffloadStore` 进入 active 前，必须有 TTL、容量上限、owner 级清理和 DB size 观测；否则只允许本地或 shadow。
- memory summary 注入前必须有 stale/过期边界，注入文本只能作为会话上下文，不能影响 citation / SourceRef 判断。
- tool offload 必须保留完整原始结果的 owner-checked 回查路径；只保留摘要不能通过 C5 验收。
- PDF page/table 工具必须先做后端权限校验再读取 artifact；`doc_id/page/table_id` 不能变成绕过权限的读取入口。
- 18/18 current-scope 和 E1 当前小样本结果都不能代表长期质量；新增知识库、权限模型、PDF 工具或 memory active 后必须扩展/复跑 eval。
- 生产配置误开是硬风险。`rag_session_memory_mode`、`tool_result_offload_enabled`、`pdf_agent_tools_enabled`、`rag_query_rewrite_mode` 必须在 `PROJECT_STATE.md` 保持默认禁用边界，且生产启用前必须有回滚记录。

### 0.4 长期运行风险核对

用户补充的长期运行风险已纳入清单 2.1，但当前状态只能称为 **已考虑并设置 active 门禁**，不能称为生产已解决。

| 风险 | 当前处理 | 剩余门禁 |
|---|---|---|
| memory/offload SQLite 表持续增长 | `SessionMemoryStore.cleanup_expired(...)` 和 `SessionToolResultOffloadStore.cleanup_expired(...)` 已存在；RAG prompt 读取和 AIOps offload 写入会做 owner 级 opportunistic cleanup | 生产 active 前仍需定时清理任务、容量上限、DB size 观测和告警 |
| memory summary 过期影响判断 | C4 active 注入前会按 `rag_session_memory_snapshot_ttl_seconds` 判断 stale；过期 snapshot 不注入 | 仍需长会话 shadow 校准，确认 TTL 不会过短丢上下文或过长污染判断 |
| prompt 注入增加成本和幻觉面 | 默认 `rag_session_memory_mode=off`；active 注入文本有长度上限并标注“仅作上下文，不是资料依据”；`source_ref` / citation 字段会被净化 | 生产 active 前需成本观测、幻觉/越权回归和更大 eval |
| tool offload 破坏审计和 eval 证据 | `past_steps` 保持字符串兼容；写入失败、缺 session/owner、超过上限时保留原文；offload 后完整原文保存在 owner-checked store，prompt 只放摘要和 `tool_result:*` ref | 生产 active 前需真实 AIOps 长日志 smoke、阈值校准、result_ref 到审计/trace 的回查流程和 retention 策略 |
| PDF 工具按 `doc_id/page` 泄露文档 | 工具 schema 只暴露 `doc_id/page/table_id`；`RequestContext` 由后端 gateway 注入；读取 artifact 前必须过 `DocumentAccessService.can_read_document(...)`；拒绝响应不泄露标题、正文、表格或路径 | 生产 active 前需真实 indexed PDF smoke、E1 复跑、PDF page/table eval 复跑和无泄漏回归 |
| evalset 过期导致 18/18 虚高 | 文档已标注 18/18 current-scope 是 3 文档小样本 baseline；E1 只是一批系统护栏小样本 | 新知识库、权限模型、PDF 工具、memory active 或检索默认值变化后必须扩展/复跑 eval |
| 配置误开 | `rag_session_memory_mode=off`、`tool_result_offload_enabled=False`、`pdf_agent_tools_enabled=False`、`rag_query_rewrite_mode=off` 保持默认禁用，并记录在 `PROJECT_STATE.md` | 生产启用前必须有显式配置变更、门禁证据和 rollback/enablement 记录 |

## 目录

- **G0：固化当前工作（已完成，P0 审计记录）**
- **C4：memory store 接入 RAG prompt（P0）**
- **C5：memory store 接入 AIOps tool result offload（P1）**
- **B4：PDF P4 Agent 工具链（P1）**
- **A3：RAG R2 query rewrite shadow（P2，条件触发）**
- **D1：routing shadow 诊断字段（P2）**
- **E1：评测体系扩展：系统能力维度（P2）**

---

## G0：固化当前工作（已完成，P0 审计记录）

### G0.1 目标

将清单 1 执行过程中累积的改动按逻辑边界分批 commit，形成可追溯的 git 历史。

当前状态：已完成。清单 2 后续章节不能再以旧提交或历史 dirty workspace 为前提。

### G0.2 当前工作区状态

当前真实状态：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
git log --oneline -6
```

预期提交链：

```text
4d9cde9 docs: close memory rag pdf execution record
e56567d fix(aiops): classify recovered infra errors
868d02d feat(rag): add retrieval mode policy hook
df9e13a feat(rag): add evaluation report tooling
01d686c feat(pdf): add profile and artifact validation
27f4765 feat(memory): add session memory scaffold
```

剩余未跟踪文件不属于清单 1 已验收成果：SQLite WAL/SHM、动态规划草稿、清单 2 草稿和父目录 demo 脚本。

### G0.3 分组策略

实际已按 6 个 commit 固化。原建议中的部分分组被合并或拆分，但逻辑边界清楚。

#### 提交分组建议

**Commit 1: C 线 session memory store 模块**
```
feat(memory): add session memory store with archive/offload

- app/models/session_memory.py
- app/services/session_memory_store.py
- tests/test_session_memory_store.py
```

状态：已提交为 `27f4765`。验收：`tests/test_session_memory_store.py` 通过。

**Commit 2: B 线 PDF profile + artifact validator**
```
feat(pdf): add pdf profile service and artifact validator

- app/services/pdf_profile_service.py
- app/services/artifact_validator_service.py
- tests/test_pdf_profile_service.py
- tests/test_artifact_validator_service.py
- app/services/document_ingestion_service.py (profile 接入点)
```
状态：已提交为 `01d686c`。验收：profile、validator 和 document ingestion 相关测试通过。

**Commit 3: A 线 RAG eval 工具链**
```
feat(rag): add rag baseline/triage/keyword-gap eval tools

- evals/knowledge_base/rag_baseline_report.py
- evals/knowledge_base/rag_answer_failure_triage_report.py
- evals/knowledge_base/rag_keyword_gap_report.py
- evals/knowledge_base/retrieval_mode_comparison_report.py
- tests/test_rag_baseline_report.py
- tests/test_rag_answer_failure_triage_report.py
- tests/test_rag_keyword_gap_report.py
- tests/test_retrieval_mode_comparison_report.py
- app/config.py (rag_default_retrieval_mode)
```

状态：主体已提交为 `df9e13a`，`rag_default_retrieval_mode` policy hook 单独提交为 `868d02d`。默认值保持 `dense_only`。

**Commit 4: B 线 PDF eval 工具链**
```
feat(pdf): add pdf baseline/retry/page-table eval tools

- evals/knowledge_base/pdf_baseline_report.py
- evals/knowledge_base/pdf_retry_report.py
- evals/knowledge_base/pdf_page_table_eval_report.py
- tests/test_pdf_baseline_report.py
- tests/test_pdf_retry_report.py
- tests/test_pdf_page_table_eval_report.py
```

状态：已提交在 `df9e13a` 的 eval/report 工具组中。PDF baseline / retry / page-table 测试通过。

**Commit 5: evalset 更新与 current-scope baseline**
```
feat(eval): add 18q current-scope baseline and evalset tests

- evals/knowledge_base/evalsets/department_rag_18q_current_scope_20260608.jsonl
- evals/knowledge_base/evalsets/department_rag_18q_current_scope_20260608.md
- evals/knowledge_base/evalsets/*.json (新增 PDF/retrieval 样本)
- tests/test_knowledge_base_evalsets.py (18q 结构测试)
```

状态：已提交在 `df9e13a`。18q current-scope baseline 复跑 18/18，20q 保留历史审计 18/20。
**Commit 6: 文档与状态记录更新**
```
docs: update PROJECT_STATE and development records

- PROJECT_STATE.md
- docs/rag_fusion_development_record.md
- docs/memory_fusion_development_record.md
- docs/记忆系统修改指南.md
- docs/记忆 ragpdf 并行开发执行步骤清单.md
- docs/pending_pdf_review_decision_list_20260608.md
- docs/记忆_ragpdf_并行开发_batch0a_static_gate_report.md
```

状态：已提交为 `4d9cde9`。文档中的当前状态已与 commit 1-5/6 的代码一致。

**Commit 7: AIOps recovered_infra_error 语义修复**
```
fix(aiops): add recovered_infra_error semantic for degraded failures

- app/enterprise/aiops/failure_semantics.py
- app/services/aiops_service.py
- aiops_lab/scripts/smoke_aiops.py
- evals/enterprise/matcher.py
- tests/test_enterprise_gateway_routes.py
```

状态：已提交为 `e56567d`。AIOps 相关回归、trace eval 和 full smoke 通过。

### G0.4 执行步骤

G0 已完成，不再重复执行。后续每个新章节仍应独立分支或独立提交，并在提交前执行对应验收。

### G0.5 验收标准

- 已形成清晰提交链到 `4d9cde9`。
- 不相关临时文件未混入提交。
- 清单 2 后续章节从新基线开始。

### G0.6 失败分类

- `stale_plan_state`：清单仍引用清单 1 执行前的历史 dirty workspace → 先更新为 `4d9cde9` 后的当前状态
- `untracked_orphan`：后续仍有文件不属于任何分组 → 审查后决定保留草稿、删除临时文件或另开任务

### G0.7 下一步门禁

G0 已完成。允许进入 C4/C5/B4/D1/E1；A3 仍必须等待检索表达失败证据触发。

---

## C4：memory store 接入 RAG prompt（P0）

### C4.1 目标

让 `SessionMemoryStore` 真正进入 `RagAgentService` 的 prompt 拼装链路，而不是只有模块代码。

### C4.2 前置条件

- G0 已完成。
- `app/services/session_memory_store.py` 已存在且单测通过。
- `app/models/memory_mode.py` 存在。
- 当前 `RagAgentService` 已有 `ConversationSummaryMiddleware.abefore_model()` 做单次 LangGraph 对话内摘要压缩；C4 不能和该摘要机制重复注入。
- `session_memory_snapshots` / archive 表的 TTL、容量上限和 owner 级清理策略必须作为 active 前置门。C4 第一版可以本地验证 prompt 接入，但不能在没有清理策略时生产启用。
- summary 注入必须有 stale 边界：至少记录 `updated_at` / `expires_at` 或等价过期判断；过期 summary 不得进入 active prompt。

### C4.3 集成策略

**不替换现有的 `SessionHistoryAccessor`**，而是在它旁边加一个轻量的 session working memory 层。

当前 `RagAgentService.__init__()` 已经注入了 `SessionHistoryAccessor`，它负责从 `enterprise_chat_sessions` 读取用户可见聊天历史。新增的 `SessionMemoryStore` 负责 Agent prompt 恢复材料（summary + live tail），两者职责不同。

### C4.4 实施步骤

**步骤 1：在 `RagAgentService` 构造函数注入 `SessionMemoryStore`**

```python
# app/services/rag_agent_service.py
from app.services.session_memory_store import SessionMemoryStore, SQLiteSessionMemoryStore

class RagAgentService:
    def __init__(
        self,
        max_raw_rounds: int = 5,
        session_memory_store: SessionMemoryStore | None = None,  # 新增
    ):
        # ... 现有初始化 ...
        self.session_memory_store = session_memory_store or SQLiteSessionMemoryStore()
```

**步骤 2：把 session memory 接入请求级 runtime prompt，而不是 `_initialize_agent()`**

`_initialize_agent()` 是全局 Agent 初始化，只负责 MCP tools、LangGraph agent 和 checkpointer，不知道当前请求的 `session_id` / `owner_id`。不能在这里恢复 memory。

正确接入点是 `query()` / `query_stream()` 构造消息前调用的 `_build_runtime_system_prompt()`。需要让该函数接收 `session_id` 和 memory mode：

```python
async def _build_runtime_system_prompt(
    self,
    *,
    session_id: str | None = None,
    memory_mode: MemoryMode = MemoryMode.OFF,
) -> str:
    prompt = await self._build_existing_runtime_profile_prompt()

    context = get_current_request_context()
    if context is None or not session_id:
        return prompt

    if memory_mode != MemoryMode.ACTIVE:
        return prompt

    snapshot = self.session_memory_store.get_snapshot(
        session_id=session_id,
        owner_id=context.user_id,
    )
    memory_context = snapshot.to_prompt_context() if snapshot else ""
    if not memory_context:
        return prompt

    return f"{prompt}\n\n会话工作记忆（仅作上下文，不是资料引用）:\n{memory_context}"
```

注意：
- `MemoryMode.OFF`：不读取、不注入，默认行为完全不变。
- `MemoryMode.SHADOW`：可以读取并记录诊断，但不注入 prompt。
- `MemoryMode.ACTIVE`：才允许把 `snapshot.to_prompt_context()` 追加进 runtime system prompt。
- 注入文本必须明确“不是资料引用”，不能伪装成 `SourceRef` 或 citation。
- 注入长度必须有上限，避免上下文成本失控；超出上限时优先降级为不注入或只注入短诊断摘要。
- stale summary 必须跳过或降级到 shadow 诊断，不能让旧 summary 影响当前回答判断。

**步骤 3：在 `query()` / `query_stream()` 结束后更新 live_tail**

在 `RagAgentService.query()` 和 `query_stream()` 的成功路径中，结合当前 `RequestContext.user_id` 调用 `append_live_message`。不要依赖 `self.session_id` / `self.owner_id` 这类不存在的实例字段。

```python
context = get_current_request_context()
if self.session_memory_store and context is not None and session_id:
    self.session_memory_store.append_live_message(
        session_id=session_id,
        owner_id=context.user_id,
        role="user",
        content=user_query,
    )
    self.session_memory_store.append_live_message(
        session_id=session_id,
        owner_id=context.user_id,
        role="assistant",
        content=final_answer,
    )
```

**步骤 4：新增显式配置，默认关闭**

当前 `MemoryMode.from_state()` 是 AIOps / eval state 语义，不存在 `MemoryMode.from_config(config)`。RAG prompt 接入需要新增独立配置，例如：

```python
# app/config.py
rag_session_memory_mode: str = "off"  # "off" | "shadow" | "active"
```

解析时只接受 `off/shadow/active`，非法值必须 fallback 到 `off` 并记录 warning。第一版建议保持默认 `off`，只在本地或 eval 显式配置后启用。

### C4.5 归档触发策略（后置，不在第一版做）

第一版**不做自动归档**。只做：
1. 读取已有 snapshot 的 summary
2. 记录新的 live_tail

归档触发（调用 `archive_live_tail()`）作为 C4.1 的后续增强，需要单独设计阈值和触发时机。

### C4.6 验收标准

**单元测试**：
```bash
# 新增测试
tests/test_rag_agent_memory_integration.py
```

测试用例：
- `test_restore_snapshot_when_active`：session 有 snapshot 且 `rag_session_memory_mode=active` 时，runtime prompt 能注入 summary
- `test_append_live_messages_after_chat`：对话后 live_tail 被更新
- `test_memory_mode_off_no_injection`：默认 `off` 时不读取、不注入 prompt
- `test_memory_mode_shadow_reads_without_injection`：shadow 时可记录诊断但不改变 prompt
- `test_memory_context_not_source_ref`：注入内容不包含 `source_ref` / `citation` 伪证据字段
- `test_stale_summary_not_injected`：过期 summary 不进入 active prompt
- `test_memory_prompt_length_bounded`：memory 注入片段不超过配置上限
- `test_memory_cleanup_policy_exists_before_active`：active 配置开启前必须存在 TTL / 容量上限 / owner cleanup 配置或显式阻塞

**集成验证**：
```bash
# 手工 smoke
# 1. 创建一个新 session，对话 2 轮
# 2. 重启服务，用同一 session_id 继续对话
# 3. 检查 SQLite 表 session_memory_snapshots 中是否有记录
sqlite3 logs/enterprise_chat_sessions.sqlite "SELECT session_id, owner_id, latest_summary FROM session_memory_snapshots LIMIT 5;"
```

**回归测试**：
```bash
uv run pytest tests/test_rag_agent_service.py -q --no-cov
```

现有 RAG agent 测试必须仍然通过（因为默认 memory_mode=OFF，行为不变）。

### C4.7 失败分类

- `snapshot_not_restored`：snapshot 存在但未注入 prompt → 检查 memory_mode 和注入逻辑
- `prompt_pollution`：memory 文本被模型当作权威资料或引用 → 收紧提示词，明确不是 SourceRef
- `stale_summary_injected`：过期 summary 被注入 → 检查 stale 判断和降级逻辑
- `memory_table_growth_unbounded`：active 模式没有 TTL / 容量 / cleanup → 阻塞生产启用
- `prompt_context_cost_unbounded`：memory 注入没有长度上限 → 阻塞 active
- `live_tail_not_recorded`：对话后 DB 无记录 → 检查 append_live_message 调用点
- `regression_failure`：现有测试挂了 → 可能是构造函数签名变化，补默认参数

### C4.8 下一步门禁

C4 模块验收通过后，才允许进入 C5（AIOps offload）。C4 生产 active 还必须额外满足：TTL / 容量 / cleanup 已实现、stale summary 不注入、prompt 长度上限验证通过、E1 permission/scope/citation 护栏通过并写入回滚记录。

### C4.9 当前执行结果（2026-06-09）

已完成：
- `app/config.py` 新增 `rag_session_memory_mode="off"`、`rag_session_memory_max_prompt_chars`、`rag_session_memory_max_tail_messages`、`rag_session_memory_snapshot_ttl_seconds`，默认不改变现有行为。
- `MemoryMode.from_config(...)` 支持从配置解析 `off/shadow/active`，非法值 fallback 到 `off`。
- `SessionMemoryStore` 增加 `cleanup_expired(ttl_seconds, owner_id)`；SQLite / InMemory adapter 均支持按 TTL 和 owner 清理 snapshot / archive。
- `RagAgentService` 注入 `SessionMemoryStore`，在请求级 `_build_runtime_system_prompt(session_id=...)` 中处理 memory：
  - `off`：不读、不注入、不写 live tail。
  - `shadow`：可读取 snapshot 并记录 live tail，但不注入 prompt。
  - `active`：仅在 TTL / cleanup / prompt 长度门禁存在时注入 bounded memory context。
- 注入文本使用“会话工作记忆（仅作上下文，不是资料依据）”，并过滤 `source_ref` / `citation` 等伪证据字段，避免 memory 伪装成 RAG citation。
- `query()` / `query_stream()` 成功路径在非 off 模式下记录 user / assistant live tail；失败路径不写入。

新增测试：
- `tests/test_rag_agent_memory_integration.py`
  - off 不读不注入
  - shadow 读取但不注入
  - active 注入 bounded 且不含伪 citation 字段
  - stale summary 不注入
  - 无 cleanup policy 时 active 降级
  - 成功 query 在 shadow 模式写 live tail
- `tests/test_session_memory_store.py`
  - InMemory / SQLite TTL cleanup 按 owner 生效

当前验收：
- C4 模块级接入完成。
- 默认仍为 `rag_session_memory_mode="off"`，生产 active 仍未启用。
- C4 生产 active 仍需要单独回滚记录、长期 shadow 观察和更大样本 eval，不因本轮测试通过自动开放。

---

## C5：memory store 接入 AIOps tool result offload（P1）

### C5.1 目标

让 AIOps 的长工具结果（如几百行日志）不直接塞进 replanner / final response prompt，而是把完整结果写入 `SessionToolResultOffloadStore`，在 `past_steps` 中只保留字符串摘要和 `result_ref`。

第一版禁止把 `ToolResultRef` Python 对象直接塞进 LangGraph state、SSE、audit 或 eval matcher 输入；这些路径必须保持 JSON / 字符串兼容。

### C5.2 前置条件

- C4 已完成。
- `SessionToolResultOffloadStore` 已存在且单测通过。
- `tool_result_offloads` 必须有 TTL、最大单条大小、最大 session 累计大小和 owner 级清理策略；否则只允许本地或 shadow 验证。
- audit / eval 的原始证据保留路径必须先定义清楚：offload 只能减少 prompt 展示文本，不能删除或覆盖完整工具结果。

### C5.3 集成点

AIOps 的工具结果在 `app/agent/aiops/executor.py` 中被合成为 `result`，并以 `past_steps: [(task, result)]` 写入 LangGraph state。第一版应在 executor 生成最终 `result` 后做字符串级 offload：

```python
from app.services.session_memory_store import SessionToolResultOffloadStore, ToolResultRef

def maybe_offload_aiops_step_result(
    *,
    session_id: str,
    owner_id: str,
    task: str,
    result: str,
    threshold: int,
    store: SessionToolResultOffloadStore,
) -> str:
    if len(result) <= threshold:
        return result

    summary = result[:500]
    ref = store.offload_result(
        session_id=session_id,
        owner_id=owner_id,
        tool_name="aiops_step_result",
        content=result,
        summary=summary,
        metadata={"task": task},
    )
    return f"{summary}\n... [完整工具结果已 offload: {ref.result_ref}]"
```

关键边界：
- `past_steps` 仍保持 `list[tuple]`，tuple 的第二项仍是 `str`。
- 原始长结果必须能通过 `SessionToolResultOffloadStore.get_result(result_ref, owner_id=...)` 回查。
- audit / trace eval 需要的 required-tool 覆盖不能依赖被截断掉的正文；工具名覆盖仍应使用 `aiops_executed_tools` 字段。
- 存储原文和生成摘要是两件事：摘要只用于 prompt，完整原文必须先落库并可被 owner 校验回查。
- 如果完整原文写入失败，必须保留原始 `result` 字符串，不允许退化成 summary-only。
- 单条 offload 超过最大大小时必须拒绝 offload 或分片保存，不能静默截断原始证据。

### C5.4 prompt 拼装

不改 `planner.py` / `replanner.py` 的状态结构，不让它们识别 Python 对象。它们继续消费 `past_steps` 字符串；区别只是长结果已被替换成“摘要 + result_ref”。

```python
# state["past_steps"] 仍然是字符串
for step_name, step_result in past_steps:
    prompt_parts.append(f"{step_name}: {step_result}")
```

如果后续要在 UI 或审计页面展开完整结果，必须新增受 owner 校验的 read API；不允许把 `result_ref` 当成公开 URL 或无权限 token。

### C5.5 验收标准

**单元测试**：
```bash
tests/test_aiops_tool_result_offload.py
```

测试用例：
- `test_offload_long_result`：超过阈值的 result 被 offload，`past_steps` 中仍是字符串
- `test_short_result_no_offload`：短 result 不 offload
- `test_ref_prompt_stub`：ToolResultRef 的 prompt_stub 不超过 200 字符
- `test_offload_original_resolvable_by_owner`：同 owner 可回查原文，其他 owner 查不到
- `test_required_tool_coverage_not_lost`：offload 后 `aiops_executed_tools` 仍保留 required-tool 覆盖证据
- `test_offload_write_failure_keeps_original_result`：offload 写入失败时 `past_steps` 保留原始完整结果
- `test_offload_cleanup_policy_exists_before_active`：active 配置开启前必须存在 TTL / 单条大小 / session 累计大小 / owner cleanup 配置
- `test_summary_only_is_rejected`：只有摘要、无完整原文回查时不能通过验收

**集成验证**：
```bash
# 触发一个 AIOps 诊断，工具返回长日志（如 search_service_logs）
# 检查 SQLite 表 tool_result_offloads 中是否有记录
# 检查最终 diagnosis_complete / eval report 不因摘要截断丢失 required-tool 覆盖
```

**回归测试**：
```bash
uv run pytest tests/test_aiops_service.py -q --no-cov

# AIOps lab/API smoke 使用当前已验证脚本；不要引用旧的聚合 shell 脚本
python3 aiops_lab/cmdb/seed.py
docker compose -f aiops_lab/docker-compose.yml up --build -d
uv run python aiops_lab/scripts/smoke_aiops.py \
  --skip-aiops-api \
  --output aiops_lab/reports/smoke_aiops_lab_only_c5.json
NO_PROXY=localhost,127.0.0.1,::1 no_proxy=localhost,127.0.0.1,::1 \
  uv run python aiops_lab/scripts/smoke_aiops.py \
    --api-url http://127.0.0.1:9900 \
    --output aiops_lab/reports/smoke_aiops_full_api_c5.json
docker compose -f aiops_lab/docker-compose.yml down
```

### C5.6 失败分类

- `offload_not_triggered`：长 result 未被 offload → 检查阈值和调用点
- `ref_not_resolvable`：offload 后无法回查原文 → 检查 get_result() 逻辑
- `prompt_still_too_long`：prompt 仍超长 → 降低阈值或检查 summary 生成
- `state_serialization_break`：LangGraph/SSE/eval 无法序列化 → 检查是否误把 `ToolResultRef` 对象放入 state
- `evidence_lost`：required-tool / root-cause 评估变差 → 检查是否把工具名、证据类别或 root-cause 关键词截断掉
- `summary_only_offload`：只保存摘要、完整原文不可回查 → 阻塞验收
- `offload_table_growth_unbounded`：无 TTL / 大小上限 / cleanup → 阻塞生产启用
- `offload_permission_bypass`：其他 owner 可通过 result_ref 读到原文 → 阻塞验收

### C5.7 配置与开关

新增配置：
```python
# app/config.py
tool_result_offload_enabled: bool = False  # 默认关闭
tool_result_offload_threshold: int = 2000
tool_result_offload_max_bytes: int = 200_000
tool_result_offload_ttl_days: int = 7
```

只有显式启用后才 offload，否则保持原行为。

### C5.8 下一步门禁

C5 完成且 smoke 通过后，C 线阶段性收口。生产 active 还必须额外满足：完整原文 owner-checked 回查可用、summary-only 被测试拒绝、TTL / 大小上限 / cleanup 已实现、AIOps eval 不因摘要截断丢失 required-tool / root-cause 证据。

### C5.9 当前执行结果（2026-06-09）

已完成：
- `app/config.py` 新增 `tool_result_offload_enabled=False`、`tool_result_offload_threshold`、`tool_result_offload_max_bytes`、`tool_result_offload_ttl_days`，默认关闭。
- `PlanExecuteState` 增加 `session_id`，`AIOpsService.execute()` 将当前 session_id 写入 state，供 executor 做 session-scoped offload。
- `SessionToolResultOffloadStore.cleanup_expired(...)` 支持按 TTL 和 owner 清理 `session_tool_result_offloads`。
- `SessionToolResultOffloadStore.offload_result(...)` 对 `content` 改为“非空检查但保留原文”，不再 strip 末尾换行，保证审计/eval 原始证据完整。
- `app/agent/aiops/executor.py` 增加 `maybe_offload_aiops_step_result(...)`：
  - 默认 `tool_result_offload_enabled=False` 时原样返回 result。
  - 只有显式启用且 result 超过阈值时，才写入 `SessionToolResultOffloadStore`。
  - `past_steps` 仍保持 `[(task, str)]`，不塞 `ToolResultRef` Python 对象。
  - 写入失败、缺 `session_id/memory_owner_id`、超过单条大小上限时，保留原始完整 result，禁止 summary-only。
  - `aiops_executed_tools` 不依赖被截断正文，offload 后仍返回原工具名列表。

新增测试：
- `tests/test_aiops_tool_result_offload.py`
  - 默认关闭时长 result 原样留在 `past_steps`
  - 长 result offload 后 owner 可回查完整原文，其他 owner 不可回查
  - offload 写入失败时保留原始完整 result
  - 超过 max bytes 时保留原始完整 result
  - offload 后 required-tool 覆盖字段仍保留
- `tests/test_session_memory_store.py`
  - tool-result offload 保留末尾换行等原始 content
  - tool-result TTL cleanup 按 owner 生效

当前验收：
- C5 default-off 模块级接入完成。
- 生产 active 仍未启用；需要真实 AIOps 长日志 smoke、阈值校准、eval 复跑和回滚记录后才能考虑打开。

---

## B4：PDF P4 Agent 工具链（P1）

### B4.1 目标

新增 `read_document_page` 和 `extract_document_table` 两个 Agent 工具，让 AI 能按页读、按表抽数据。

### B4.2 前置条件

- G0 已完成。
- `blocks.json` page coverage >= 95%（在 P0 baseline 中已验证）。
- `tables.json` 的 table_id/page_start/rows 稳定（在 pdf_page_table_eval 中已验证）。
- E1 permission-isolation / scope / citation 护栏必须可复跑；PDF 工具会直接暴露文档页和表格内容，不能在没有权限回归测试时接入 Agent。
- `DocumentAccessService.can_read_document(context, document)` 必须是工具 provider 读取 artifact 前的硬门禁；模型传入的 `doc_id/page/table_id` 永远不能绕过后端权限。

### B4.3 开发前置门：blocks page coverage 验证

在开发工具前，必须先确认 blocks.json 的页码产物可信：

```bash
# 对当前 3 个 indexed 文档跑 blocks 检查
uv run python -c "
import json
from pathlib import Path

for doc_dir in Path('uploads/documents').rglob('artifacts'):
    blocks_file = doc_dir / 'blocks.json'
    if blocks_file.exists():
        blocks = json.loads(blocks_file.read_text())
        total = len(blocks)
        with_page = sum(1 for b in blocks if b.get('page'))
        print(f'{doc_dir.parent.name}: {with_page}/{total} blocks with page')
"
```

预期：所有文档的 page coverage >= 95%。如果不满足，B4 阻塞，先修 P3 页码策略。

### B4.4 工具 1：read_document_page

**模型可见工具参数**：
```python
ToolDefinition(
    tool_id="pdf.read_document_page",
    name="read_document_page",
    input_schema={
        "type": "object",
        "properties": {
            "doc_id": {"type": "string"},
            "page": {"type": "integer", "minimum": 1},
        },
        "required": ["doc_id", "page"],
    },
)
```

模型参数里不能出现 `RequestContext`、`owner_id`、权限对象或内部 artifact path。

**后端执行签名**：
```python
async def execute_tool_with_context(
    self,
    tool_id: str,
    arguments: dict[str, Any],
    ctx: RequestContext,
) -> dict[str, Any]:
    if tool_id == "pdf.read_document_page":
        return self._read_document_page(
            doc_id=str(arguments["doc_id"]),
            page=int(arguments["page"]),
            context=ctx,
        )
```

`context` 只能由 `ToolGateway.execute(context, tool_id, arguments)` / provider 后端注入，不能让模型自己传。

**实现要点**：
1. 通过 `KnowledgeMetadataStore` 查 `DocumentRecord`
2. 在 provider 后端调用 `DocumentAccessService.can_read_document(context, document)` 校验权限
3. 读取 `artifacts/blocks.json`，过滤 `block.page == page` 的 blocks
4. 拼接成 content，同时返回对应的 source_refs

必须先权限校验再读取 artifact。无权限时不能返回文档标题、页码正文、表格片段、artifact path 或可推断文件位置的错误细节。

**错误处理**：
- 文档不存在 → `{"error": "document_not_found"}`
- 无权限 → `{"error": "permission_denied"}`
- blocks.json 缺失 → `{"error": "artifact_missing"}`
- 页码超范围 → `{"error": "page_out_of_range"}`

### B4.5 工具 2：extract_document_table

**模型可见工具参数**：
```python
ToolDefinition(
    tool_id="pdf.extract_document_table",
    name="extract_document_table",
    input_schema={
        "type": "object",
        "properties": {
            "doc_id": {"type": "string"},
            "table_id": {"type": "string"},
            "page": {"type": "integer", "minimum": 1},
        },
        "required": ["doc_id"],
    },
)
```

后端 provider 执行时再接收 `RequestContext`，并在读取 artifact 前完成文档权限校验。

**实现要点**：
1. 权限校验同 read_document_page
2. 读取 `artifacts/tables.json`
3. 按 table_id 精确匹配，或按 page 范围匹配
4. 返回 rows + markdown + quality_flags

### B4.6 工具接入 ToolGateway

两个工具必须作为 `ToolProvider` / `ToolExecutionFacade` provider 接入 `ToolGateway`，不能直接塞进 legacy tool list，也不能绕过权限体系：

```python
class PdfDocumentToolProvider:
    async def list_tools(self) -> list[ToolDefinition]:
        if not config.pdf_agent_tools_enabled:
            return []
        return [READ_DOCUMENT_PAGE_TOOL, EXTRACT_DOCUMENT_TABLE_TOOL]

    async def execute_tool_with_context(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        ctx: RequestContext,
    ) -> dict[str, Any]:
        # 在这里做 DocumentAccessService 权限校验和 artifact 读取。
        ...
```

`pdf_agent_tools_enabled=False` 必须保持默认值。注册后，模型只能看到 `doc_id/page/table_id` 这类业务参数；真实用户、部门、权限和 trace 由后端 context 注入。

### B4.7 验收标准

**单元测试**：
```bash
tests/test_pdf_document_tools.py
```

测试用例：
- `test_read_page_success`：有权限时能读到页内容
- `test_read_page_permission_denied`：无权限时返回 error
- `test_read_page_out_of_range`：页码超范围返回 error
- `test_extract_table_by_id`：按 table_id 能抽到表
- `test_extract_table_by_page`：按 page 能抽到表
- `test_extract_table_permission_denied`：无权限返回 error
- `test_read_page_permission_denied_no_content_leak`：无权限时不泄露标题、正文、页码片段、artifact path
- `test_extract_table_permission_denied_no_table_leak`：无权限时不泄露表头、行数据、table_id 之外的内部路径
- `test_tool_schema_has_no_context_or_owner`：模型可见 schema 不包含 `RequestContext`、`owner_id`、部门、artifact path

**集成验证（手工）**：
```bash
# 1. 启动后端
# 2. 用 Agent 模式问："查看工艺部 PDF 第 3 页的内容"
# 3. 观察是否调用 read_document_page 工具
# 4. 问："这个文档有哪些表格？"
# 5. 观察是否调用 extract_document_table
```

**回归测试**：
```bash
uv run pytest tests/test_knowledge_tool.py -q --no-cov
# 现有知识工具测试不受影响
```

### B4.8 失败分类

- `tool_not_callable`：Agent 调不到工具 → 检查 ToolGateway 注册
- `permission_bypass`：跨部门读到了不该读的文档 → 检查权限校验逻辑
- `metadata_leak_on_denied`：无权限错误泄露标题、正文、页码、表头或 artifact path → 收紧错误响应
- `artifact_parse_error`：blocks/tables.json 格式异常 → 补 schema 校验或 try-except
- `page_number_mismatch`：返回的 page 和 source_ref 不一致 → 检查 blocks 过滤条件

### B4.9 配置与开关

新增配置：
```python
# app/config.py
pdf_agent_tools_enabled: bool = False  # 默认关闭
```

只有显式启用后，工具才注册到 Agent。

### B4.10 下一步门禁

B4 完成后，PDF P4 阶段收口。生产启用还必须额外满足：权限拒绝不泄露内容、E1 permission/scope/citation 回归通过、PDF 页码/表格 eval 通过、`pdf_agent_tools_enabled=False` 仍是默认值且启用/回滚记录已写入 `PROJECT_STATE.md`。

### B4.11 当前执行结果（2026-06-09）

已完成：
- `app/config.py` 新增 `pdf_agent_tools_enabled=False`，默认不注册 PDF Agent 工具。
- 新增 `app/enterprise/tools/pdf_document_provider.py`：
  - `PdfDocumentToolProvider.list_tools()` 只有在开关显式启用时返回 `pdf.read_document_page` / `pdf.extract_document_table`。
  - `execute_tool_with_context(...)` 由 `ToolGateway.execute(context, tool_id, arguments)` 后端注入 `RequestContext`；模型可见参数只包含 `doc_id`、`page`、`table_id`。
  - provider 先通过 `KnowledgeMetadataStore.get_document()` 取 `DocumentRecord`，再调用 `DocumentAccessService.can_read_document(context, document)`；权限通过后才读取 `blocks.json` / `tables.json`。
  - 无权限响应固定为 `{"status": "error", "error": "permission_denied"}`，不返回文件名、正文、表格内容或 artifact path。
  - 页读取支持顶层 list 和 `{"blocks": [...]}` 两种现有 artifact 形态；表格读取支持顶层 list 和 `{"tables": [...]}`。
- `build_local_agent_tool_gateway()` 接入 `PdfDocumentToolProvider()`，PDF 工具 id 纳入 local agent default-allowed 集合；由于 provider 默认不注册，旧 RAG 工具列表保持不变。

新增测试：
- `tests/test_pdf_document_tools.py`
  - 默认关闭时不注册 PDF 工具。
  - 模型可见 schema 不包含 `RequestContext`、`owner_id`、权限对象或 artifact path。
  - bindable tool 暴露的是 `doc_id/page/table_id`，不是泛型 `arguments`。
  - gateway 注入 context 后，有权限用户可按页读取内容并返回 source_refs。
  - 无权限用户读取页或表时不泄露标题、正文、表格值或 artifact path。
  - 支持按 `table_id` 和按 `page` 抽表。
  - local agent gateway 只有在 `pdf_agent_tools_enabled=True` 时才列出 PDF 工具。

当前验收：
- B4 default-off 模块级接入完成。
- 生产启用仍未开放；启用前还需要真实 indexed PDF 页码/表格 smoke、E1 permission/scope/citation 复跑、PDF page/table eval 复跑、回滚记录和 `PROJECT_STATE.md` 启用记录。

## A3：RAG R2 query rewrite shadow（P2，条件触发）

### A3.1 触发条件

**只有满足以下所有条件，才进入 A3**：

1. 18q current-scope baseline 中仍有失败题，且 triage 归因为 `retrieval_no_hit` 或召回排序问题。
2. keyword gap 分析显示"query 表达与文档用词不匹配"是主要原因。
3. **当前状态**：18/18 通过，剩余 2 题是 out_of_scope → **不满足触发条件，A3 暂缓**。

如果后续新增 evalset 或资料扩充后出现上述情况，再启动 A3。

### A3.2 目标（当触发时）

在权限 scope 已锁定后，把用户问题改写成更适合召回的表达，但只做 shadow 观测，不改变真实检索结果。

### A3.3 实施步骤（当触发时）

**步骤 1：新增 query_rewrite.py 模块**

```python
# app/enterprise/rag/query_rewrite.py
from pydantic import BaseModel, Field

class RewriteCandidate(BaseModel):
    query: str
    strategy: str  # e.g., "term_expansion", "synonym"
    reason: str
    protected_terms_used: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)

class RewritePlan(BaseModel):
    original_query: str
    active_query: str  # shadow 阶段仍是 original_query
    candidates: list[RewriteCandidate] = Field(default_factory=list)
    protected_terms: list[str] = Field(default_factory=list)  # 文件名、告警名、技术词
    mode: str  # "off" | "shadow" | "rules_active"
    scope_locked: bool
    rewrite_trace: dict[str, Any] = Field(default_factory=dict)

class QueryRewriter:
    def rewrite(self, query: str, context: RetrievalContext) -> RewritePlan:
        # 提取保护词（文件名、doc_id、告警名、引号内容）
        # 应用规则生成候选（同义词、术语扩展）
        # 返回 RewritePlan，但 active_query 仍是 original（shadow 模式）
```

**步骤 2：在 RetrievalOrchestrator 注入 rewrite**

在 `retrieve()` 调用前生成 `RewritePlan`，记录到 diagnostics，但真实检索仍用 `original_query`。

**步骤 3：配置与开关**

```python
# app/config.py
rag_query_rewrite_mode: str = "off"  # "off" | "shadow" | "rules_active"
```

第一版只支持 "off" 和 "shadow"。

### A3.4 验收标准（当触发时）

**单元测试**：
```bash
tests/test_query_rewrite.py
```

测试用例：
- `test_protected_terms_preserved`：文件名、告警名不被改写
- `test_shadow_mode_no_change`：shadow 模式下 active_query == original_query
- `test_rewrite_trace_recorded`：diagnostics 中有 rewrite_trace

**集成验证**：
```bash
# 跑 18q，检查每个 sample 的 retrieval response 中是否有 rewrite_trace
# 确认 rewrite_trace 存在但 actual_query_used 仍是 original
```

### A3.5 当前决策

**A3 暂不执行。** 因为当前 18/18 通过，没有检索表达问题的证据。记录为 backlog，等后续 eval 扩展或资料增加后再评估。

---

## D1：routing shadow 诊断字段（P2）

### D1.1 目标

为 `app/enterprise/routing/` 补 `domain`、`intent`、`approval_required`、`execution_mode` 诊断字段，用于后续路由语义升级的 eval 基础。

### D1.2 前置条件

- G0 已完成。
- `app/enterprise/routing/router.py` 已存在 `StrategyRouter`。

### D1.3 实施步骤

**步骤 1：优先把诊断字段放进 `RoutingDecision.metadata`**

```python
# app/enterprise/routing/models.py

class RoutingDecision(BaseModel):
    route: RouteName
    provider: RoutingProviderName
    reason: str
    risk_level: RoutingRiskLevel = "low"
    required_capabilities: list[str] = Field(default_factory=list)
    fallback_route: RouteName | None = "chat"
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

当前 `RoutingDecision` 是 Pydantic `BaseModel`，不是标准库数据类。第一版不建议新增一批一等字段，以免破坏现有 schema / audit 消费方；把 shadow-only 诊断写入 `metadata["routing_diagnostics"]` 即可。如果未来要升为一等字段，必须用 Pydantic `Field(...)` 并同步更新所有 schema 测试。

**步骤 2：在 `StrategyRouter.evaluate(...)` 返回前补 metadata**

```python
# app/enterprise/routing/router.py

def _with_shadow_diagnostics(
    decision: RoutingDecision,
    *,
    payload: dict[str, Any],
) -> RoutingDecision:
    diagnostics = {
        "domain": infer_domain(decision.route),
        "intent": infer_intent(payload, decision.route),
        "approval_required": infer_approval_required(payload, decision.route),
        "execution_mode": infer_execution_mode(decision.route),
    }
    metadata = {
        **decision.metadata,
        "routing_diagnostics": diagnostics,
    }
    return decision.model_copy(update={"metadata": metadata})
```

当前 `StrategyRouter` 没有 `route()` 方法，真实入口是：

```python
StrategyRouter.evaluate(context, route=actual_route, payload=payload)
StrategyRouter.record_shadow_decision(...)
```

D1 只能补 shadow diagnostics，不能让 metadata 反向改变 `decision.route` 或实际执行 route。

**步骤 3：diagnostics 进入 audit trace**

确保 `RoutingDecision.diagnostics` 被写入 `AuditService` 或响应的 diagnostics 字段。

### D1.4 验收标准

**单元测试**：
```bash
tests/test_enterprise_strategy_router.py
```

测试用例：
- `test_database_route_has_domain_metadata`：数据库查询的 `metadata.routing_diagnostics.domain="database"`
- `test_aiops_route_has_intent_metadata`：AIOps 诊断的 `metadata.routing_diagnostics.intent="diagnose"`
- `test_approval_required_for_high_risk_metadata`：高风险操作的 `metadata.routing_diagnostics.approval_required=True`
- `test_diagnostics_not_affect_route`：诊断字段不改变真实 route

**集成验证**：
```bash
# 跑几条不同类型的请求，检查响应 diagnostics 中是否有 routing.domain/intent 等字段
curl -X POST .../api/chat -d '{"query":"查询数据库"}'
# 观察响应 JSON 中 diagnostics.routing
```

**回归测试**：
```bash
uv run pytest tests/test_enterprise_gateway_routes.py -q --no-cov
# 现有路由测试不受影响（因为只加诊断字段，不改路由逻辑）
```

### D1.5 失败分类

- `diagnostics_missing`：响应中无 routing diagnostics → 检查 audit 写入点
- `domain_inference_wrong`：domain 推断错误 → 调整 _infer_domain 规则
- `regression_route_changed`：真实 route 被改了 → 回滚，确保 shadow-only

### D1.6 下一步门禁

D1 完成后，routing shadow 基础建立。后续 D2/D3（RAG 分流上移、DB 确认链路修正）作为独立共享边界收口任务，不在清单 2 范围内。

### D1.7 当前执行结果（2026-06-09）

已完成：
- `app/enterprise/routing/router.py` 在 `StrategyRouter.evaluate(...)` 返回前调用 `_with_shadow_diagnostics(...)`，把诊断字段写入 `RoutingDecision.metadata["routing_diagnostics"]`。
- 新增诊断字段：
  - `domain`：由建议 route 推断为 `knowledge` / `aiops` / `database` / `admin` / `governance` / `general`。
  - `intent`：由建议 route 和风险级别推断为 `knowledge_retrieval`、`incident_diagnosis`、`database_read/write`、`admin_management`、`approval_required` 或 `plain_chat`。
  - `approval_required`：当建议 route 是 `human_review`、风险为 high 或 required capability 包含 `human_review` 时为 true。
  - `execution_mode`：记录建议执行形态，如 `retrieval`、`agent_workflow`、`governed_tool`、`admin_api`、`approval_gate`、`direct_response`。
  - `actual_route` / `shadow_only`：明确这是 shadow 诊断，不能反向改变真实执行 route。
- `record_shadow_decision(...)` 继续通过 `_decision_metadata(...)` 写 audit；因为 metadata 自动展开，`routing_diagnostics` 已进入 `routing_decision` audit event。
- 未给 `RoutingDecision` 增加一等字段，未改变 provider 判定顺序，未改变 chat / aiops adapter 的真实执行路径。

新增/扩展测试：
- `tests/test_enterprise_strategy_router.py`
  - route 决策仍保持原值。
  - knowledge / aiops / human_review 等样本包含 `routing_diagnostics`。
  - audit event 中包含 `routing_diagnostics`。
  - chat / aiops HTTP 路径记录 shadow 诊断，但响应和 stream 行为不变。

当前验收：
- D1 shadow diagnostics 完成。
- 后续 D2/D3 仍作为独立共享边界收口任务，不在清单 2 当前实现范围内。

## E1：评测体系扩展：系统能力维度（P2）

### E1.1 目标

补齐权限隔离、scope 锁定、跨库不串、citation 准确性等系统能力维度的 evalset，而不只测内容召回。

### E1.2 当前评测缺口

当前 18q current-scope 中：
- 约 15 题是内容类题（"这个问题的答案是什么"）
- 3 题是系统能力题（RAG-18/19/20：source_ref 回查、chunk_id 解析、PDF 失败门禁）

**系统能力题占比仍然过低**（约 3/18），无法充分守护权限、scope、citation 这些关键能力。18/18 只能作为当前 3 个 indexed 文档的小样本 baseline，不能代表长期评测充分。

### E1.3 新增 evalset 设计

**evalset 1: 权限隔离题（department_rag_permission_isolation_10q.jsonl）**

每题测试一个权限边界：
```jsonl
{"sample_id":"PERM-01","query":"查询工艺部的安全隔离文档","user_department":"process_digital_dept","allowed_kb_ids":["process_digital_dept"],"expected_doc_ids":[],"expected_failure":"permission_filtered","scope":"scoped"}
{"sample_id":"PERM-02","query":"跨部门搜索所有安全相关文档","user_department":"process_digital_dept","allowed_kb_ids":["process_digital_dept","craft_dept"],"expected_doc_ids":["doc_xxx"],"scope":"auto"}
...
```

**评分规则**：
- 用户 A 能搜到自己部门文档 → pass
- 用户 A 搜不到其他部门文档 → pass
- 用户 A 搜到了不该看的文档 → **hard fail (wrong_scope)**

**evalset 2: scope 锁定题（department_rag_scope_lock_10q.jsonl）**

测试 scope 选择器是否准确：
```jsonl
{"sample_id":"SCOPE-01","query":"运维手册的告警处理","allowed_kb_ids":["process_digital_dept"],"expected_doc_ids":["doc_6627ee79..."],"retrieved_must_not_contain_kb":["craft_dept"],"scope":"scoped"}
{"sample_id":"SCOPE-02","query":"工艺部的设备检修","allowed_kb_ids":["craft_dept"],"expected_doc_ids":["doc_27b282ca..."],"retrieved_must_not_contain_kb":["process_digital_dept"],"scope":"scoped"}
...
```

**评分规则**：
- 选对了 kb → pass
- 串到了不该串的 kb → **hard fail (wrong_scope)**

**evalset 3: citation 准确性题（department_rag_citation_accuracy_10q.jsonl）**

测试 source_ref 完整性和可解析性：
```jsonl
{"sample_id":"CITE-01","query":"运维交接流程","expected_doc_ids":["doc_6627ee79..."],"expected_source_ref_fields":["kb_id","doc_id","chunk_id","page_start","source_file"],"citation_must_resolvable":true}
...
```

**评分规则**：
- source_ref 字段齐全 → pass
- 能在 metadata store 回查到 chunk → pass
- source_ref 缺失或回查失败 → **hard fail (citation_unresolvable)**

### E1.4 实施步骤

**步骤 1：编写 3 个 evalset**

每个 evalset 10 题，覆盖典型边界场景。

**步骤 2：扩展 eval runner**

修改现有 `run_department_rag_eval.py` 或新建 runner，支持：
- `permission_filtered` 失败分类
- `wrong_scope` 硬失败判定
- `citation_unresolvable` 硬失败判定

**步骤 3：生成 baseline 报告**

```bash
uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_permission_isolation_10q.jsonl \
  --output-json evals/knowledge_base/reports/permission_isolation_baseline_20260608.json

# 同理跑 scope_lock 和 citation_accuracy
```

### E1.5 验收标准

**evalset 结构测试**：
```bash
tests/test_knowledge_base_evalsets.py
# 新增测试用例验证 3 个新 evalset 的 schema
```

**eval runner 测试**：
```bash
tests/test_rag_eval_runner.py
# 测试 wrong_scope 和 citation_unresolvable 能被正确识别
```

**baseline 报告**：
- 3 个 evalset 各生成一份报告
- 报告中 `wrong_scope_rate` 和 `citation_unresolvable_rate` 单独统计
- 每个失败样本有明确原因（permission_filtered / wrong_scope / citation_unresolvable）

### E1.6 失败分类

- `evalset_schema_invalid`：新 evalset 格式错误 → 修正 schema
- `wrong_scope_not_detected`：跨库召回未被标为失败 → 检查 eval 判定逻辑
- `citation_check_too_loose`：source_ref 缺字段但仍 pass → 收紧校验规则

### E1.7 长期维护

- 每次增加新知识库时，补对应的权限隔离题
- 每次修改 scope 路由逻辑时，跑 scope_lock eval
- 每次修改 citation 合同时，跑 citation_accuracy eval
- 每次启用 memory active、tool offload、PDF Agent tools 或 query rewrite，都必须复跑 E1 护栏并记录报告路径。
- 每次 evalset 从 18q / 30q 小样本扩展到新语料时，必须保留历史 baseline，不用覆盖旧报告制造“持续 100%”假象。

### E1.8 下一步

E1 第一切片完成后，评测体系从"内容为主"变成"内容 + 系统能力并重"。后续可以根据 eval 失败分布，决定是补资料、修 scope 路由，还是补 citation 校验。

### E1.9 当前执行结果（2026-06-09）

已完成：
- 新增 `department_rag_permission_isolation_10q.jsonl`
- 新增 `department_rag_scope_lock_10q.jsonl`
- 新增 `department_rag_citation_accuracy_10q.jsonl`
- 扩展 `run_department_rag_eval.py`，支持 `permission_filtered`、`wrong_scope`、`citation_unresolvable` 的硬失败统计
- 扩展 `tests/test_knowledge_base_evalsets.py`，覆盖 3 份 evalset 结构、permission-filtered 期望通过、forbidden KB 返回硬失败、citation 回查失败硬失败和 summary rate

Baseline 结果：

| evalset | 结果 | 结论 |
|---|---:|---|
| permission_isolation_10q | 10/10 passed, permission_filtered_passed=10 | 已修复“跨权限意图不应从无关 allowed KB 回答”的语义，权限护栏当前小样本为绿 |
| scope_lock_10q | 9/10 passed, 1 answer_wrong | scope 锁定未发现跨库串库，但仍有 1 个内容匹配问题 |
| citation_accuracy_10q | 10/10 passed | 当前 3 文档小样本 source_ref 回查可解析 |

报告文件：
- `evals/knowledge_base/reports/department_rag_permission_isolation_baseline_20260609.json`
- `evals/knowledge_base/reports/department_rag_scope_lock_baseline_20260609.json`
- `evals/knowledge_base/reports/department_rag_citation_accuracy_baseline_20260609.json`

门禁结论：
- E1 护栏基础设施已落地。
- permission isolation 与 citation 当前绿；scope lock 没有跨库串库，但仍有 1 个内容匹配问题需要作为后续 eval/内容质量项跟踪。
- C4/C5/B4/D1 已完成默认关闭 / shadow / 本地验证级接入；不能因为 E1 小样本变绿就生产 active。
- 后续只剩 A3 条件触发项，或单独补 B4 真实 indexed PDF smoke；生产启用前仍必须补 TTL / cleanup / stale summary / audit evidence / permission no-leak / rollback 这些门禁。

---

## 附录 A：清单 2 执行顺序建议

按依赖关系和优先级：

1. **G0**（已完成，只保留为审计记录）
2. **E1**（评测护栏，2-3 天；可先做，也可与 C4 并行）
3. **C4**（memory 接入 RAG prompt，约 2 天）
4. **C5**（AIOps offload，约 1 天；先做 prompt 展示截断，不破坏原始证据）
5. **B4**（已完成 default-off；必须通过 ToolGateway 后端注入 context）
6. **D1**（已完成；只写 metadata，不改真实 route）
7. **A3**（仅当 eval 证据触发时才做）

剩余推荐集：A3 仍为条件触发；D2/D3 作为独立共享边界收口任务，不在清单 2 当前实现范围内（不含已完成的 G0/E1/C4/C5/B4/D1）。

---

## 附录 B：验收检查清单

每完成一节，跑以下全量回归：

```bash
# 单元测试
uv run pytest tests/ -q --no-cov -k "not slow"

# 静态检查
uv run ruff check --select F,E9,I app tests evals
uv run python -m compileall app tests evals

# git 检查
git diff --check

# evalset 回归
uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_18q_current_scope_20260608.jsonl

# AIOps smoke：使用当前项目脚本
python3 aiops_lab/cmdb/seed.py
docker compose -f aiops_lab/docker-compose.yml up --build -d
uv run python aiops_lab/scripts/smoke_aiops.py \
  --skip-aiops-api \
  --output aiops_lab/reports/smoke_aiops_lab_only_checklist2.json
NO_PROXY=localhost,127.0.0.1,::1 no_proxy=localhost,127.0.0.1,::1 \
  uv run python aiops_lab/scripts/smoke_aiops.py \
    --api-url http://127.0.0.1:9900 \
    --output aiops_lab/reports/smoke_aiops_full_api_checklist2.json
docker compose -f aiops_lab/docker-compose.yml down
```

---

## 附录 C：失败时的回滚策略

每节的改动都应该在独立分支上开发，验收通过后再 merge：

```bash
# 开始新节前
git switch enterprise2
git switch -c codex/c4-memory-integration

# 开发...

# 验收失败
git switch enterprise2
git branch -D codex/c4-memory-integration

# 验收通过
git switch enterprise2
git merge --no-ff codex/c4-memory-integration
git branch -d codex/c4-memory-integration
```

---

## 附录 D：长期运行风险控制

清单 2 完成后，长期运行需要关注。以下条目是 **active / production 前置门禁**，不是已经自动完成的能力：

| 风险 | 必须落实的控制 | 当前状态 |
|---|---|---|
| memory SQLite 表持续增长 | TTL、容量上限、owner 级清理命令、DB size 统计 | C4 active 前必须补 |
| tool offload SQLite 表持续增长 | TTL、最大单条大小、最大 session 累计大小、后台清理 | C5 active 前必须补 |
| memory summary 过期 | `updated_at` / `expires_at` 或等价 stale 判断；过期不注入 active prompt | C4 active 前必须补 |
| prompt 注入成本和幻觉面 | `memory_mode=off/shadow/active`、注入长度上限、明确“不是资料引用” | C4 必测 |
| offload 摘要破坏审计/eval | prompt 只用摘要；完整原文必须 owner-checked 可回查；summary-only 阻塞验收 | C5 必测 |
| PDF doc_id/page 泄露 | ToolGateway 后端注入 `RequestContext`；先 `DocumentAccessService` 校验再读 artifact；拒绝响应不泄露正文/路径 | B4 必测 |
| evalset 过期 | 18q 只是当前小样本；新增知识库/权限模型/PDF 工具/memory active 后必须扩展并复跑 E1 | E1 长期维护 |
| 配置误开 | 默认 `off` / `False` / shadow；生产启用前写 `PROJECT_STATE.md`、eval 证据和回滚记录 | 硬边界 |

不能说“清单已考虑风险”就等于“长期运行无风险”。准确表述是：风险已进入开发门禁；在对应 TTL、清理、stale、权限、审计和 eval 复跑能力落地前，只能本地或 shadow，不能生产 active。

---

**清单 2.1 结束**
