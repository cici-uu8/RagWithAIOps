# AIOps 主链路质量审计（2026-05-29）

## 结论先行

我建议把下一步 AIOps 优化切口定为 `executor` 侧的 MCP 工具发现稳定性，优先考虑“工具列表一次获取、同轮复用/缓存”，而不是先改更大的 planner/replanner 逻辑。

原因很简单：
- 201046 这次回退里，所有 degraded samples 都落在 `executor`。
- `planner` / `executor` / `replanner` 都会重复取 MCP tools，`get_tools` 这条路本身就是高频耗时点。
- 这类优化是最小切口，风险比大改 prompt 低很多。

## 代码路径

- `app/services/aiops_service.py`：组 LangGraph，节点是 `planner -> executor -> replanner`。
- `app/agent/aiops/planner.py`：先 `retrieve_knowledge`，再注入可选 memory guidance，然后生成计划。
- `app/agent/aiops/executor.py`：每一步都重新拉本地工具 + MCP 工具，做工具选择，再执行工具，再生成最终步骤结果。
- `app/agent/aiops/replanner.py`：决定 `continue / replan / respond`，并在最后合成最终响应。

## P6 样本 diff

对比 `evals/memory/p6_memory_eval_20260529_005432.json` 和 `evals/memory/p6_memory_eval_20260529_201046.json`，翻转样本是：

| sample | 005432 | 201046 | 变化点 |
|---|---|---|---|
| `p6_repeated_004` | PASS | FAIL | `guidance_check_rate` 从 `1.0` 降到 `0.666...`，且 201046 的退化点在 `executor get_tools timed out after 25.000s` |
| `p6_stale_001` | FAIL | PASS | guidance 明确补到了新根因，属于正向翻转 |
| `p6_stale_003` | PASS | FAIL | judged text 里仍带 stale 关键词，`guidance_not_using_stale` 变成 false；201046 这条 guidance 样本也有 `executor get_tools` timeout |
| `p6_stale_004` | PASS | FAIL | 同样是 stale 关键词污染 judged plan / response 文本，而不是 infra hard failure |

## 我怎么理解这次波动

这不是单一原因，更像两条信号叠在一起：

1. `executor` 不稳
   - 201046 的 degraded samples 全部落在 `executor`
   - 出错点集中在 `executor get_tools` 和一次 `executor llm tool selection`
   - 这会直接把 step coverage 拉低，最典型就是 `repeated_alert` 那条从 7/12 掉到 5/12 里的 1 分

2. guidance 文本仍会污染判断面
   - `stale_override` 的判分会把 `plan` / `step_result` / `report` 都算进 judged text
   - 所以只要 planner guidance 里还在明显写 stale 旧词，哪怕最终 response 方向是对的，也可能被判成 fail

## 建议的下一步

优先做一个小切口：

1. 先把 MCP tools 的发现从“每个节点每一步都重新取”收口成更稳定的复用路径。
2. 再看 `stale_override` 是否还需要单独收紧 planner guidance 的呈现方式。

我不建议现在就做大范围 planner 重写，也不建议把这次波动解释成 memory 线的问题。Memory 已经冻结，这里更像 AIOps 主链路自己的稳定性和提示词边界问题。

## 实施结果（2026-05-30）

最小切口已经落地到 `app/agent/mcp_client.py`：

- `get_mcp_tools_with_retry()` 的默认路径现在会复用 300 秒内的 MCP tools。
- TTL 到期后会自动刷新，不会把过期工具列表长期保留。
- 如果缓存客户端的 `get_tools()` 失败，会回退到 fresh client，并把 fresh 结果重新写回缓存。

目标测试已经通过：

- `tests.test_aiops_mcp_tool_cache`
- `tests.test_p6_memory_eval_infra`
- `tests.test_p5_planner_memory_integration`
- `tests.test_memory_ingestion_aiops_hook`

后续又完成了一轮新的 P6 full eval。报告 `evals/memory/p6_memory_eval_20260530_015555.json` 是 valid / rollout YES / infra_failure_rate=0.0 / hard_failure_count=0 / categories_passed=3/3 / overall=7/12。这个结果说明缓存 slice 不只是单测命中，而是已经验证到完整 P6 主链路。

更细一点看：

- `planner` / `executor` / `replanner` 仍然保持同一条链路，不需要改结构。
- 这轮里 `executor` 和 `replanner` 都能复用缓存的 MCP tools，日志里能直接看到 `Reusing cached MCP tools (count=7)`。
- `p6_plan_004` 这条长尾样本暴露出的是 `replanner` structured output timeout，而不是 `get_tools` 再次成为主要瓶颈。

所以当前更稳妥的结论是：缓存 slice 已完成，而且已经在 full eval 上验证有效。后面如果还要继续 AIOps 优化，下一小切口应从 `replanner` structured output timeout 单独拆出来，而不是回头改 Memory/RAG。
