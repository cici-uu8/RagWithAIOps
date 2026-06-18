# Compare: Month1 Retrieval Candidates

Compare ID: `COMPARE-M1-RETRIEVAL-CANDIDATES-20260618`

Date: 2026-06-18

Phase: Month1 Week1 Day1

Module: retrieval / rerank

## Question

Should Month1 promote sparse, hybrid, or hybrid_rerank retrieval over the current dense-only default?

## Inputs

| Item | Baseline | Candidate |
|---|---|---|
| Runtime config | `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3` | Shadow modes only; no default config change |
| Evalset | `evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl` | Same 54q representative evalset |
| Raw output | `evals/knowledge_base/reports/month1_retrieval_4mode_54q_20260618.json` | `evals/knowledge_base/reports/month1_retrieval_4mode_54q_20260618.md` |
| Modes | `dense_only` | `sparse_only`, `hybrid`, `hybrid_rerank` |

## Results

| Metric | `dense_only` | `sparse_only` | `hybrid` | `hybrid_rerank` | Gate |
|---|---:|---:|---:|---:|---|
| Samples | 54 | 54 | 54 | 54 | pass |
| `expected_doc_found` | 51 (94.4%) | 35 (64.8%) | 52 (96.3%) | 36 (66.7%) | only hybrid has small lift |
| Result count | 150 | 162 | 155 | 161 | observe |
| `wrong_scope` | 0 | 0 | 0 | 0 | pass |
| `not_ready` | 0 | 0 | 0 | 0 | pass |
| Source/citation incomplete | 0 | 0 | 0 | 0 | pass |
| Average latency | 510 ms | 86 ms | 1177 ms | 927 ms | hybrid/rerank slower |
| P95 latency | 1430 ms | 122 ms | 3580 ms | 3067 ms | hybrid/rerank fail performance gate |
| Max latency | 3424 ms | 182 ms | 27349 ms | 14779 ms | hybrid/rerank outlier risk |
| Rerank status | n/a | n/a | n/a | `applied=161` | applied but quality drops |

## Failure / Regression Analysis

| Case / Cluster | Baseline Result | Candidate Result | Category | Decision |
|---|---|---|---|---|
| `S4M-E-010` expression/lexical gap | dense misses | sparse/hybrid/hybrid_rerank find expected doc | real candidate lift | keep for targeted probes |
| Markdown/PDF representative cases where sparse loses dense hit | dense finds expected doc | sparse misses many cases | semantic coverage regression | reject sparse default |
| Rerank representative ranking | dense finds 51/54 | hybrid_rerank finds 36/54 | rerank regression | reject rerank default |
| Hybrid latency outlier | dense max 3424 ms | hybrid max 27349 ms | performance regression | keep-shadow only |
| Safety hard gates | all modes 0 wrong_scope/source_ref failures | no observed regression | safety pass | eligible for more shadow testing |

## Decision

Decision: `keep-shadow`

Reason:

- `hybrid` is the only candidate with a representative quality lift, but the lift is small (+1/54) and latency regression is too large for a default change.
- `hybrid_rerank` proves the rerank path can execute on the representative evalset, but it degrades expected-doc coverage from 51/54 to 36/54.
- `sparse_only` remains useful for expression/exact-code diagnostics, not as broad retrieval default.
- No candidate triggered wrong-scope, not-ready, or source_ref hard-gate failures.

Next action:

- Keep defaults unchanged.
- Mark Month1 Week1 Day1 retrieval compare as complete.
- Continue to Month1 Day1 afternoon local coverage/CI work.
- Revisit hybrid/rerank only with narrower residual-failure probes or a corrected rerank strategy.
