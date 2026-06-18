# Scorecard: Month1 Retrieval Strategy

Scorecard ID: `SCORE-M1-RETRIEVAL-STRATEGY-20260618`

Date: 2026-06-18

Phase: Month1 Week1 Day1

Module: retrieval / rerank

## Scope

Judge whether Month1 has enough evidence to promote a retrieval candidate over the current dense-only default.

Out of scope:

- Enabling hybrid, query rewrite, or rerank by default.
- Treating synthetic exact-code probes as production-default evidence.
- Answer-layer prompt or top_k changes.

## Criteria

| Dimension | Metric / Check | Target | Evidence | Result |
|---|---|---:|---|---|
| Functionality | Four candidate modes evaluated on representative 54q evalset | pass | `evals/knowledge_base/reports/month1_retrieval_4mode_54q_20260618.json` | pass |
| Quality | Candidate improves `expected_doc_found` stably over dense baseline | meaningful lift | `docs/compare-reports/compare_month1_retrieval_candidates.md` | partial |
| Safety | `wrong_scope`, `not_ready`, `source_ref_complete` regressions absent | pass | raw compare summary | pass |
| Performance | Candidate latency does not exceed baseline materially | baseline-bound | raw compare summary | fail for hybrid / hybrid_rerank |
| Rerank | Rerank candidate improves representative retrieval | pass | `hybrid_rerank` 36/54 vs dense 51/54 | fail |
| Governance | Runtime defaults unchanged without gate | pass | `app/config.py`, `tests/test_checklist2_production_defaults.py` | pass |

## Candidate Options

| Candidate | Expected Doc Found | P95 Latency | Safety Regressions | Status |
|---|---:|---:|---:|---|
| `dense_only` | 51/54 (94.4%) | 1430 ms | 0 | baseline |
| `sparse_only` | 35/54 (64.8%) | 122 ms | 0 | reject as broad default |
| `hybrid` | 52/54 (96.3%) | 3580 ms | 0 | keep-shadow |
| `hybrid_rerank` | 36/54 (66.7%) | 3067 ms | 0 | reject as default; keep as targeted experiment only |

## Gate Decision

Decision: `keep-shadow`

Reason:

- `hybrid` improves expected-doc coverage by only +1/54 over `dense_only`, while P95 latency rises from 1430 ms to 3580 ms and max latency reaches 27349 ms.
- `hybrid_rerank` applied rerank to 161 candidates but drops representative expected-doc coverage to 36/54, so it cannot be promoted.
- `sparse_only` is fast but loses too much representative coverage for broad default use.
- No candidate introduced wrong-scope or source_ref hard-gate failures, so further shadow work is allowed.

Required follow-up:

- Keep runtime defaults at `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3`.
- Continue Month1 local tasks after recording this compare.
- If retrieval optimization continues later, focus on residual chunk/PDF/table/expression-gap probes rather than enabling global hybrid or rerank.
