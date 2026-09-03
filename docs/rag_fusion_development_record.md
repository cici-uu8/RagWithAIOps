# RAG And AIOps Development Record

This public record summarizes the implementation boundaries that are useful
when reviewing or extending `RagWithAIOps`. Private run logs, uploaded source
documents, credentials, screenshots, and generated reports are intentionally
kept outside the repository.

## Current public baseline

- RAG request flow is implemented in `app/services/rag_agent_service.py` and
  `app/enterprise/rag/`, with permission-aware retrieval and source references.
- Document ingestion supports text and office/PDF routes through parser,
  chunking, artifact validation, embedding, and indexing services.
- AIOps uses LangGraph Planner/Executor/Replanner nodes and MCP adapters for
  deterministic example log and metric tools.
- Enterprise controls live under `app/enterprise/`: request context, gateway,
  permissions, approvals, MySQL safety checks, and audit/trace models.
- Offline evaluation scripts under `evals/` verify retrieval, answers, SSE
  traces, audit evidence, and Agent scorecard behavior without changing live
  runtime defaults.

## Public cleanup decision

The repository keeps source code, tests, generic `aiops-docs`, MCP examples,
and sanitized fixtures. It excludes `.env`, local Agent state, uploaded or
internal documents, database/vector volumes, logs, browser traces, and
historical evaluation output. Any credential that appeared in an older local
revision must still be revoked or rotated separately.

## Extension rule

New integrations should be added behind an adapter, preserve `RequestContext`,
`source_ref`, and audit metadata, and ship with a focused test. Runtime default
changes require a corresponding evaluation or rollback record.
