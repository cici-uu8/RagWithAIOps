# P5 Shadow Mode 设计文档

**创建时间**: 2026-05-26  
**状态**: 已实现，待测试

---

## 1. 背景

P5 memory guidance 已实现为 `enable_memory_guidance` flag（默认 False）。当设置为 True 时，memory guidance 直接注入 planner prompt，影响输出。

P6 lite evaluation 通过后，需要在生产环境中小流量验证 memory guidance 的实际效果，但不能直接影响用户体验。因此需要 **shadow mode**：

- 召回 memory
- 格式化 guidance
- 记录完整 trace
- **不注入 prompt**，不影响 planner 输出

---

## 2. 设计原则

### 2.1 单一枚举替代双 bool

**问题**: `enable_memory_guidance` + `memory_shadow_mode` 两个 bool 组合状态容易混乱

**解决**: 使用单一枚举 `MemoryMode`

```python
class MemoryMode(str, Enum):
    OFF = "off"          # 默认，不召回 memory
    SHADOW = "shadow"    # 召回 + 格式化 + 记录，不进 prompt
    ACTIVE = "active"    # 召回 + 格式化 + 进 prompt
```

### 2.2 统一检索 + 格式化，最后分叉

**问题**: 如果 shadow 和 active 各自实现检索逻辑，后续维护困难

**解决**: 共享检索和格式化逻辑，只在最后一步分叉

```python
if memory_mode in [MemoryMode.SHADOW, MemoryMode.ACTIVE]:
    # 统一检索
    memory_response = memory_service.retrieve(...)
    # 统一格式化
    memory_guidance_text = format_memory_guidance(...)
    # 统一记录 trace
    memory_observation = trace_service.create_observation(...)
    
    # 分叉点：是否注入 prompt
    if memory_mode == MemoryMode.ACTIVE:
        memory_guidance_for_prompt = memory_guidance_text
    else:  # SHADOW
        memory_guidance_for_prompt = ""
```

### 2.3 命名：observation 而非 guidance

**问题**: shadow 模式下，memory 不是 "guidance"（不指导 LLM），只是观测结果

**解决**: 
- 返回字段命名为 `memory_observation`（不是 `shadow_memory_guidance`）
- Trace 文件命名为 `mem_trace_{timestamp}.txt`
- 日志前缀为 `[MEMORY-SHADOW]` 或 `[MEMORY-ACTIVE]`

### 2.4 日志简洁，全文单独存储

**问题**: 直接打印完整 guidance 会污染日志，且可能泄露内容

**解决**:
- 日志只记录摘要：`hit_count`, `memory_ids`（前3个）, `would_inject`, `trace_id`
- 完整 guidance 文本存储到 `traces/memory/{trace_id}.txt`

---

## 3. 实现架构

### 3.1 新增文件

#### `app/models/memory_mode.py`

```python
class MemoryMode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    ACTIVE = "active"
    
    @classmethod
    def from_state(cls, state: dict) -> "MemoryMode":
        """
        从 state 解析 memory_mode
        
        兼容旧的 enable_memory_guidance:
        - memory_mode 显式设置时优先使用
        - enable_memory_guidance=True → ACTIVE
        - 默认 → OFF
        """
```

#### `app/services/memory_trace_service.py`

```python
class MemoryTraceService:
    def create_observation(
        mode: MemoryMode,
        memory_response: MemoryRetrievalResponse,
        memory_guidance_text: str,
        query: str,
        owner_id: str
    ) -> Dict[str, Any]:
        """
        创建 memory observation trace
        
        返回:
        {
            "mode": "shadow" | "active",
            "trace_id": "mem_trace_20260526_123456",
            "query": "...",
            "owner_id": "...",
            "memory_ids": ["mem_001", "mem_002"],
            "namespaces": ["memory://oncall/alert-patterns"],
            "memory_types": ["alert_pattern"],
            "hit_count": 2,
            "would_inject": false,
            "timestamp": "2026-05-26T12:34:56Z",
            "retrieval_trace": {...},
            "full_text_path": "traces/memory/mem_trace_20260526_123456.txt"  # shadow only
        }
        """
    
    def _save_shadow_trace(file_path, observation, memory_guidance_text):
        """保存 shadow trace 到文件"""
    
    @staticmethod
    def format_log_summary(observation) -> str:
        """格式化日志摘要（不包含全文）"""
```

