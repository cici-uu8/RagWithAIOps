# Enterprise Agent Architecture

## Purpose

`RagWithAIOps` combines enterprise knowledge retrieval and operational diagnosis in one service. The repository is intentionally split into reusable adapters and services so that model calls, tool execution, data access, and governance checks remain testable independently.

## Request flows

### Knowledge question

```text
HTTP /api/chat or /api/chat_stream
  -> RequestContext / RequestGateway
  -> RagAgentService (LangGraph)
  -> query intent + permission-filtered retrieval
  -> Milvus vector search + optional sparse/rerank shadow path
  -> evidence selection and source_ref/citation assembly
  -> answer or SSE events
```

Document ingestion follows `upload -> parser router -> structured chunks -> artifact validation -> embedding/indexing`. PDF parsing can use MinerU when available; the default path is configured through environment variables rather than a machine-specific absolute path.

### Operational diagnosis

```text
HTTP /api/aiops
  -> AIOpsService
  -> LangGraph Planner
  -> Executor -> MCP CLS / Monitor tools
  -> Replanner (continue, recover, or stop)
  -> structured diagnosis report + SSE events
```

The included `mcp_servers/` implementations return deterministic example data. Replace those adapters with an authorized CLS, Prometheus, Grafana, ticketing, or internal monitoring connector in a deployment environment.

## Governance boundaries

- `RequestContext` carries identity and trace IDs through adapters.
- Permission filters run before knowledge retrieval and database reads.
- MySQL operations pass through operation classification, allowlists, confirmation, and audit events.
- High-risk tool calls can require approval; audit events are designed for offline evidence verification.
- `evals/enterprise/` contains offline Trace and audit gates. They are release-readiness tools, not production request middleware or CI hard gates.

## Module map

| Area | Entry points |
| --- | --- |
| API | `app/main.py`, `app/api/` |
| RAG | `app/services/rag_agent_service.py`, `app/services/vector_*`, `app/enterprise/rag/` |
| Document ingestion | `app/services/document_ingestion_service.py`, `app/services/mineru_parser_adapter.py`, `app/services/artifact_*` |
| AIOps | `app/services/aiops_service.py`, `app/agent/aiops/` |
| MCP | `app/agent/mcp_client.py`, `mcp_servers/` |
| Enterprise controls | `app/enterprise/auth/`, `permissions/`, `gateway/`, `database/`, `observability/` |
| Evaluation | `evals/enterprise/`, `evals/knowledge_base/`, `tests/` |

## Extending the system

1. Add a provider or adapter at the boundary that owns the external integration.
2. Keep `RequestContext`, `source_ref`, and audit metadata intact across the boundary.
3. Add a focused test before changing a default or enabling a live integration.
4. Keep secrets and generated reports outside Git; use `.env.example` only for names and safe defaults.
