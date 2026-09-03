# RagWithAIOps

企业知识库与智能运维 Agent：用一个 FastAPI 服务串起文档解析、RAG 检索、证据引用、告警诊断和企业治理控制。

## 能力

- **企业知识库问答**：支持 Markdown、TXT、PDF、DOCX、XLSX；结构化分块后写入 Milvus，提供 dense / sparse / hybrid 检索与可选重排。
- **证据型回答**：检索结果保留 `source_ref`、页码/表格元数据和引用信息，回答链路支持证据选择与 SSE 流式输出。
- **AIOps 诊断**：LangGraph Plan-Execute-Replan 工作流通过 MCP 调用日志、指标、服务和历史工单工具，输出可追溯诊断报告。
- **企业治理**：RequestContext、权限过滤、审批、MySQL 安全查询、审计事件和离线评测门禁覆盖高风险操作。
- **异步处理**：Redis/RQ 负责 PDF/DOCX/XLSX 解析与索引任务；Docker Compose 提供 Milvus、MinIO 和 Redis 本地依赖。
- **可观测性与评测**：JSONL/SQLite Trace、SSE 契约检查、RAG 评测和企业 Agent 评测脚本均位于 `evals/`。

## 技术栈

Python 3.11-3.13 · FastAPI · LangChain · LangGraph · Milvus · Redis/RQ · MCP/FastMCP · MySQL/sqlglot · Docker · SSE

## 快速开始

```bash
git clone https://github.com/cici-uu8/RagWithAIOps.git
cd RagWithAIOps

uv sync --extra dev
cp .env.example .env
# 在 .env 中填入 DASHSCOPE_API_KEY；不要提交 .env

docker compose -f vector-database.yml up -d
make start
```

服务默认地址：<http://localhost:9900>，API 文档：<http://localhost:9900/docs>。

需要运行 AIOps MCP 示例时：

```bash
make start-cls
make start-monitor
make status-mcp
```

需要处理 PDF/DOCX/XLSX 时，另开终端运行：

```bash
uv run python -m app.workers.document_processing_worker
```

## 代码导航

```text
app/
  api/                    FastAPI 路由
  enterprise/             权限、审批、审计、数据库和评测契约
  agent/aiops/            Planner / Executor / Replanner
  services/               RAG、文档解析、分块、向量索引和队列
  tools/                  知识库、数据库和记忆工具
aiops_lab/                合成故障场景与 AIOps 实验工具
mcp_servers/              CLS 日志与 Monitor 指标 MCP 服务
evals/                    RAG、AIOps、Trace 和企业评测脚本
tests/                    后端、前端契约和安全边界测试
static/                   对话页、管理台和执行看板
aiops-docs/               不含企业私有数据的通用运维示例
```

更完整的模块说明见 [`docs/enterprise-agent.md`](docs/enterprise-agent.md)，安全边界见 [`docs/security.md`](docs/security.md)。

## 验证

```bash
uv run ruff check app aiops_lab mcp_servers evals tests
uv run pytest -q --no-cov
uv run python -m compileall -q app aiops_lab mcp_servers evals tests
```

离线 Agent 评测门禁示例：

```bash
uv run python -m evals.enterprise.run_agent_eval_scorecard \
  --trace-evalset <trace-evalset.jsonl> \
  --audit-events <audit-events.jsonl>
```

## 配置与安全

所有凭据、数据库连接、日志、上传文件、向量数据和评测运行产物均应留在本地或部署环境，并已加入 `.gitignore`。复制 `.env.example` 后按需配置；生产环境必须替换默认 JWT secret，并通过密钥管理系统注入 API key。

## 许可

代码按 MIT License 发布；第三方来源和 WeKnora 复用说明见 [`NOTICE`](NOTICE)。
