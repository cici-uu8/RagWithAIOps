# P6_v2 Stale Quality Optimization Plan

日期: 2026-05-28
执行状态: 2026-05-29 第一版已实施并通过 full P6 复测，结果见第 12 节。
范围: P6 full eval 通过后的 stale override 质量优化。P6_v2 只处理 stale-aware retrieval 与 stale override prompt，不处理 infra、judge、MCP fixture 或通用 memory 架构扩张。

## 0. 当前结论

P6 Phase A 已收口，最新 full eval 报告:

```text
evals/memory/p6_memory_eval_20260528_000027.json
```

当前结论:

```text
eval_status=valid
continue_rollout=true
preflight.ok=true
hard_failure_count=0
infra_failure_rate=0.0

repeated_alert: 3/4
plan_reuse: 3/4
stale_override: 0/4
overall: 6/12
categories_passed: 2/3
```

解释:

- P6 eval 本身现在可信。
- rollout gate 已达标。
- `stale_override=0/4` 是真实质量缺口，不是 infra failure，也不是当前 rollout gate blocker。
- P6_v2 是后续质量优化，不回写或推翻 P6 Phase A 的 rollout YES。

## 1. 为什么开 P6_v2

P6 Phase A 修的是评估可信度:

- preflight / infra_summary / traceback 能说明 eval 是否有效。
- recovered node degradation 与 graph-aborted sample failure 已分开。
- judge 已支持中文表达与 planner plan / current_step / step_result。
- 报告保存完整 response 和 key events。

这些修复回答的是:

> 这次评估是不是可信?

P6_v2 要回答的是另一个问题:

> 当历史 memory 可能过时时，retrieval 和 prompt 能不能让 planner 更优先相信当前观测?

当前 `stale_override=0/4` 暴露的不是"memory 没召回"，而是"旧 memory 召回后可能影响当前判断"。所以本轮只处理 stale 质量，不再调整 P6 gate、judge 或 infra policy。

## 2. 范围与不变量

### 2.1 本轮做什么

1. **Stale-aware retrieval**
   - 使用固定规则识别 stale cue，但必须同时有负向过滤，避免把 `fixed parameter`、`固定参数`、`最近有没有类似案例` 误判成 stale。
   - 对命中 stale cue 且明显偏旧的 active memory 做保守降权。
   - `stale_age_days` 与 `stale_penalty` 必须可通过 `MemoryRetrievalService` 构造参数配置，默认值只作为第一版假设，不写死成不可调策略。
   - retrieval trace 必须记录 stale cue、负向过滤、降权配置和被降权 memory，方便后续判断效果差是规则问题还是 prompt/LLM 问题。
   - 保持当前 `LexicalMemoryScorer` 作为 V1 默认 scorer，不引入 embedding / vector / RRF。

2. **Stale override prompt hardening**
   - Memory guidance 明确要求: 当前日志、指标、配置、部署记录、工具观测优先于历史 memory。
   - prompt 不做一刀切免责声明，而是分情况讨论:
     - 当前观测明确反驳 memory 时，必须优先采用当前观测，并说明历史 memory 可能过时。
     - 当前观测不充分时，可以把 memory 作为历史假设，但必须做 fresh checks。
     - 当前观测与 memory 不冲突时，可以复用 memory 中的检查路径或计划模板。
   - 仍然强调 memory 不是 document citation。

### 2.2 本轮不做什么

- 不改 MCP fixture。
- 不补 service-e / service-g / service-h，除非后续证明某个失败样本确实被 fixture 错配阻塞。
- 不改 P6 Phase A judge / infra policy。
- 不引入 hybrid retrieval、vector retrieval、BM25、RRF。
- 不做 LLM stale cue 判断。
- 不做 A/B 测试框架。
- 不做 memory TTL、自动归档或自动 conflict 写回。
- 不新增长期记忆类型或通用 memory OS 分层。
- 不改 `retrieve_knowledge`、RAG `RetrievalResult`、`SourceRef`、`citation_text`。
- 不把 P6_v2 当成生产 rollout 自动开关。

## 3. 现有代码边界

当前相关模块:

