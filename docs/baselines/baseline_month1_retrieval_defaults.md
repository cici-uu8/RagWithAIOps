# Baseline: Month1 Retrieval Defaults

Baseline ID: `BASE-M1-RETRIEVAL-DEFAULTS-20260618`

Date: 2026-06-18

Phase: Month1 Week1 Day1

Module: retrieval / rerank / runtime defaults

## Scope

Record the Month1 starting baseline for retrieval before any candidate strategy is promoted.

This baseline is intentionally conservative: it preserves the existing production and beta defaults while allowing shadow comparison of sparse, hybrid, and hybrid_rerank candidates.

## Runtime Defaults

| Setting | Baseline Value | Evidence |
|---|---|---|
| `rag_default_retrieval_mode` | `dense_only` | `app/config.py`, `tests/test_checklist2_production_defaults.py` |
| `rag_query_rewrite_mode` | `off` | `app/config.py`, `tests/test_checklist2_production_defaults.py` |
| `rerank_enabled` | `false` | `app/config.py`, `tests/test_checklist2_production_defaults.py` |
| `rag_top_k` | `3` | `app/config.py`, `docs/baselines/baseline_week0_current_state_20260618.md` |
| Local rerank model | `local_lexical_v1` | `app/config.py`, `app/services/rerank_service.py` |
| External rerank candidate | Bailian `qwen3-rerank` | `docs/compare-reports/compare_week0_embedding_rerank_smoke_20260618.md` |

## Representative Evalset

| Item | Value |
|---|---|
| Evalset | `evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl` |
| Sample count | 54 |
| Knowledge base | `process_digital_dept` |
| Top K | 3 |
| Compared modes | `dense_only`, `sparse_only`, `hybrid`, `hybrid_rerank` |
| Raw report JSON | `evals/knowledge_base/reports/month1_retrieval_4mode_54q_20260618.json` |
| Raw report Markdown | `evals/knowledge_base/reports/month1_retrieval_4mode_54q_20260618.md` |

## Baseline Metrics

| Metric | Dense Baseline | Gate Meaning |
|---|---:|---|
| `expected_doc_found` | 51 / 54 (94.4%) | Current quality baseline |
| `wrong_scope` | 0 | Hard safety gate |
| `source_ref_complete` failures | 0 | Hard citation/source gate |
| `not_ready` | 0 | Infrastructure readiness gate |
| Average latency | 510 ms | Performance baseline |
| P95 latency | 1430 ms | Performance regression comparator |
| Max latency | 3424 ms | Outlier watch |

## Known Baseline Limits

- Dense-only still misses 3/54 representative retrieval cases.
- Prior residual triage already identified Markdown target-section coverage, PDF/table ranking, and expression/lexical gaps as the main failure clusters.
- Hybrid and rerank candidates must prove stable lift without permission, scope, source_ref, latency, or cost regression before any default change.

## Gate

Decision: `baseline-accepted`

Reason:

- The baseline is representative enough for Month1 Day1 candidate comparison.
- It does not change runtime defaults.
- Candidate promotion remains blocked until compare and scorecard evidence justify it.
