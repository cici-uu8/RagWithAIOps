# Security And Data Boundary

This repository is a runnable reference implementation. It is not a drop-in production deployment. Review the following controls before exposing it to real enterprise data.

## Never commit

- `.env` files, API keys, JWT secrets, cloud credentials, database passwords, or access tokens.
- Uploaded documents, vector database volumes, SQLite files, logs, screenshots, browser traces, and evaluation run outputs.
- Internal documents or reports containing company names, employee identifiers, customer data, or absolute local paths.

The tracked tree is kept free of these classes of files. If a credential was ever committed in another revision or clone, revoke and rotate it; deleting the current file is not sufficient.

## Runtime controls

- Set a random `JWT_SECRET_KEY` and inject credentials through the deployment secret manager.
- Keep `enterprise_mysql_enabled=false` until database identity, table/column allowlists, read-only policy, confirmation flow, and audit storage are reviewed.
- Keep `RERANK_ENABLED=false`, `RAG_QUERY_REWRITE_MODE=off`, memory injection, and tool-result offload disabled unless their corresponding evaluation gates are reviewed.
- Restrict CORS, bind MCP services to private interfaces, and put authentication and TLS at the deployment edge.
- Use separate Redis, Milvus, and MySQL credentials and namespaces for development, staging, and production.

## Evidence handling

Trace and audit evaluation scripts are offline tools. They may contain sensitive request metadata when pointed at real logs, so write reports to an access-controlled local directory and keep them out of Git. The example MCP services use synthetic data and should not be mistaken for production observability integrations.