### 3.2 修改文件

#### `app/agent/aiops/planner.py`

**核心改动**:

```python
# 1. 解析 memory_mode
memory_mode = MemoryMode.from_state(state)

# 2. 统一检索 + 格式化（shadow 和 active 共享）
memory_observation = None
memory_guidance_for_prompt = ""

if memory_mode in [MemoryMode.SHADOW, MemoryMode.ACTIVE]:
    memory_response = memory_service.retrieve(...)
    memory_guidance_text = format_memory_guidance(...)
    memory_observation = trace_service.create_observation(...)
    
    # 日志只打摘要
    logger.info(MemoryTraceService.format_log_summary(memory_observation))
    
    # 分叉点
    if memory_mode == MemoryMode.ACTIVE:
        memory_guidance_for_prompt = memory_guidance_text
    else:  # SHADOW
        logger.info(f"Memory guidance 已记录到 trace，不注入 prompt: {memory_observation['full_text_path']}")

# 3. 合并 context（shadow 模式下 memory_guidance_for_prompt 为空）
combined_experience_context = combine_memory_and_document_context(
    memory_guidance_for_prompt, experience_context
)

# 4. 返回 memory_observation
result = {"plan": plan_steps}
if memory_observation:
    result["memory_observation"] = memory_observation
return result
```

---

## 4. Trace 文件格式

### 4.1 文件路径

```
traces/memory/mem_trace_20260526_123456.txt
```

### 4.2 文件内容

```markdown
# Memory Shadow Trace

**Trace ID**: mem_trace_20260526_123456
**Mode**: shadow
**Owner**: user_001
**Query**: CPUHigh alert on service-a
**Hit Count**: 2
**Memory IDs**: mem_001, mem_002
**Namespaces**: memory://oncall/alert-patterns
**Memory Types**: alert_pattern
**Would Inject**: false
**Timestamp**: 2026-05-26T12:34:56Z

---

## Retrieval Trace

```json
{
  "lexical_hits": 2,
  "semantic_hits": 0,
  "hybrid_score": 0.95
}
```

---

## Full Guidance Text

[完整的 memory_guidance 原文]
```

---

## 5. 使用方式

### 5.1 OFF 模式（默认）

```python
state = {
    "input": "CPUHigh alert",
    # memory_mode 未设置，默认 OFF
}
# 不召回 memory，不记录 trace
```

### 5.2 SHADOW 模式

```python
state = {
    "input": "CPUHigh alert",
    "memory_mode": "shadow",
    "memory_owner_id": "user_001",
}
# 召回 memory，记录 trace，不注入 prompt
# 返回 memory_observation 供后续分析
```

### 5.3 ACTIVE 模式

```python
state = {
    "input": "CPUHigh alert",
    "memory_mode": "active",
    "memory_owner_id": "user_001",
}
# 召回 memory，记录 trace，注入 prompt
# 返回 memory_observation
```

### 5.4 兼容旧 API

```python
state = {
    "input": "CPUHigh alert",
    "enable_memory_guidance": True,  # 等价于 memory_mode="active"
}
```

---

## 6. 小流量控制（外层实现）

**设计原则**: planner 只负责 "拿不拿、记不记、进不进 prompt"，不负责流量控制逻辑。

流量控制应在调用 planner 之前完成：

```python
# 外层服务（如 API handler）
def prepare_planner_state(user_request):
    memory_mode = "off"  # 默认
    
    # 白名单检查
    if user_request.owner_id in MEMORY_SHADOW_ALLOWLIST:
        memory_mode = "shadow"
    # 采样率检查
    elif random.random() < MEMORY_SHADOW_SAMPLING_RATE:
        memory_mode = "shadow"
    
    return {
        "input": user_request.input,
        "memory_mode": memory_mode,
        "memory_owner_id": user_request.owner_id,
    }
```

