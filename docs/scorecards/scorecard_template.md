# Scorecard Template

Scorecard ID: `__________`

Date: `YYYY-MM-DD`

Owner: `__________`

Phase: `Week0 / Month1 / Month2 / Month3`

Module: `governance / embedding / retrieval / rerank / query_rewrite / answer / frontend / aiops / database / ops`

## Scope

What is being judged:

- `__________`

Out of scope:

- `__________`

## Evaluation Contract

All modules use the same governance skeleton: baseline -> candidate/shadow -> compare -> gate decision. Metrics are module-specific; do not reuse RAG metrics for frontend/AIOps/ops unless they actually apply.

## Criteria

| Dimension | Metric / Check | Target | Evidence | Result |
|---|---|---:|---|---|
| Functionality | Required behavior works | pass | `path_or_command` | pending |
| Quality | Module-specific scorecard metric passes | pass | `path_or_command` | pending |
| Performance | P95 / runtime / cost within budget | baseline-bound | `path_or_command` | pending |
| Safety | permission/scope/source_ref/rollback hard gates | pass | `path_or_command` | pending |
| Maintainability | docs/state/tests updated | pass | `path_or_command` | pending |

## Candidate Options

| Candidate | Description | Expected Benefit | Risk | Status |
|---|---|---|---|---|
| baseline | Current behavior | stable reference | may be insufficient | measured |
| candidate_a | `__________` | `__________` | `__________` | pending |
| candidate_b | `__________` | `__________` | `__________` | pending |

## Gate Decision

Decision: `pending / pass / fail / shadow-only / external-blocked`

Reason:

- `__________`

Required follow-up:

- `__________`