```text
app/services/memory_scorer.py
app/services/memory_retrieval_service.py
app/services/memory_guidance_service.py
app/services/memory_guidance_provider.py
app/agent/aiops/planner.py
```

现状:

- `LexicalMemoryScorer.score(record, query)` 返回 `(score, matched_terms)`。
- `MemoryRetrievalService.retrieve(...)` 负责 active candidate 过滤、调用 scorer、排序、构造 result。
- 当前排序为 `(-score, updated_at, memory_id)`。
- `MemoryGuidanceService.format_memory_guidance(...)` 负责生成注入 prompt 的 memory guidance。
- planner 不应重新理解 stale 细节，只消费 provider/service 返回的 guidance text。

P6_v2 改动原则:

- lexical relevance 仍由 scorer 负责。
- stale-aware adjustment 放在 `MemoryRetrievalService` 的 post-score ranking 层，而不是塞进 `LexicalMemoryScorer`，避免未来替换 scorer 时重写 stale 逻辑。
- prompt 规则留在 `MemoryGuidanceService`。
- planner 主流程不新增 stale 分支。

## 4. Stale-aware Retrieval 设计

### 4.1 Stale cue 正向规则

第一版只做固定规则，不上 LLM。正向 cue 需要表达"历史经验可能已经被修复、更新、替换或不再成立"，而不是任何时间词都触发。

英文候选:

```text
fixed last week
fixed yesterday
already fixed
resolved last week
resolved yesterday
config updated
configuration updated
updated last week
changed recently
recent change
no longer the issue
not the same issue
```

中文候选:

```text
上周已修复
昨天已修复
已经修复
已解决
前几天解决了
配置已更新
已经改过配置
最近变更
最近改动
不再是这个问题
已经不是这个问题
当前已经修复
目前已经修复
```

注意:

- 不把单独的 `recently` / `最近` 作为 stale cue；它们太宽，容易误伤"最近有没有类似案例"这类查询。
- 但 `changed recently` / `最近变更` / `最近改动` 这种组合表达仍然是 stale cue，因为它们明确表达了"状态已改变"。
- 不把单独的 `fixed` / `固定` 作为 stale cue；它们可能只是参数名、固定值或一般形容词。
- 但 `fixed last week` / `already fixed` / `上周已修复` 这种组合表达仍然是 stale cue，因为它们明确表达了"问题已解决"。

### 4.2 负向过滤

如果 query 命中以下表达，应取消 stale cue:

```text
fixed parameter
fixed value
fixed interval
fixed threshold
固定参数
固定值
固定阈值
固定间隔
最近有没有类似案例
最近类似案例
最近的历史案例
recent similar incident
recent similar case
recent history
```

原因:

- 这些表达虽然包含 `fixed` / `recent` / `最近`，但用户意图不是"旧 memory 可能过时"。
- 第一版宁可漏掉一部分 stale cue，也不要大面积误伤 repeated_alert / plan_reuse。

### 4.3 可配置参数

默认配置:

```text
stale_age_days = 7
stale_penalty = 0.5
```

但这两个值必须由 `MemoryRetrievalService.__init__` 接收:

```python
def __init__(
    self,
    store: MemoryStore = memory_store,
    scorer: MemoryScorer | None = None,
    stale_age_days: int = 7,
    stale_penalty: float = 0.5,
):
    ...
```

约束:

- `stale_age_days` 必须大于 0。
- `stale_penalty` 应在 `(0, 1]` 范围内。
- 默认值是 P6_v2 第一版假设，不代表长期最优。
- 本轮不做配置文件 / env 接线；先保证测试和后续 eval 可注入不同参数。

### 4.4 降权对象

只对满足以下条件的 active memory 降权:

- query 命中 stale cue；
- query 没有命中负向过滤；
- memory `updated_at` 的年龄超过 `stale_age_days`；
- memory 仍然通过 lexical 命中，否则本来就不会进入结果。

第一版不解析"last week"对应的精确日期。以 record 的 `updated_at` 和当前时间差作为 conservative signal。

### 4.5 排序策略

最小实现:

```python
base_score, matched_terms = scorer.score(record, query.query)

if stale_policy.should_penalize(record, query.query):
    final_score = base_score * stale_penalty
else:
    final_score = base_score
```

原则:

- 降权不是删除。旧 memory 仍可出现在 top_k，只是不应无条件压过同等相关的新 memory。
- 第一版不改全局 tie-breaker，避免扩大回归面。若 P6_v2 后仍失败，再单独讨论 `updated_at` tie-breaker 是否应从旧优先改为新优先。
- 如果降权导致 repeated_alert / plan_reuse 明显回退，按 Stop Rules 停止，不继续调参。

### 4.6 Trace 硬要求

retrieval response 的 `trace` 必须包含 stale policy 信息:

```text
stale_policy.cue_detected
stale_policy.matched_cues
stale_policy.negative_cues
stale_policy.stale_age_days
stale_policy.stale_penalty
stale_policy.penalized_memory_ids
stale_policy.score_adjustments
```

`score_adjustments` 至少包含:

```text
memory_id
base_score
final_score
age_days
reason
```

这不是生产监控系统，但能让 P6 report / 单测 / 手工复盘看清楚:

- 是否检测到了 stale cue；
- 是否被负向过滤取消；
- 哪些 memory 被降权；
- 降权前后分数是多少。

## 5. Stale Override Prompt 设计

### 5.1 guidance 顶部规则

在 `MemoryGuidanceService.format_memory_guidance(...)` 的开头增加条件化规则:

```text
- memory 是历史经验，不是当前事实，也不是文档 citation。
- 当前工具观测（日志、指标、配置、部署记录）优先于历史 memory。
- 如果当前观测明确反驳 memory，必须优先采用当前观测，并说明历史 memory 可能已经过时。
- 如果当前观测不充分，可以把 memory 作为历史假设，但必须执行 fresh checks 验证。
- 不要把历史 memory 中的旧根因直接当成当前根因。
```

这比"必须总是说明历史可能过时"更稳，避免 LLM 在 memory 仍然有效时过度保守。

### 5.2 alert_pattern 专项提示

`format_alert_pattern_guidance(...)` 现在已有:

```text
注意: 这是历史根因假设，仍需执行 fresh checks 验证。
```

P6_v2 建议改为:

```text
注意: 这是历史根因假设。若当前日志、指标、配置或部署记录显示该问题已修复或不再成立，必须优先采用当前观测，并说明该记忆可能过时；若没有冲突证据，可把它作为排查假设并执行 fresh checks。
```

### 5.3 不做自动写回

P6_v2 不把 stale memory 自动改成 `conflict` 或 `candidate`。原因:

- 当前 V1 的长期 memory 仍是 reviewed sidecar memory。
- 自动 mutation 需要 review / audit / conflict merge 设计。
- 本轮只让 planner 在推理时更正确地使用 memory。

因此 prompt 只能要求"在报告中说明 memory 可能过时"，不能要求 LLM 真的修改 MemoryStore 状态。

## 6. 测试计划

### 6.1 Retrieval 单测

新增或扩展:

```text
tests/test_memory_retrieval_service.py
```

核心 case:

1. query 无 stale cue 时，保持原 lexical 排序。
2. query 有 `fixed last week` 时，超过 `stale_age_days` 的旧 memory 被降权。
3. 降权不是删除: 旧 memory 仍可出现在 top_k，只是不应压过同等相关的新 memory。
4. 中文 stale cue 如 `上周已修复` / `配置已更新` 触发降权。
5. 负向表达如 `fixed parameter` / `固定参数` / `最近有没有类似案例` 不触发降权。
6. `stale_age_days` / `stale_penalty` 可在 service 构造时注入，测试不依赖写死默认值。
7. trace 中能看到 cue、negative cue、penalized memory、base/final score。

### 6.2 Prompt 单测

新增或扩展:

```text
tests/test_memory_guidance_service.py
tests/test_memory_guidance_provider.py
```

核心 case:

1. `format_memory_guidance(...)` 包含"当前观测优先"规则。
2. guidance 仍包含"memory 不是 document citation"。
3. alert_pattern guidance 包含"历史根因假设"、"fresh checks"、"当前观测冲突时优先当前观测"。
4. prompt 文案是条件化的，不是每次都无条件宣称 memory 过时。