**配置示例**:

```python
# config.py
MEMORY_SHADOW_ALLOWLIST = ["user_001", "user_002"]  # 白名单优先
MEMORY_SHADOW_SAMPLING_RATE = 0.01  # 1% 采样率
```

---

## 7. 测试覆盖

### 7.1 单元测试

**文件**: `tests/test_p5_shadow_mode.py`

**覆盖场景**:
- `MemoryMode.from_state()` 正确解析各种 state
- `memory_mode=off` 不召回 memory
- `memory_mode=shadow` 召回但不注入 prompt
- `memory_mode=active` 召回且注入 prompt
- Shadow mode 生成 trace 文件
- 兼容旧的 `enable_memory_guidance` flag

### 7.2 集成测试（待补充）

- 端到端验证 shadow mode 不影响 planner 输出
- 验证 trace 文件正确生成
- 验证 memory_observation 正确返回

---

## 8. 部署计划

### 8.1 Phase 1: 白名单小流量（1-2 个 owner）

```python
MEMORY_SHADOW_ALLOWLIST = ["internal_test_user"]
MEMORY_SHADOW_SAMPLING_RATE = 0.0
```

**验证**:
- Trace 文件正确生成
- 日志格式正确
- 不影响 planner 输出

### 8.2 Phase 2: 1% 采样

```python
MEMORY_SHADOW_ALLOWLIST = []
MEMORY_SHADOW_SAMPLING_RATE = 0.01
```

**监控**:
- Trace 文件数量
- Memory 召回成功率
- 性能影响（latency, memory usage）

### 8.3 Phase 3: 根据 trace 分析决定是否扩大

- 分析 shadow trace，评估 memory guidance 质量
- 如果质量达标，逐步提升采样率或切换到 ACTIVE 模式
- 如果质量不达标，调整 memory 策略后重新 shadow

---

## 9. 监控指标

### 9.1 Shadow Mode 指标

- `memory_shadow_requests_total`: shadow 请求总数
- `memory_shadow_hits_total`: shadow 命中总数
- `memory_shadow_trace_files_total`: 生成的 trace 文件数
- `memory_shadow_latency_ms`: shadow 模式延迟

### 9.2 质量指标（需人工分析 trace）

- Memory guidance 与实际 root cause 的匹配度
- Memory guidance 与最终 plan 的相关性
- Stale memory 比例（updated_at 过旧）

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Shadow mode 增加延迟 | 用户体验下降 | 1. 小流量测试<br>2. 监控 latency<br>3. 设置 timeout |
| Trace 文件占用磁盘 | 磁盘满 | 1. 定期清理旧 trace<br>2. 设置 trace 保留期限（7天）<br>3. 监控磁盘使用 |
| Memory 召回失败影响主流程 | 服务不可用 | 1. 已实现 try-except 保护<br>2. Memory 失败不影响 planner 继续执行 |
| Shadow 和 active 逻辑不一致 | 切换到 active 后行为不符预期 | 1. 共享检索 + 格式化逻辑<br>2. 只在最后一步分叉<br>3. 集成测试验证一致性 |

---

## 11. 后续工作

### 11.1 短期（P6 full eval 前）

- [ ] 补充集成测试
- [ ] 实现 trace 文件清理逻辑
- [ ] 添加监控指标
- [ ] 白名单小流量测试

### 11.2 中期（P6 full eval 后）

- [ ] 分析 shadow trace，评估 memory guidance 质量
- [ ] 根据分析结果调整 memory 策略
- [ ] 逐步扩大 shadow 流量

### 11.3 长期

- [ ] 如果 shadow 验证通过，切换到 ACTIVE 模式
- [ ] 实现 A/B 测试框架（baseline vs memory guidance）
- [ ] 自动化 memory 质量评估

---

## 12. 参考

- P5 Memory Guidance 实现: `app/services/memory_guidance_service.py`
- P6 Lite Evaluation 报告: `evals/memory/reports/p6_memory_eval_lite_20260525_234134.md`
- Memory Retrieval Service: `app/services/memory_retrieval_service.py`
