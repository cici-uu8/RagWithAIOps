# Scorecard: Week0 RAG Evaluation Matrix

Scorecard ID: `SCORE-W0-RAG-EVAL-MATRIX-20260618`

Date: 2026-06-18

Phase: Week0

Module: RAG / frontend / operations evaluation planning

## Purpose

Make the evaluation system explicit for every production-grade module so future failures are not blamed on a single layer such as embedding by default.

## Module Matrix

| Module | Baseline Required | Candidate Plans | Compare Metrics | Gate Outcome |
|---|---|---|---|---|
| Embedding | Current `text-embedding-v4`, corpus coverage, query/document domain distribution | current model, dimension changes, domain-specific evalset, future fine-tune only if evidence justifies | recall contribution, failure-cluster coverage, latency, cost, corpus-domain misses | promote / keep-shadow / reject |
| Retrieval | current `dense_only` Mixed/RAG baseline | dense, sparse, hybrid, residual chunk probe | expected_doc_found, wrong_scope, source_ref_complete, mrr, latency | promote / keep-shadow / reject |
| Rerank | local lexical baseline | Bailian `qwen3-rerank`, fallback, later provider candidates | rank lift, source_ref stability, latency, timeout/fallback rate | promote / keep-shadow / reject |
| Query rewrite | `off` baseline | rule-based rewrite, LLM intent/rewrite shadow | intent accuracy, retrieval lift, wrong-scope risk, hallucination/refusal changes | promote / keep-shadow / reject |
| Answer | deterministic hard gate baseline | prompt variants, optional LLM judge shadow | answer safety, source support, incomplete answer rate, citation stability | promote / keep-shadow / reject |
| Frontend | current static app/admin-console smoke | error classification, loading states, trace visibility, layout refactor | workflow success, browser smoke, visual regression notes, JS syntax/tests | promote / keep-shadow / reject |
| Operations | current service health and MCP lifecycle | long-run check, log rotation, memory/connection pool monitoring, backup/restore | health uptime, memory growth, log growth, recovery time, alert signal | promote / keep-shadow / reject |
| Governance | current registry/timeline/checklists | GitHub Projects sync, weekly review automation | source-of-truth consistency, stale-plan contamination, evidence freshness | promote / keep-shadow / reject |

## Week0 Gate Status

| Requirement | Status | Evidence |
|---|---|---|
| Evaluation directories exist | pass | `docs/scorecards/`, `docs/baselines/`, `docs/compare-reports/` |
| Templates exist | pass | `scorecard_template.md`, `baseline_template.md`, `compare_template.md` |
| Public corpus manifest exists | pass | `docs/public_corpus_manifest_week0_20260618.md` |
| Embedding/rerank smoke recorded | pass | `docs/compare-reports/compare_week0_embedding_rerank_smoke_20260618.md` |
| Runtime defaults unchanged | pass | `tests/test_checklist2_production_defaults.py` |
| Representative Month1 RAG compare | pending | Month1 task, not Week0 |

## Decision

Decision: `Week0 evaluation foundation pass; production default changes still blocked`

Reason:

- The evaluation framework now covers embedding, retrieval, rerank, query rewrite, answer, frontend, operations, and governance.
- Week0 evidence proves readiness to start evidence-first Month1 work, not readiness to promote any new RAG default.
