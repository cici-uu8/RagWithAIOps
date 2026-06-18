# Compare: Week0 Plan Alignment

Compare ID: `COMPARE-W0-PLAN-ALIGNMENT-20260618`

Date: 2026-06-18

Phase: Week0

Module: plan governance

## Question

Should the repo auto-bootstrap all detected plan-like documents, or manually register only the current production-grade mainline?

## Inputs

| Item | Auto-bootstrap all candidates | Manual active-mainline registry |
|---|---|---|
| Source | `docs/plan_adoption_report.md` found 169 possible plan-related files | User-stated mainline plus active root docs |
| Risk | Old RAG/database/memory/enterprise plans become ambiguous current plans | Requires manual maintenance |
| Current-user requirement | Violates "do not mix old plans" | Matches fixed Week0 -> Month1 -> Month2 -> Month3 order |

## Results

| Metric | Auto-bootstrap | Manual Registry | Decision |
|---|---:|---:|---|
| Current mainline clarity | low | high | manual wins |
| Risk of old-plan contamination | high | low | manual wins |
| Automation convenience | high | medium | auto wins |
| Fit for overnight autonomous development | risky | safer | manual wins |

## Decision

Decision: `reject auto-bootstrap; promote manual registry`

Reason:

- The brownfield repo contains many historical execution plans and closeout docs.
- The user explicitly requires no old-plan mixing.
- Manual registry keeps the current production-grade line auditable and narrow.

Next action:

- Maintain `docs/plan_registry.md` and `docs/plan_timeline_report.md` after every plan lifecycle change.
