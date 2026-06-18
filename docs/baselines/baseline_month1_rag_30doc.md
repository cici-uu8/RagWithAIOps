# Baseline: Month1 RAG 30-Doc Pre-Expansion

Baseline ID: `BASE-M1-RAG-30DOC-20260618`

Date: 2026-06-18

Phase: Month1 Week3 pre-expansion baseline

Module: RAG corpus / retrieval

## Scope

Record the current 30-doc RAG baseline before Month1 Week3 starts any 30 -> 50 doc corpus expansion work.

This file is the pre-expansion corpus baseline. It is separate from the Day0 top_k/rerank gate baseline.

## Corpus Snapshot

| Item | Value | Evidence |
|---|---|---|
| Indexed corpus size | 30 docs | `docs/RAG_Corpus_清单6_Final_Closeout.md`, `PROJECT_STATE.md` |
| Markdown docs | 18 | same evidence |
| PDF docs | 12 | same evidence |
| Deferred parsing record | 1 AWS long-PDF record outside indexed readiness | same evidence |
| Active knowledge base | `process_digital_dept` | `docs/RAG_Corpus_清单6_C6-P3_Mixed_54q_retrieval_baseline.md` |

## Locked Runtime Defaults

| Setting | Value |
|---|---|
| `rag_default_retrieval_mode` | `dense_only` |
| `rag_query_rewrite_mode` | `off` |
| `rerank_enabled` | `false` |
| `rag_top_k` | `3` |

## Retrieval Baseline

| Item | Value |
|---|---|
| Formal retrieval evalset | `evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl` |
| Formal dense-only report | `evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_54q_after_c6_p2_dense_20260612.json` |
| Formal dense-only result | `45 / 54` passed (`83.33%`) |
| `wrong_scope_count` | `0` |
| `citation_unresolvable_count` | `0` |
| `all_source_ref_resolvable` | `true` |

## Known Retrieval Shape

- Mixed 54q residual failures remain `9`, concentrated in Markdown target-section coverage, PDF chunk/page/table ranking, and one expression/lexical gap cluster.
- Existing evidence does not justify default promotion to hybrid, rerank, or query rewrite.
- Month1 Week3 Day0 shadow gate must be completed before any corpus expansion-driven default discussion.

## Decision

Decision: `baseline-accepted`

Reason:

- The 30-doc corpus is stable enough to serve as the pre-expansion reference state.
- Retrieval safety boundaries are clean.
- Quality gaps are known and already triaged, so Week3 corpus work can start from an explicit baseline instead of an implied one.
