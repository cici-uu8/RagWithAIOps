# P6 Memory 评估设计

日期: 2026-05-25
范围: Memory guidance 价值判定（P5 已实现，默认关闭）。本阶段产出 `continue_rollout = true / false / trigger_hybrid` 决定后续路线。

## 0. 边界与不变量

- P5 已完成：memory guidance integration 已实现，默认关闭，通过 `enable_memory_guidance` flag 控制。
- P6 不改 `app/*` 运行时代码；只做评估，不做实现。
- 评估脚本与样例是本阶段唯一交付物。
- 阈值跑前固定（frozen pre-run），跑后不调。
- RAG citation invariance 必须成立：`retrieval_drift_bytes = 0`，memory 不能污染文档引用。
- 样本规模：至少 12 条（3 类 × 至少 4 条/类）。
- Judge 协议先于样本写定（不允许凭语义直觉选 expected behavior）。

## 1. 目标与方法

### 1.1 想回答的核心问题

Memory guidance 是否有实际价值？三个门槛：

- (a) **Repeated alert**: 第二次相似告警能召回旧根因假设，并仍执行 fresh checks。
- (b) **Plan reuse**: planner 被过去成功 plan template 引导，同时允许按新证据 replan。
- (c) **Stale override**: 新证据能推翻 stale memory，并把旧 memory 标记为 conflict/candidate。

如果 3 个门槛都不过，说明 memory guidance 当前无价值，应回滚或触发 P2.6 hybrid retrieval。

### 1.2 方法

对照评估：

- `baseline` flavor: `enable_memory_guidance=False`（当前默认）
- `guidance` flavor: `enable_memory_guidance=True`，预先写入 active memory
- 对比指标：repeated alert success rate、plan reuse success rate、stale override success rate

如果 guidance flavor 在 ≥ 2 类门槛上显著优于 baseline（success rate 提升 ≥ 0.20），说明 memory guidance 有价值；否则当前无价值。

## 2. Judge 协议（frozen pre-run）

### 2.1 Repeated Alert Success Rate

**输入**：
- `query`: 告警描述（第二次出现）
- `expected_alert_pattern`: 预期召回的 alert pattern memory
- `expected_root_cause`: 预期根因
- `expected_fresh_checks`: 预期仍执行的 fresh checks（工具调用）
- `baseline_response`: baseline flavor 的 AIOps 诊断响应
- `guidance_response`: guidance flavor 的 AIOps 诊断响应

**Success 条件（guidance flavor）**：
1. 诊断响应中提到了 `expected_root_cause` 或其同义表达
2. 诊断响应中仍执行了 `expected_fresh_checks` 中至少 80% 的工具调用
3. 诊断响应中没有把 memory 当作文档 citation（不出现 `SourceRef` 指向 memory）

**Failure 条件**：
- 未提到 expected root cause
- 或未执行 expected fresh checks
- 或把 memory 当作文档 citation

**Tie-breaker**：
- 如果 baseline 也提到了 root cause，但 guidance 更早提到（在 plan 阶段 vs 在 replanner 阶段），guidance 胜出
- 如果 baseline 和 guidance 都执行了 fresh checks，但 guidance 的 plan 更接近 expected plan template，guidance 胜出

**固定规则实现**：
```python
def judge_repeated_alert(sample, baseline_response, guidance_response) -> str:
    # 1. Check root cause mention
    guidance_mentions_root_cause = any(
        keyword in guidance_response.lower()
        for keyword in sample["expected_root_cause_keywords"]
    )
    
    # 2. Check fresh checks execution
    guidance_fresh_checks = extract_tool_calls(guidance_response)
    expected_checks = sample["expected_fresh_checks"]
    guidance_check_rate = len(
        set(guidance_fresh_checks) & set(expected_checks)
    ) / len(expected_checks)
    
    # 3. Check memory not treated as citation
    guidance_no_memory_citation = not has_memory_source_ref(guidance_response)
    
    # Success condition
    if (guidance_mentions_root_cause 
        and guidance_check_rate >= 0.8 
        and guidance_no_memory_citation):
        return "pass"
    else:
        return "fail"
```

### 2.2 Plan Reuse Success Rate

**输入**：
- `query`: 告警描述
- `expected_plan_template`: 预期召回的 plan template memory
- `expected_plan_steps`: 预期 plan 步骤（至少覆盖 60%）
- `allow_replan`: 是否允许按新证据 replan
- `baseline_response`: baseline flavor 的 AIOps 诊断响应
- `guidance_response`: guidance flavor 的 AIOps 诊断响应

