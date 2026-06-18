# Scorecard: Week0 Governance And Evaluation Foundation

Scorecard ID: `SCORE-W0-GOV-20260618`

Date: 2026-06-18

Phase: Week0

Module: governance / evaluation foundation

## Scope

Judge whether Week0 has enough governance and evaluation infrastructure to begin Month1 without mixing old plans or making unproven default changes.

## Criteria

| Dimension | Metric / Check | Target | Evidence | Result |
|---|---|---:|---|---|
| Plan governance | Current mainline registry exists | pass | `docs/plan_registry.md` | pass |
| Timeline clarity | Historical vs active plans separated | pass | `docs/plan_timeline_report.md` | pass |
| Evaluation infrastructure | scorecard/baseline/compare templates exist | pass | `docs/scorecards/`, `docs/baselines/`, `docs/compare-reports/` | pass |
| External dependency handling | external-blocked registry exists | pass | `docs/external_blocked_registry.md` | pass |
| Weekly review | script exists and generates report | pass | `scripts/weekly_review.py`, `docs/weekly_reviews/weekly_review_auto_20260618_101457.md` | pass |
| Safety | Runtime defaults are not changed by Week0 | pass | `app/config.py`, `tests/test_checklist2_production_defaults.py` | pass |
| Public corpus fallback | source/license/synthetic manifest exists | pass | `docs/public_corpus_manifest_week0_20260618.md` | pass |
| API smoke | embedding/rerank smoke recorded | pass | `docs/compare-reports/compare_week0_embedding_rerank_smoke_20260618.md` | pass |

## Gate Decision

Decision: `pass`

Reason:

- Week0 governance, fallback, evaluation templates, API smoke, weekly review, and default-safety checks are present.
- This pass allows Month1 evidence-first work to start.
- It does not authorize changing RAG runtime defaults.
