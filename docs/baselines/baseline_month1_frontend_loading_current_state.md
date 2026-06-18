# Baseline: Month1 Frontend Loading Current State

Baseline ID: `BASE-M1-FE-LOADING-20260618`

Date: `2026-06-18`

Phase: `Month1`

Module: `frontend`

## Environment

| Item | Value |
|---|---|
| Branch | `enterprise3` |
| Commit | `working tree` |
| Runtime | `FastAPI 127.0.0.1:9900 + local browser smoke` |
| Data source / evalset | `static/index.html + static/app.js + browser smoke` |
| Config defaults | `static HTML/JS only; no build step; no loading-state manager yet` |

## Baseline Metrics

| Metric | Value | Evidence |
|---|---:|---|
| chat loading stages | 1 static spinner message | `this.addLoadingMessage('正在思考...')` |
| upload loading stages | static overlay text only | `showUploadOverlay(true, file.name)` |
| aiops loading stages | static overlay/text only | `showLoadingOverlay(true)` / `showUploadOverlay(...)` |
| progress bar | absent | `static/app.js` pre-Day3 review |
| dedicated loading module | absent | `static/js/loading-states.js` did not exist before Day3 |
| test coverage | frontend contract only, no loading-state contract | `tests/test_assistant_frontend_optimization.py` pre-Day3 scope |
| latency / cost | no backend change | static UI only |

## Known Risks

- 用户只看到“转圈/静态文案”，不知道当前处于检索、分析还是生成阶段。
- 上传和 AIOps 的加载反馈缺少统一阶段语义。
- 没有独立 loading 资源，后续难以做前端契约测试。

## Repro Command

```bash
sed -n '197,236p' Month1_执行清单.md
```

## Notes

- 这是 Month1 Day3 的起始状态基线，不是长期运行基线。
- 该 baseline 只用于比较 Day3 前后 loading UX，不改变任何后端默认值。