**Success 条件（guidance flavor）**：
1. planner 输出的 plan 覆盖了 `expected_plan_steps` 中至少 60% 的步骤
2. 如果 `allow_replan=True`，允许 replanner 按新证据调整 plan
3. 诊断响应中没有把 memory 当作文档 citation

**Failure 条件**：
- plan 覆盖率 < 60%
- 或把 memory 当作文档 citation

**Tie-breaker**：
- 如果 baseline 也覆盖了 expected plan steps，但 guidance 的 plan 更接近 expected plan template（步骤顺序、工具选择），guidance 胜出

**固定规则实现**：
```python
def judge_plan_reuse(sample, baseline_response, guidance_response) -> str:
    # 1. Extract plan steps
    guidance_plan = extract_plan_steps(guidance_response)
    expected_steps = sample["expected_plan_steps"]
    
    # 2. Calculate coverage
    coverage = len(
        set(guidance_plan) & set(expected_steps)
    ) / len(expected_steps)
    
    # 3. Check memory not treated as citation
    guidance_no_memory_citation = not has_memory_source_ref(guidance_response)
    
    # Success condition
    if coverage >= 0.6 and guidance_no_memory_citation:
        return "pass"
    else:
        return "fail"
```

### 2.3 Stale Override Success Rate

**输入**：
- `query`: 告警描述
- `stale_memory`: 过期的 alert pattern memory（root cause 已不适用）
- `expected_new_root_cause`: 新工具证据揭示的新根因
- `expected_memory_status`: 预期旧 memory 被标记为 `conflict` 或 `candidate`
- `baseline_response`: baseline flavor 的 AIOps 诊断响应
- `guidance_response`: guidance flavor 的 AIOps 诊断响应

**Success 条件（guidance flavor）**：
1. 诊断响应中提到了 `expected_new_root_cause`（新工具证据）
2. 诊断响应中没有盲目采用 stale memory 的旧根因
3. 如果有 memory update 机制，旧 memory 被标记为 `conflict` 或 `candidate`

**Failure 条件**：
- 盲目采用 stale memory 的旧根因
- 或未提到新工具证据揭示的新根因

**Tie-breaker**：
- 如果 baseline 也发现了新根因，但 guidance 更明确地说明"旧假设不适用"，guidance 胜出

**固定规则实现**：
```python
def judge_stale_override(sample, baseline_response, guidance_response) -> str:
    # 1. Check new root cause mention
    guidance_mentions_new_root_cause = any(
        keyword in guidance_response.lower()
        for keyword in sample["expected_new_root_cause_keywords"]
    )
    
    # 2. Check not blindly using stale memory
    stale_root_cause_keywords = sample["stale_memory"]["root_cause_keywords"]
    guidance_not_using_stale = not all(
        keyword in guidance_response.lower()
        for keyword in stale_root_cause_keywords
    )
    
    # Success condition
    if guidance_mentions_new_root_cause and guidance_not_using_stale:
        return "pass"
    else:
        return "fail"
```

## 3. 评估指标

### 3.1 主门槛 / 软观察分层

| 指标 | 类型 | 跑前阈值 |
|---|---|---|
| **RAG citation invariance** | 强断言 | `retrieval_drift_bytes = 0`；任一失败 = AssertionError 立刻停 |
| **Repeated alert success rate** | 主门槛 | guidance 比 baseline 提升 ≥ 0.20（至少 4 条样本） |
| **Plan reuse success rate** | 主门槛 | guidance 比 baseline 提升 ≥ 0.20（至少 4 条样本） |
| **Stale override success rate** | 主门槛 | guidance 比 baseline 提升 ≥ 0.20（至少 4 条样本） |
| **Token overhead** | 软观察 | guidance 比 baseline token 增加 < 30% |
| **Answer text diff rate** | 软观察 | 全表入报告；不做硬门 |

### 3.2 Continue Rollout 判定逻辑（frozen pre-run）

```python
continue_rollout = (
    citation_invariance_ok
    and sum([
        repeated_alert_lift >= 0.20,
        plan_reuse_lift >= 0.20,
        stale_override_lift >= 0.20
    ]) >= 2  # 至少 2 类门槛通过
    and token_overhead < 0.30
)
```

**不允许跑后调阈值** —— 如果只有 1 类门槛通过，结论就是 `continue_rollout = false`，记入 Open Problems，**不**降到 ≥ 1 来"凑过线"。

### 3.3 Trigger Hybrid Retrieval 判定逻辑

如果 `continue_rollout = false`，进一步判断是否触发 P2.6 hybrid retrieval：

