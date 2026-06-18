# Baseline: Month1 Week1 Acceptance

Baseline ID: `baseline_month1_week1_acceptance_20260618`

Date: `2026-06-18`

Phase: `Month1 / Week1`

Module: `frontend / retrieval / governance`

## Environment

| Item | Value |
|---|---|
| Branch | `enterprise3` |
| Commit | `c6d4211` plus current working-tree Month1 Week1 changes |
| Runtime | FastAPI `http://127.0.0.1:9900`, CLS MCP `8003`, Monitor MCP `8004`, Milvus connected |
| Data source / evalset | Existing local test suite, desktop smoke users, Month1 retrieval 54q evalset |
| Config defaults | `dense_only / query_rewrite=off / rerank_enabled=false / top_k=3` |

## Baseline Metrics

| Metric | Value | Evidence |
|---|---:|---|
| retrieval candidate gate | pass, keep dense-only default | `docs/compare-reports/compare_month1_retrieval_candidates.md` |
| frontend error handling | pass after Day5 browser regression fix | `output/playwright/month1_week1_day5_smoke/browser_smoke_result.json` |
| frontend loading state | pass | `docs/scorecards/scorecard_month1_frontend_loading_state.md` |
| frontend trace headers | pass | `docs/scorecards/scorecard_month1_frontend_trace_id.md` |
| full pytest regression | pass | `uv run pytest -q --no-cov` |
| frontend contract regression | `32/32` pass | `uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov` |
| desktop technical smoke | `21/21` pass | `output/smoke_test/*_smoke_test.json` |
| browser smoke | all checks pass | `output/playwright/month1_week1_day5_smoke/browser_smoke_result.json` |

## Known Risks

- Remote GitHub Actions validation remains `external-blocked` as `EXT-M1-CI-REMOTE`; local CI workflow exists and local regression checks passed.
- Current `make start-api` / `make restart` still uses plain `nohup` for FastAPI. In this command runner it can briefly start and then exit; current runtime was kept healthy with an independent session. This is a local launcher robustness risk, not a Week1 product behavior failure.
- Browser smoke intentionally mocks `/api/chat` success and 500 responses to validate frontend loading/error/trace behavior deterministically. End-to-end live chat is covered by `smoke_test_desktop_beta.py`, but LLM answer quality is not part of Week1 frontend Phase 0 gate.

## Repro Command

```bash
curl --noproxy '*' -fsS http://127.0.0.1:9900/health
uv run pytest -q --no-cov
node --check static/app.js
node --check static/js/error-handler.js
node --check static/js/loading-states.js
node --check static/js/trace-utils.js
uv run pytest tests/test_assistant_frontend_optimization.py -q --no-cov
uv run python smoke_test_desktop_beta.py
# Browser evidence: output/playwright/month1_week1_day5_smoke/browser_smoke_cli_output.md
```

## Notes

- Week1 acceptance proves the local P0 frontend experience and regression gates are coherent enough to continue Month1 Week2.
- This baseline does not promote hybrid retrieval, rerank, query rewrite, or any RAG default change.
