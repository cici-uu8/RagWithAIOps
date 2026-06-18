# External Dependencies

Generated: 2026-06-18

## Policy

The production-grade plan does not wait for unavailable internal contacts. If internal materials cannot be confirmed, use public corpora and record source, license, and scope.

## Dependencies

| Dependency | Purpose | Current Status | Fallback / Decision |
|---|---|---|---|
| Internal runbooks from digitalization/process teams | Enterprise-like RAG corpus | external-blocked: contacts unavailable in Codex runtime | Use public SRE, Redis, MySQL, Kubernetes, Prometheus, and incident-response materials with license notes |
| `DASHSCOPE_API_KEY` from local `.env` | Embedding and DashScope/Bailian rerank validation | available if env loads successfully | If unavailable or API fails, record failure and use local lexical rerank baseline |
| GitHub Projects project scope | External task board | user completed `gh auth refresh -s read:project -s project`; local verification still required before automation | If board automation fails, use repo-local governance files as source of truth |
| Public corpus network access | Corpus fallback | allowed | Save source URLs/license in manifest before importing |

## Corpus Source Rules

- Prefer operational documents with troubleshooting procedures, alerts, symptoms, diagnosis steps, and rollback/remediation actions.
- Record source URL, license, collected date, domain, and intended eval coverage.
- Do not mix synthetic docs into real-corpus baseline without labeling them `synthetic=true`.
- If a source license is unclear, do not import it as a production-grade corpus asset; use it only as inspiration for a separately written synthetic sample.

## API Use Rules

- Rerank calls must be narrow and recorded in compare evidence.
- No default runtime switch is allowed from a successful API call alone.
- API failure must trigger fallback evidence, not silent success.
