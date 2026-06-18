# Compare: Week0 Embedding And Rerank Smoke

Compare ID: `COMPARE-W0-EMBED-RERANK-20260618`

Date: 2026-06-18

Phase: Week0

Module: embedding / rerank / fallback

## Question

Can the local environment run the required `text-embedding-v4` and Bailian `qwen3-rerank` validation paths, and should either result change runtime defaults?

## Baseline

Current default runtime posture remains:

```text
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
rag_top_k = 3
rerank_model = local_lexical_v1
```

## Smoke Evidence

| Check | Result | Evidence |
|---|---|---|
| `.env` DashScope key loads through app config | pass | `text-embedding-v4` smoke initialized DashScope client with masked key |
| Embedding model | pass | `text-embedding-v4` returned 2 vectors |
| Embedding dimension | pass | 1024 |
| Embedding latency | observed | 868 ms for 2 short texts |
| Local lexical rerank | pass | ranked the strongest `HighCPUUsage system-metrics` candidate first |
| Bailian rerank model | pass | `qwen3-rerank` through `https://dashscope.aliyuncs.com/compatible-api/v1/reranks` |
| Bailian rerank count | pass | returned scores for 3 candidates |
| Bailian rerank latency | observed | 620 ms |
| Fallback boundary | pass | `RerankService` keeps local lexical as baseline/fallback |

## Rerank Mini Comparison

Query:

```text
HighCPUUsage system-metrics
```

Candidates:

| Candidate | Content Summary |
|---|---|
| `doc_cpu:c00002` | Generic CPU traffic spike note |
| `doc_cpu:c00001` | HighCPUUsage + system-metrics troubleshooting note |
| `doc_cpu:c00003` | Disk capacity unrelated note |

Results:

| Method | Scores | Ranked Order | Observation |
|---|---|---|---|
| local lexical | `[0.0, 1.0731707317073171, 0.0]` | `doc_cpu:c00001`, then tied zero-score candidates | Correctly lifts exact lexical match; tied unrelated/generic zero scores need stable tie handling in larger evals |
| Bailian `qwen3-rerank` | `[0.5717248480884565, 0.6957611181376028, 0.2277508989349749]` | `doc_cpu:c00001`, `doc_cpu:c00002`, `doc_cpu:c00003` | Correctly lifts best match and separates generic CPU from unrelated disk candidate |

## Gate Decision

Decision: `keep-shadow`

Reason:

- The environment can call both embedding and Bailian rerank.
- The mini smoke is too small to justify changing production defaults.
- Month1/Month2 must run representative retrieval/rerank compare gates before any promote decision.

## Follow-Up

- Month1: build retrieval candidate baseline and compare dense/sparse/hybrid/hybrid_rerank without changing defaults.
- Month2: if residual rank-gap samples remain, run local lexical vs Bailian rerank on a representative evalset.
- Any API failure should fall back to local lexical and be recorded as compare evidence, not hidden.
