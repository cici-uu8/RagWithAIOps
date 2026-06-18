# Code Review Checklist

Generated: 2026-06-18

Use this checklist for every non-trivial code or plan change in the production-grade mainline.

## Scope

- [ ] The change is tied to the current active plan in `docs/plan_registry.md`.
- [ ] The change does not execute or revive an old unregistered plan.
- [ ] Unrelated cleanup is avoided.
- [ ] Any external dependency is marked `external-blocked` instead of left ambiguous.

## Behavior

- [ ] Acceptance criteria are explicit.
- [ ] Existing defaults are preserved unless a compare gate proves the change.
- [ ] User-visible behavior is documented when it changes.
- [ ] Rollback or fallback behavior is defined for risky paths.

## RAG / Retrieval / Rerank / Query Rewrite

- [ ] Baseline before the change is identified.
- [ ] Candidate alternatives are listed.
- [ ] Compare report records metrics, regressions, and gate decision.
- [ ] No default switch is made from isolated or synthetic-only evidence.
- [ ] Permission, scope, and `source_ref` gates remain hard checks.

## Frontend

- [ ] Architecture/module boundary is consistent with existing frontend structure.
- [ ] UI state, error state, loading state, and empty state are handled.
- [ ] Text does not overflow or overlap in target viewports.
- [ ] Browser smoke or targeted JS checks are run when frontend files change.

## Tests and Verification

- [ ] Targeted tests cover the changed behavior.
- [ ] Static checks or syntax checks are run.
- [ ] Regression scope is stated.
- [ ] Important skipped checks are explicitly recorded with reason.

## Documentation and State

- [ ] Active checklist is updated.
- [ ] `PROJECT_STATE.md` is updated.
- [ ] `DEVELOPMENT_LOG.md` or the relevant development record is updated.
- [ ] Scorecard/baseline/compare evidence is updated when applicable.
