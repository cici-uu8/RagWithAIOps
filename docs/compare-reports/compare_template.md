# Compare Report Template

Compare ID: `__________`

Date: `YYYY-MM-DD`

Phase: `Week0 / Month1 / Month2 / Month3`

Module: `embedding / retrieval / rerank / query_rewrite / frontend / ops`

## Question

What decision does this compare report support?

- `__________`

## Inputs

| Item | Baseline | Candidate |
|---|---|---|
| commit/config | `__________` | `__________` |
| evalset/data | `__________` | `__________` |
| command | `__________` | `__________` |

## Evaluation Skeleton

Use a shared governance shape, but choose metrics by module. For RAG strategy comparisons, report Retrieval, Rerank, Answer, and engineering metrics separately.

## Results

| Metric | Baseline | Candidate | Delta | Gate |
|---|---:|---:|---:|---|
| primary quality metric | pending | pending | pending | pending |
| regression metric | pending | pending | pending | pending |
| latency | pending | pending | pending | pending |
| cost / external calls | pending | pending | pending | pending |
| safety hard gate | pending | pending | pending | pending |

## Failure / Regression Analysis

| Case | Baseline Result | Candidate Result | Category | Decision |
|---|---|---|---|---|
| `__________` | `__________` | `__________` | `__________` | `__________` |

## Decision

Decision: `promote / keep-shadow / reject / rollback / external-blocked`

Reason:

- `__________`

Next action:

- `__________`