```python
trigger_hybrid = (
    citation_invariance_ok
    and repeated_alert_lift < 0.20  # repeated alert 门槛未过
    and "memory not recalled" in failure_reasons  # 失败原因是 memory 召回不足
)
```

如果 `trigger_hybrid = true`，说明 lexical-only retrieval 不足，应启动 P2.6 Tencent-style hybrid retrieval 设计。

## 4. 样例设计：12 条 / 3 类

| 类别 | 数量 | 设计目的 | 是否参与门槛判定 |
|---|---|---|---|
| `repeated_alert` | 4 | 第二次相似告警能召回旧根因假设，并仍执行 fresh checks | ✓ |
| `plan_reuse` | 4 | planner 被过去成功 plan template 引导 | ✓ |
| `stale_override` | 4 | 新证据能推翻 stale memory | ✓ |

样本字段：

```json
{
  "id": "p6_repeated_001",
  "category": "repeated_alert",
  "query": "service-a CPUHigh alert triggered again",
  "expected_alert_pattern": "mem_alert_cpu_high",
  "expected_root_cause": "memory leak in cache layer",
  "expected_root_cause_keywords": ["memory leak", "cache", "heap"],
  "expected_fresh_checks": ["query_metrics", "query_logs", "check_recent_deploy"],
  "pre_seeded_memory": {
    "memory_id": "mem_alert_cpu_high",
    "memory_type": "alert_pattern",
    "content": "CPUHigh on service-a usually caused by memory leak in cache layer",
    "payload": {
      "alert_name": "CPUHigh",
      "service": "service-a",
      "root_cause": "memory leak in cache layer",
      "fix": "restart service and check cache config"
    }
  }
}
```

样本纪律（沿用 P5.f1 教训，跑前固定）：

1. 先用 `_p6_memory_probe.py` 跑 candidate query 的 memory recall 命中分布。
2. 再用 `_p6_memory_kw_probe.py` 验证 `expected_root_cause_keywords` 在 memory content 里**实际出现**。
3. 不允许凭语义直觉选 keyword；不允许凭"看 memory 内容猜命中"写 `expected_alert_pattern`。
4. Probe 失败的 candidate query → 替换或归类到别类，不强写。

## 5. 评估流程

### 5.1 Pre-seed Active Memory

在评估前，预先写入 active memory：

```python
# Pre-seed active memory for guidance flavor
memory_store = MemoryStore(store_path="./uploads/_metadata/oncall_memory_p6_eval.sqlite3")

for sample in p6_samples:
    if "pre_seeded_memory" in sample:
        memory_record = MemoryRecord(
            memory_id=sample["pre_seeded_memory"]["memory_id"],
            owner_id="default",
            namespace="memory://oncall/alert-patterns",
            memory_type=sample["pre_seeded_memory"]["memory_type"],
            content=sample["pre_seeded_memory"]["content"],
            summary=sample["pre_seeded_memory"]["content"][:200],
            payload=sample["pre_seeded_memory"]["payload"],
            status="active",
            source="p6_eval_fixture",
            evidence={"source": "p6_eval_fixture"},
            tags=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        memory_store.create(memory_record)
```

### 5.2 Run Baseline Flavor

```python
# Baseline: enable_memory_guidance=False
for sample in p6_samples:
    baseline_response = await aiops_service.diagnose(
        session_id=f"p6_baseline_{sample['id']}",
        enable_memory_guidance=False,
        memory_owner_id="default"
    )
    # Collect baseline response
```

### 5.3 Run Guidance Flavor

```python
# Guidance: enable_memory_guidance=True
for sample in p6_samples:
    guidance_response = await aiops_service.diagnose(
        session_id=f"p6_guidance_{sample['id']}",
        enable_memory_guidance=True,
        memory_owner_id="default"
    )
    # Collect guidance response
```

### 5.4 Judge and Report

```python
# Judge each sample
for sample in p6_samples:
    baseline_response = baseline_responses[sample["id"]]
    guidance_response = guidance_responses[sample["id"]]
    
    if sample["category"] == "repeated_alert":
        result = judge_repeated_alert(sample, baseline_response, guidance_response)
    elif sample["category"] == "plan_reuse":
        result = judge_plan_reuse(sample, baseline_response, guidance_response)
    elif sample["category"] == "stale_override":
        result = judge_stale_override(sample, baseline_response, guidance_response)
    
    # Collect result
```

## 6. Stop-loss

