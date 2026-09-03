# Knowledge-base evaluation tools

The repository ships evaluation runners and deterministic fixtures, but does
not ship real enterprise evaluation corpora or execution traces. Provide an
evaluation set from a local, approved data source when running the runners.

For retrieval evaluation, each JSONL row must contain:

```json
{
  "sample_id": "example-001",
  "query": "How do I investigate a service timeout?",
  "allowed_kb_ids": ["ops_kb"],
  "expected_doc_ids": ["doc-example"],
  "expected_answer_keywords": ["timeout"],
  "scope": "scoped"
}
```

Run an approved local set explicitly:

```bash
uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset /path/to/approved-evalset.jsonl
```

Generated reports, evalsets, and child-run traces are local-only and are
ignored by `.gitignore`.
