# RAG Beta Readiness 生产试运行闭环

日期：2026-06-12

状态：`beta_readiness_minimum_loop_ready`

## 1. 当前可对外说明的能力

当前只固化以下能力口径：

```text
indexed_docs = 30
retrieval_evalset = Mixed 54q after C6-P2
retrieval_baseline = 45/54 passed (83.3%)
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
answer_hard_safety_gates = clean
answer_coverage = limited
```

当前 MVP / beta 基线入口：

```text
docs/RAG_MVP_Baseline_20260612.md
docs/RAG_Production_Readiness_Checklist.md
```

解释口径：

- Corpus 已从 18 indexed docs 扩到 30 indexed docs，覆盖 Markdown、PDF、AIOps/DB runbook 和 craft PDF。
- Retrieval 层在派生 Mixed 54q 上为 45/54，通过率 83.3%；新增 Redis/MySQL 4q 全部通过，原 50q 样本无状态退化。
- 安全边界干净：没有 wrong scope，citation/source_ref 都能回查。
- Answer 层只能说明硬安全门禁干净：缺 citation、unsupported claim、permission leak、source_ref unresolvable 这类硬问题没有出现。
- Answer 覆盖率仍有限，不对外承诺 Answer 50q、复杂 agent behavior 或 90%+ 准确率。

## 2. 真实运行 smoke

新增 smoke runner：

```text
evals/knowledge_base/beta_readiness_smoke.py
```

默认命令：

```bash
.venv/bin/python -m evals.knowledge_base.beta_readiness_smoke \
  --output evals/knowledge_base/reports/beta_readiness_smoke_20260612.json
```

本次已运行，结果：

```text
status = passed
check_count = 7
passed_count = 7
failed_count = 0
external_llm_called = false
external_vector_db_called = false
```

覆盖检查：

| 检查项 | 方式 | 通过证据 |
|---|---|---|
| 登录 | FastAPI TestClient 调 `/api/auth/login` | admin 登录返回 bearer token 和 user profile |
| RAG 问答 | 受控本地 corpus 走 `RagAdapter -> RetrievalService` | 只返回授权文档并生成受控答案 |
| source_ref 回查 | 用 `KnowledgeMetadataStore` 反查 chunk | `doc-visible:c00001` 可解析回 chunk |
| 权限过滤 | 同一查询同时给 visible/hidden raw hits | hidden doc 被过滤，不进入 context/answer |
| 配置默认值 | 读取 `app.config.config` | dense_only / off / false / top_k=3 |
| 日志/audit | `InMemoryAuditSink` 捕获事件 | `permission_checked` 和 `rag_retrieval` 均出现 |
| 用户反馈字段 | `validate_feedback_record()` | 必填字段完整时无错误 |

边界：

- 这个 smoke 是 beta 前置的受控真实服务边界检查，不是线上负载测试。
- 默认 smoke 不调用外部 LLM，不调用外部向量库，避免把外部服务抖动误判成产品失败。
- 已额外运行真实 corpus 的 Redis/MySQL 4q retrieval pilot，只读、不写正式报告，结果仍为 4/4，source_ref 全部可回查。
- 若需要完整在线 smoke，再单独启动服务并执行真实 `/api/chat`，该结果必须标注为 live observation，不得覆盖当前 retrieval baseline。

## 3. 用户反馈入口

Beta 用户材料：

```text
docs/RAG_Beta_生产试运行用户材料.md
```

正式反馈入口文件：

```text
docs/RAG_Beta_User_Feedback_Log.md
```

反馈 schema：

```text
docs/schemas/rag_user_feedback.schema.json
```

每条反馈必须记录：

| 字段 | 含义 |
|---|---|
| `timestamp` | 反馈时间 |
| `user_id` | 用户标识，不能写明文密码/token |
| `session_id` | 会话标识 |
| `query` | 用户原始 query |
| `retrieved_docs` | 召回文档 doc_id/source_file/kb_id/rank |
| `answer` | 系统回答 |
| `answer_issue` | 用户指出的问题类型 |
| `missing_facts` | 缺失事实点 |
| `source_refs` | 回答或召回中的 source_ref |
| `source_ref_resolvable` | source_ref 是否可回查 |
| `permission_scope_issue` | 是否疑似权限/scope 问题 |
| `followup_decision` | 后续处理决定 |

反馈分类建议：

```text
answer_incomplete
answer_wrong
source_ref_unresolvable
permission_scope_issue
retrieval_no_hit
retrieval_wrong_doc
expression_gap
other
```

## 4. 下一轮优化触发规则

下一轮优化只从真实用户反馈触发，不再靠假设扩题。

触发条件：

- 同一类真实反馈累计出现 3 条以上，且能复现。
- 每条反馈都有原始 query、召回文档、回答、缺失事实和 source_ref 回查结果。
- 如果问题是 `source_ref_unresolvable` 或 `permission_scope_issue`，优先作为安全/引用 bug 处理。
- 如果问题集中在 `answer_incomplete`，重开 `S5 Answer revisit`，但只做窄 pilot，不直接扩 Answer 50q。
- 如果问题集中在 `retrieval_no_hit` 或 `retrieval_wrong_doc`，再回到 retrieval 失败分流，不默认启用 hybrid/rerank/query rewrite。

不触发条件：

- 单个孤立 bad case。
- 只来自内部假设、合成样本或未确认的 prompt 直觉。
- 没有 source_ref 回查证据的主观评价。
- 没有用户真实 query 的二手描述。

## 5. 保留 Answer 层为后续专项

Answer 层当前结论：

- 硬安全门禁干净，这是可对外说明的底线能力。
- 覆盖率仍有限，不应直接进入 Answer 50q、RAGAS 主 gate 或 agent_behavior acceptance。
- 如果真实用户反馈集中在“答案不完整”，再重开 S5 Answer revisit。

S5 Answer revisit 的默认顺序：

1. 从真实反馈中挑 5-10 个 confirmed answer-incomplete 样本。
2. 复现当前 baseline，确认是 Answer 层问题，不是 retrieval/source_ref/scope 问题。
3. 做窄范围 prompt/context/prompt-output contract pilot。
4. 窄 pilot 有效后，再讨论是否扩到 Answer 50q。

## 6. 明确不做

本阶段不做以下事情：

- 不修改 `app/config.py` 或 `.env`。
- 不改 `rag_default_retrieval_mode=dense_only`。
- 不启用 query rewrite。
- 不启用 rerank。
- 不默认切 hybrid。
- 不创建 Answer 50q。
- 不把 OpenJudge/RAGAS 作为主 gate。
- 不进入 agent_behavior acceptance。
- 不承诺 Answer 覆盖率已经稳定。

## 7. 恢复方式

下次恢复时先运行：

```bash
.venv/bin/python -m evals.knowledge_base.beta_readiness_smoke \
  --output evals/knowledge_base/reports/beta_readiness_smoke_YYYYMMDD.json
```

如果要验证真实 indexed corpus 的 Redis/MySQL 检索：

```bash
.venv/bin/python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_c6_p2_redis_mysql_retrieval_4q.jsonl \
  --no-write
```

只有在 smoke 通过且真实反馈出现集中失败模式后，才进入下一轮专项优化。
