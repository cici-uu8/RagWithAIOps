# Compare: Month1 RAG Top-K / Rerank Matrix

Compare ID: `COMPARE-M1-RAG-TOPK-RERANK-MATRIX-20260618`

Date: 2026-06-18

Phase: Month1 Week3 Day0

Module: RAG retrieval / rerank / final context

## Question

Before Month1 Week3 corpus expansion, is there enough evidence to promote a non-default `retrieval_top_k`, `rerank_top_n`, or rerank strategy over the current `dense_only / off / false / top_k=3` runtime posture?

## Inputs

| Item | Baseline | Candidates |
|---|---|---|
| Runtime config | `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3` | Shadow only; no runtime change |
| Evalset | `evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl` | Same 54q representative evalset |
| Raw output | `evals/knowledge_base/reports/month1_topk_rerank_shadow_matrix_54q_20260618.json` | `evals/knowledge_base/reports/month1_topk_rerank_shadow_matrix_54q_20260618.md` |
| Answer shadow reference | `department_rag_answer_3q_top_k5_shadow_20260612.json` | same reference for gate notes |

## Scenario Results

| Scenario | retrieval_top_k | rerank | rerank_top_n | final_context_k | pass_rate | final_expected_doc_hit | answer_score_avg | context_pollution | latency_p95_ms | Gate |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| `dense_k3_ctx3_default` | 3 | off | - | 3 | 83.33% | 94.44% | 0.8287 | 0 | 488 | baseline |
| `dense_k5_ctx3_no_rerank` | 5 | off | - | 3 | 83.33% | 96.30% | 0.8472 | 0 | 403 | keep-shadow |
| `dense_k20_ctx5_no_rerank` | 20 | off | - | 5 | 87.04% | 96.30% | 0.9074 | 0 | 379 | keep-shadow |
| `dense_k10_lexical_rn5_ctx3` | 10 | local lexical | 5 | 3 | 51.85% | 90.74% | 0.5895 | 3 | 381 | reject |
| `dense_k20_bailian_rn5_ctx3` | 20 | Bailian | 5 | 3 | 68.52% | 96.30% | 0.7948 | 0 | 893 | reject |
| `dense_k50_lexical_rn8_ctx5` | 50 | local lexical | 8 | 5 | 51.85% | 83.33% | 0.5787 | 7 | 452 | reject |

## Key Deltas vs Baseline

| Scenario | Retrieval lift | Rerank effect | Answer proxy effect | Engineering effect | Interpretation |
|---|---|---|---|---|---|
| `dense_k5_ctx3_no_rerank` | `final_expected_doc_hit_rate +1.86%`; pool miss `3 -> 2` | n/a | `answer_score_avg +0.0185`; pass rate unchanged | `p95 -85ms`; context p95 unchanged | Small recall lift, not enough promotion evidence |
| `dense_k20_ctx5_no_rerank` | `final_expected_doc_hit_rate +1.86%`; pool miss `3 -> 2` | n/a | `pass_rate +3.71%`; `answer_score_avg +0.0787` | `p95 -109ms`; context tokens p95 `+603` | Useful shadow candidate, but context-size cost rises materially |
| `dense_k10_lexical_rn5_ctx3` | Pool hit stays `96.30%` | `MRR delta -0.0710`; `nDCG delta -1.1246`; only `1` positive rank lift | `pass_rate -31.48%`; `answer_proxy_regression_count=19` | Cheap locally, but quality collapses | Reject lexical rerank for now |
| `dense_k20_bailian_rn5_ctx3` | Pool/final hit stays `96.30%` | `nDCG delta -1.6575`; `53` applied + `1` external-blocked | `pass_rate -14.81%`; `answer_proxy_regression_count=11` | `p95 +405ms`; `54` rerank API calls | Reject Bailian rerank despite good candidate pool |
| `dense_k50_lexical_rn8_ctx5` | Pool recall rises to `14.7963` avg | `MRR delta -0.2424`; `nDCG delta -3.0997` | `pass_rate -31.48%`; `context_pollution_count=7` | Context tokens p95 `+984`; rerank input tokens p95 `13362` | High-recall pressure mostly creates noise |

## Failure / Gate Analysis

| Check | Result | Meaning |
|---|---|---|
| `wrong_scope_count` | all scenarios `0` | Safety gate remains clean |
| `source_ref_incomplete_count` | all scenarios `0` | Citation/source gate remains clean |
| `retrieval_pool_miss_count` | baseline `3`; other scenarios `2` | Some misses are first-stage ceiling, not rerank mistakes |
| `rerank_ceiling_limited_count` | rerank scenarios `2` | Runner correctly separates "not recalled" from "rerank made it worse" |
| `context_pollution_count` | lexical rerank scenarios `3` and `7` | Noise entered final context and degraded answer proxy |
| prior 3q answer shadow | `1 / 3` passed | Context lift alone is not enough to promote a strategy |

## Decision

Decision: `keep-shadow`

Reason:

- No candidate is promotion-ready.
- `dense_k5_ctx3_no_rerank` and `dense_k20_ctx5_no_rerank` improved retrieval coverage without safety regression, but the evidence is still shadow-only and not enough to change runtime defaults.
- All rerank scenarios failed the gate. The problem is not only latency or cost: answer proxy and ranking quality regressed, and high-recall lexical rerank showed explicit context pollution.
- Bailian rerank is callable, but a callable external rerank path is not the same as a promotable production strategy.

## Next Action

- Keep runtime defaults unchanged.
- Carry the two no-rerank recall-expansion scenarios forward as shadow references for Week3 corpus expansion analysis.
- Do not promote any rerank strategy until a later gate proves net gain on Retrieval, Rerank, Answer, and engineering metrics together.