### 6.3 回归测试

至少运行:

```bash
.venv/bin/python -m unittest tests.test_memory_retrieval_service tests.test_memory_guidance_service -v
.venv/bin/python -m unittest tests.test_memory_guidance_provider tests.test_p5_shadow_mode tests.test_p5_planner_memory_integration -v
.venv/bin/python -m py_compile app/services/memory_retrieval_service.py app/services/memory_guidance_service.py
```

如果代码改动影响 planner/provider，再追加:

```bash
.venv/bin/python -m unittest tests.test_p5_shadow_mode_chain tests.test_memory_layered_evals -v
```

## 7. P6 full eval 复测策略

P6_v2 不要求一上来重跑 full P6。推荐顺序:

1. 先跑 deterministic retrieval / prompt 单测。
2. 再跑 memory retrieval eval / injection eval（如果相关脚本仍适用）。
3. 如果 stale-specific 行为已在单测中通过，再跑 full P6。

复测时看两个层次:

```text
infra 层:
- eval_status 是否仍为 valid
- hard_failure_count 是否为 0
- infra_failure_rate 是否为 0.0

质量层:
- stale_override 是否从 0/4 改善
- repeated_alert / plan_reuse 是否没有明显回退
- citation_invariance 是否仍 OK
- stale trace 是否能解释每个 stale 样本的降权行为
```

full P6 的目标不是重新证明 Phase A rollout gate，而是观察 stale quality 是否改善。

本轮不做 A/B 框架。若默认 `7 days / 0.5 penalty` 效果不稳，只记录结果和失败归因，后续单独开参数调优任务。

## 8. 验收标准

P6_v2 完成条件:

1. `stale-aware retrieval` 行为有单测覆盖。
2. stale cue 正向规则、负向过滤、可配置阈值/惩罚、trace 都有测试覆盖。
3. `stale override prompt` 行为有单测覆盖，且文案是条件化规则。
4. 原 P5 shadow / active guidance 回归通过。
5. RAG citation 边界没有变化。
6. `docs/memory_fusion_development_record.md` 记录:
   - 为什么开 P6_v2；
   - 改动文件；
   - 验证命令；
   - 是否重跑 full P6；
   - stale_override 最新结论。

P6_v2 不要求:

- stale_override 必须一次达到 4/4；
- MCP fixture 必须补齐；
- 自动把 stale memory 写成 conflict；
- 引入 hybrid / vector retrieval。

## 9. Stop Rules

遇到以下情况要停下来，不继续扩大范围:

1. 降权导致 repeated_alert 或 plan_reuse 明显回退。
2. 单测必须依赖真实 LLM/MCP 才能表达行为。
3. 为了让 stale_override 通过需要改 judge 而不是改 retrieval/prompt。
4. 需要自动 memory mutation 才能解释行为。
5. 需要引入 embedding / hybrid retrieval 才能继续。
6. 需要持续追加大量特殊 cue / negative cue，说明固定规则已经不适合，应另开语义 stale 检测设计。
7. 需要调多组参数才能判断方向，说明应另开 A/B 或参数 sweep 任务。

这些都说明 P6_v2 当前最小范围不够，应另开设计，而不是在本计划里扩张。

## 10. 延期项

以下建议暂不进入 P6_v2 第一版:

- A/B 测试框架: 参数 sweep 有价值，但会把本轮从行为修复变成实验框架建设。
- LLM stale cue 判断: 语义效果可能更好，但会引入成本、稳定性和可测性问题。
- read-only stale label 返回结构: 可以作为 trace 的后续产品化形态，第一版先放在 `trace` 内。
- memory TTL / 自动归档: 属于生命周期治理，需要 review / audit / rollback 设计，不应混入本轮。
- MCP fixture 补全: 只有确认某个失败样本确实是 fixture 错配时才做。

## 11. 面试 / 项目解释口径

如果被问"为什么 P6 已经 rollout YES，还要做 P6_v2"，答案是:

