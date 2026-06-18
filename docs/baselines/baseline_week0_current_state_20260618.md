# Baseline: Week0 Current State

Baseline ID: `BASE-W0-CURRENT-20260618`

Date: 2026-06-18

Phase: Week0

Module: project governance / RAG defaults / local service health

## Environment

| Item | Value |
|---|---|
| Branch | `enterprise3` |
| Runtime services | FastAPI `http://127.0.0.1:9900`, CLS MCP `8003`, Monitor MCP `8004` |
| Active plan order | Week0 -> Month1 -> Month2 -> Month3 |
| Default retrieval posture | `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3` until compare gates prove otherwise |
| Adoption scan | `docs/plan_adoption_report.md` |

## Baseline Metrics And Evidence

| Metric | Value | Evidence |
|---|---:|---|
| FastAPI health | healthy | `GET /health` returned service healthy and Milvus connected during 2026-06-18 local check |
| MCP port readiness | listening | local ports `8003` and `8004` were listening during 2026-06-18 check |
| Current RAG beta retrieval baseline | 45/54 Mixed 54q | `PROJECT_STATE.md`, `docs/RAG_MVP_Baseline_20260612.md` |
| Current Answer baseline | 18/30 Answer 30q | `PROJECT_STATE.md`, `docs/RAG_Production_Readiness_Checklist.md` |
| Current beta smoke | 7/7 | `PROJECT_STATE.md`, `evals/knowledge_base/reports/` |
| Desktop smoke | 21/21 | `docs/技术冒烟测试报告_20260614.md` |

## Known Risks

- `Month1_执行清单.md` previously suggested enabling hybrid by default; this must be corrected before Month1 execution.
- Rerank currently has local lexical implementation; DashScope/Bailian rerank still needs integration and compare evidence.
- GitHub Projects can be used only if local `gh` auth/project permissions work in the current repo.

## Gate

This baseline is evidence for Week0 planning and does not justify any runtime default change.
