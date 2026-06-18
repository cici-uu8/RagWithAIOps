# Scorecard: Month1 Week2 Acceptance

Scorecard ID: `scorecard_month1_week2_acceptance_20260618`

Date: `2026-06-18`

Owner: `Codex local execution`

Phase: `Month1 / Week2`

Module: `frontend / aiops / permissions`

## Scope

What is being judged:

- Week2 core capability visualization completion: AIOps diagnosis flow visualization and permission-state three-color visualization in the existing static frontend.

Out of scope:

- Month1 Week3 RAG quality expansion and top_k/rerank shadow compare.
- Live AIOps model/MCP diagnosis quality.
- Backend permission model, grant semantics, review queue, or ToolGateway behavior changes.
- Remote GitHub Actions execution, which is tracked separately as `external-blocked`.

## Criteria

| Dimension | Metric / Check | Target | Evidence | Result |
|---|---|---:|---|---|
| Functionality | AIOps visualizer class/style/script present | pass | frontend contract | pass |
| Functionality | AIOps SSE events render plan/steps/tool/report | pass | browser smoke JSON | pass |
| Functionality | terminal AIOps state prevents late status reopen | pass | running steps = `0` | pass |
| Functionality | PermissionViewer class/style/script present | pass | frontend contract | pass |
| Functionality | granted/requestable/forbidden cards render | pass | `3 / 2 / 2` | pass |
| Functionality | request buttons prefill existing forms | pass | browser DOM smoke | pass |
| Quality | Full local pytest | pass | `uv run pytest -q --no-cov` | pass |
| Quality | Static frontend contract tests | `33/33` | `uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov` | pass |
| Quality | JS syntax checks | pass | targeted `node --check` commands | pass |
| Quality | `git diff --check` | pass | command exit 0 | pass |
| Safety | RAG defaults unchanged | pass | no config/default changes in Week2 | pass |
| Safety | no backend permission authority change | pass | frontend-only permission viewer | pass |
| Maintainability | baseline/scorecard/compare/evidence docs updated | pass | `docs/baselines/`, `docs/scorecards/`, `docs/compare-reports/`, `docs/milestones/` | pass |

## Candidate Options

| Candidate | Description | Expected Benefit | Risk | Status |
|---|---|---|---|---|
| baseline | Week1 UX fixes only | stable existing frontend | core capabilities remain hard to inspect | measured |
| candidate_a | AIOps visualizer + PermissionViewer | better operational and permission transparency | frontend-only smoke can overclaim if framed as backend/live quality | accepted with explicit boundaries |

## Gate Decision

Decision: `pass`

Reason:

- AIOps visualizer and PermissionViewer both have static contract and browser DOM evidence.
- Full local pytest, frontend contract tests, JS syntax checks, and diff checks passed.
- Week2 did not change RAG defaults, AIOps backend protocol, or backend permission authority.

Required follow-up:

- Continue only after Week2 is marked complete in the active plan.
- Next Month1 task is Week3 Day0 top_k/rerank shadow compare gate, with defaults still locked.