- RAG citation invariance 失败 → 停（memory 污染了文档引用）。
- **Pre-seed memory 任一条失败 → 立即停**：memory store 写入失败说明 P1-P4 实现有 bug。
- Probe 揭示候选 query ≥ 50% 找不到对应 expected memory → 停下来重设计样本，不强写。
- 跑后调阈值或重写样本 → 不允许。
- **如果 `continue_rollout = false` 且 `trigger_hybrid = false`**：写明 "Memory guidance 当前无价值"，记入 `PROJECT_STATE.md` Open Problems；P5 rollout 停止；**不**因为想推 P5 就放宽阈值或扩样本。

## 7. 验证清单（结束态守住）

- `unittest discover tests`: 241/241 仍持平（不动 app/* 与 tests/*）。
- RAG citation invariance: `retrieval_drift_bytes = 0`，12 样本 all OK。
- 12 条样本的 baseline / guidance success rate 全表入报告。
- `continue_rollout` 判定结果显式写出（true / false）+ 触发样本 id 列出。
- `trigger_hybrid` 判定结果显式写出（true / false）+ 失败原因分析。
- 报告 markdown 头部显式标注：(i) P5 已实现，默认关闭；(ii) 评估是对照实验，不是 P5 实现；(iii) 门槛阈值（lift ≥ 0.20，≥ 2 类门槛通过）；(iv) 样本来源（design-fixture 或 real oncall case）。

## 8. 执行顺序

1. **设计落地（本文档）→ 用户审阅。**（当前步）
2. 写 `_p6_memory_probe.py`，跑通 pre-seed active memory 到 isolated store。
3. 草拟 15-20 条 candidate query，跑 memory probe 看 recall 命中分布。
4. 写 `_p6_memory_kw_probe.py`，验证 `expected_root_cause_keywords` 实际出现。
5. 收敛到 12 条 / 3 类，写入 `p6_samples.jsonl`。
6. 写 `run_p6_memory_eval.py`。
7. 单轮跑评估。
8. 写报告 + 更新状态文档（PROJECT_STATE / task_plan / memory_fusion_development_record / findings / progress）；按 `continue_rollout` 结果决定下一步：`true` → 启动 P5 shadow 模式；`false` + `trigger_hybrid=true` → 启动 P2.6 hybrid retrieval；`false` + `trigger_hybrid=false` → P5 rollout 停止，记入 Open Problems。

## 9. 不做的事（防偷跑）

- **不实现新的 memory 能力**：本阶段不动 P1-P5 已完成的 schema/store/retrieval/artifact/candidate/review/guidance。
- **不允许跑后调阈值**：≥ 0.20 / ≥ 2 类门槛是 frozen pre-run。
- **不允许 probe 失败时强写样本**：宁可减少 query 数量也不强写。
- **不允许把 `continue_rollout = false` 的结果改写成 "需要扩样本"**：如果 false 就 false，记入 Open Problems；要扩样本是另一个独立决策。
- **不开 P5 shadow 模式或小范围 flag-on**：P6 评估通过后才考虑。

## 10. 文档约束（必须显式写进报告）

报告 markdown 头部必须显式标注以下 4 条，不允许只在脚注或附录里写：

1. 门槛阈值：`guidance_lift ≥ 0.20`，且在 ≥ 2 类门槛上稳定出现。**等价含义**：因 success rate 的连续性，lift 0.20 语义上是 "guidance flavor 在该类别上至少多成功 20% 的样本"。这条等价含义必须显式写在报告头部，避免被误读为"小幅提升也算过线"。
2. 样本来源（design-fixture 或 real oncall case）+ 样本数量（12 条 / 3 类）。
3. 评估是对照实验（baseline vs guidance），**不是** P5 实现；P5 已实现，默认关闭。
4. `continue_rollout` 判定结果（true / false）+ 决策影响（启动 P5 shadow / 停止 rollout / 触发 P2.6）。

## 11. 与 P5 的关系

- **不替换** P5 已完成的 memory guidance integration；P6 评估是**价值判定**而不是 P5 follow-up。
- **复用**：P5 的 `enable_memory_guidance` flag、planner memory guidance 逻辑、memory retrieval service。
- P6 评估通过后，才考虑 P5 shadow 模式或小范围 flag-on；P6 评估不通过，P5 rollout 停止。

## 12. Faithfulness 边界

按 2026-05-19 reframing 决定：**factual answer faithfulness 是跨 pipeline 的 RAG 质量横切关注点，不是 P5 / P6 交付项**，不是 P6 gate。即使 `continue_rollout = false`，faithfulness 也作为独立线另起。本设计**不**把 faithfulness 写进 P6 门槛判定。
