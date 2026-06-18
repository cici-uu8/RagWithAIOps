# Plan Registry

Generated: 2026-06-18

This registry is the canonical source of truth for current production-grade development planning. It is intentionally manual and minimal because `docs/plan_adoption_report.md` found many historical plan-like documents that must not be auto-promoted into the current execution line.

## Current Authoritative Mainline

Execution order is fixed:

`Week0_准备清单.md` -> `Month1_执行清单.md` -> `Month2_执行清单.md` -> `Month3_执行清单.md`

`开发主控文档.md` is the master control document. It explains the mainline, gates, and lifecycle policy, but the execution checklists above own day-to-day work.

## Registry

| Plan ID | Path | Role | Lifecycle | Execution | Authoritative | Workstream | Start | Completion Rule |
|---|---|---|---|---|---|---|---|---|
| PROD-MASTER-20260617 | `开发主控文档.md` | master_plan | active | in_progress | yes | production-grade-mainline | 2026-06-17 | All Week0, Month1, Month2, Month3 gates closed with evidence |
| PROD-W0-20260617 | `Week0_准备清单.md` | execution_plan | active | completed | yes | production-grade-mainline | 2026-06-17 | Week0 final checklist closed or external-blocked with fallback |
| PROD-M1-20260617 | `Month1_执行清单.md` | execution_plan | active | in_progress | yes | production-grade-mainline | after Week0 gate | Milestone 1 scorecard and compare gates pass |
| PROD-M2-20260617 | `Month2_执行清单.md` | execution_plan | active | not_started | yes | production-grade-mainline | after Month1 gate | Milestone 2 scorecard and compare gates pass |
| PROD-M3-20260617 | `Month3_执行清单.md` | execution_plan | active | not_started | yes | production-grade-mainline | after Month2 gate | Final production-ready scorecard passes |
| PLAN-ADOPTION-20260618 | `docs/plan_adoption_report.md` | evidence_doc | active | completed | no | governance | 2026-06-18 | Read-only adoption scan retained as evidence |

## Historical / Non-Current Plan Handling

The adoption report found many plan-like files under `docs/`. They are not current execution plans unless explicitly added to this registry.

Default handling:

- Existing RAG, database, memory, enterprise, and closeout checklists remain historical evidence or reference documents.
- Do not execute an unregistered historical checklist as a current task.
- If a historical document contains useful evidence, cite it in the active checklist or compare report instead of changing the active execution order.
- If a new plan document is created, update this registry and `docs/plan_timeline_report.md` in the same work batch.

## Stage Gate Policy

| Gate | Required Evidence |
|---|---|
| Week0 -> Month1 | Governance files exist; weekly review script runs; baseline/scorecard/compare templates exist; external-blocked items recorded |
| Month1 -> Month2 | Month1 scorecard passes; no default changes without compare; local regression checks pass; unresolved blockers are external-blocked |
| Month2 -> Month3 | RAG expansion/rerank/retrieval/query-rewrite compare gates pass or are explicitly rejected; quality gates pass |
| Month3 -> Production-ready | Final comprehensive scorecard passes; long-run risk assessment completed; deployment/ops docs complete |

## Latest Execution Evidence

| Date | Plan ID | Evidence | Decision |
|---|---|---|---|
| 2026-06-18 | PROD-M1-20260617 | `docs/milestones/week1_evidence.md`; `docs/scorecards/scorecard_month1_week1_acceptance.md`; `docs/compare-reports/compare_month1_week1_acceptance.md`; `output/smoke_test/*_smoke_test.json`; `output/playwright/month1_week1_day5_smoke/browser_smoke_result.json` | Week1 local gate passed; Month1 remains `in_progress`; next task is Week2 Day1 |

## External Blocked Rule

When a task depends on a person, unavailable permission, paid account change, external system, or unavailable source material, mark it `external-blocked` in:

- the relevant execution checklist,
- `docs/external_blocked_registry.md`,
- `PROJECT_STATE.md`,
- and the next weekly review report.

External-blocked tasks must not stop unrelated local tasks.