> P6 Phase A 解决的是评估可信度和 rollout gate。它证明 memory guidance 在 repeated alert 和 plan reuse 上已经有价值，所以可以继续 rollout；但报告同时暴露 stale_override 仍为 0/4。P6_v2 不推翻 rollout YES，而是把这个真实质量缺口拆出来单独优化。我们只做两个最小改动: retrieval 在识别 `fixed last week` / `上周已修复` 这类 stale cue 后对旧 memory 做可观测、可配置的保守降权；prompt 明确当前日志、指标、配置优先于历史 memory。MCP fixture、hybrid retrieval、LLM stale 判断和自动 conflict 写回都不混进本轮，避免把质量优化扩大成新架构项目。

## 12. 执行结果

时间: 2026-05-29

### 12.1 实际改动

本轮按计划只做 P6_v2 第一版质量优化:

- `app/services/memory_retrieval_service.py`
  - 增加短语级 stale cue 与 negative cue。
  - 增加可配置 `stale_age_days` / `stale_penalty`。
  - 在 post-score ranking 层对旧 memory 做保守降权，不修改 `LexicalMemoryScorer`。
  - 在 `trace.stale_policy` 中记录 `cue_detected`、`matched_cues`、`negative_cues`、`penalized_memory_ids` 和 `score_adjustments`。
  - 对 `updated_at` 排序做 timezone 归一化，避免 aware / naive datetime 比较错误。
- `app/services/memory_guidance_service.py`
  - 增加条件化 stale override prompt: 当前日志、指标、配置、部署记录等工具观测优先；当前观测明确反驳旧 memory 时说明历史 memory 可能过时；当前观测不充分时仍可把 memory 作为待验证假设。
- `app/services/memory_store.py`
  - `record_access()` 使用 `preserve_timestamps=True`，避免 retrieval access 把旧 memory 的内容更新时间刷新成当前时间。

本轮没有做:

- MCP fixture 补全。
- hybrid / vector retrieval。
- LLM stale cue 判断。
- A/B 参数框架。
- TTL / 自动归档。
- 自动 conflict 写回。
- P6 Phase A judge / infra policy 改动。

### 12.2 验证结果

相关单测与编译检查已通过:

```text
.venv/bin/python -m unittest tests.test_memory_retrieval_service tests.test_memory_store tests.test_memory_guidance_service tests.test_memory_guidance_provider tests.test_p6_memory_eval_infra -v
Ran 67 tests ... OK

.venv/bin/python -m compileall app/services/memory_store.py app/services/memory_retrieval_service.py tests/test_memory_store.py tests/test_memory_retrieval_service.py
passed

SSL_CERT_FILE='.venv/lib/python3.13/site-packages/certifi/cacert.pem' .venv/bin/python -m unittest discover tests -v
Ran 332 tests ... OK
```

最新 full P6 报告:

```text
evals/memory/p6_memory_eval_20260529_005432.json
eval_status=valid
continue_rollout=true
preflight.ok=true
hard_failure_count=0
infra_failure_rate=0.0
degraded_sample_count=6

repeated_alert=2/4
plan_reuse=3/4
stale_override=2/4
overall=7/12
categories_passed=3/3
```

四个 `p6_stale_*` guidance 样本均写出 `stale_policy` trace，且 trace 中包含 `matched_cues`、`penalized_memory_ids` 和 `score_adjustments`。本轮未再出现 `can't compare offset-naive and offset-aware datetimes`。

### 12.3 结论

P6_v2 第一版达到本计划验收口径:

- stale_override 从 0/4 改善到 2/4。
- full P6 仍为 infra-valid。
- rollout decision 仍为 YES，且 categories_passed 从 2/3 提升到 3/3。
- stale 样本失败时已经可以通过 `stale_policy` trace 判断是 cue、penalty、prompt 或 LLM 行为问题，而不是评估基础设施不可用。

剩余 2 个 stale 失败不在本轮继续调参。若后续继续优化，应另开小任务分析失败样本的 final response 与 key events，不要把 MCP fixture、hybrid retrieval、LLM classifier 或自动 memory lifecycle 混回 P6_v2 第一版。
