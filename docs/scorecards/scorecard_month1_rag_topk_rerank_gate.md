# Scorecard: Month1 RAG Top-K / Rerank Gate

Scorecard ID: `SCORE-M1-RAG-TOPK-RERANK-GATE-20260618`

Date: 2026-06-18

Phase: Month1 Week3 Day0

Module: RAG retrieval / rerank / final context

## Scope

Judge whether Month1 Week3 Day0 produced enough evidence to promote any top_k or rerank candidate before corpus expansion.

Out of scope:

- Changing runtime defaults immediately.
- Treating deterministic answer proxy as a full Answer gate replacement.
- Using this gate as evidence for query rewrite, hybrid retrieval, or prompt changes.

## Criteria

| Dimension | Metric / Check | Target | Evidence | Result |
|---|---|---:|---|---|
| Functionality | Baseline + multiple candidate groups executed on 54q evalset | pass | `month1_topk_rerank_shadow_matrix_54q_20260618.json` | pass |
| Retrieval | Candidate improves expected-doc hit or recall ceiling over baseline | meaningful lift | raw report + compare | partial |
| Rerank quality | Rerank improves ranking quality (`MRR`, `nDCG`, rank lift) without hurting final hit | pass | raw report + compare | fail |
| Answer proxy | Candidate avoids regression in deterministic answer proxy | no regression | raw report + compare | partial for no-rerank, fail for rerank |
| Safety | `wrong_scope` and `source_ref` regressions absent | pass | raw report | pass |
| Engineering | Latency, token cost, API calls, timeout stay proportionate to quality gain | baseline-bound | raw report + compare | partial |
| Governance | Defaults remain locked unless promote evidence is complete | pass | checklist + raw report | pass |

## Candidate Status

| Candidate | Retrieval Outcome | Rerank Outcome | Answer Proxy Outcome | Engineering Outcome | Status |
|---|---|---|---|---|---|
| `dense_k5_ctx3_no_rerank` | small lift | n/a | neutral to slight lift | acceptable | keep-shadow |
| `dense_k20_ctx5_no_rerank` | small lift | n/a | best shadow lift | context cost rises | keep-shadow |
| `dense_k10_lexical_rn5_ctx3` | candidate pool good | rank quality regresses | major regression | cheap but not useful | reject |
| `dense_k20_bailian_rn5_ctx3` | candidate pool good | no net lift | regression | extra latency + API cost | reject |
| `dense_k50_lexical_rn8_ctx5` | very large pool | strong regression | major regression | heavy context pollution | reject |

## Gate Decision

Decision: `keep-shadow`

Reason:

- The gate itself is complete and usable.
- No scenario met the promotion bar.
- The best Month1 Day0 result is not a rerank strategy but a larger dense candidate pool without rerank.
- Rerank currently looks riskier than helpful on the 30-doc / 54q baseline: both lexical and Bailian variants hurt ranking or answer proxy enough to fail promotion.

## Required Follow-up

- Keep runtime defaults at `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3`.
- Use `baseline_month1_rag_30doc.md` and this gate as the pre-expansion reference for Week3 corpus work.
- Revisit top_k and rerank only after more corpus coverage and a later compare gate confirm that gains survive beyond deterministic proxy evaluation.
