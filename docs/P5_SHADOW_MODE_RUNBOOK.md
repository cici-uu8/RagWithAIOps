# P5 Shadow Mode Runbook

## 概述

Shadow Mode 是 Memory 功能的灰度观测模式，允许在不影响实际输出的情况下观测 memory 召回和格式化的效果。

**核心原则：**
- Memory 召回、格式化、trace 记录正常执行
- **不注入** LLM prompt，不影响诊断输出
- 通过 trace 文件和监控指标观测效果
- 为后续 Active Mode 上线提供数据支撑

---

## 启用 Shadow Mode

### 1. 配置流量控制

编辑 `.env` 文件，配置白名单和采样率：

```bash
# 白名单：逗号分隔的 owner_id 列表（优先级最高）
MEMORY_SHADOW_ALLOWLIST=user1,user2,team_oncall

# 采样率：0.0 - 1.0，白名单外的流量按此比例进入 shadow
# 0.0 = 完全关闭，0.1 = 10%，1.0 = 100%
MEMORY_SHADOW_SAMPLING_RATE=0.1
```

**推荐策略：**
- **初期（第 1-3 天）**：白名单 1-2 个内部测试账号，采样率 0.0
- **扩大（第 4-7 天）**：白名单扩展到 5-10 个账号，采样率 0.05（5%）
- **稳定（第 8-14 天）**：采样率提升到 0.1-0.2（10%-20%）

### 2. 重启服务

```bash
# 重启 FastAPI 服务以加载新配置
pkill -f "uvicorn app.main:app"
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 9900
```

### 3. 验证配置

```bash
# 检查配置是否生效
curl http://localhost:9900/api/shadow-metrics

# 预期返回：
# {
#   "requests_total": 0,
#   "requests_shadow_enabled": 0,
#   ...
# }
```

---

## 观测 Shadow Mode

### 1. 实时监控指标

```bash
# 查看当前指标
curl http://localhost:9900/api/shadow-metrics | jq

# 关键指标：
# - requests_shadow_enabled: shadow 模式请求数
# - allowlist_hits: 白名单命中数
# - sampling_hits: 采样命中数
# - memory_recalls: memory 召回成功数
# - memory_recall_errors: memory 召回失败数
# - trace_writes: trace 写入成功数
# - memory_recall_latency_p95: 召回延迟 P95（毫秒）
```

**健康标准：**
- `memory_recall_errors / memory_recalls < 0.01`（错误率 < 1%）
- `trace_write_errors / trace_writes < 0.01`（写入失败率 < 1%）
- `memory_recall_latency_p95 < 200ms`（P95 延迟 < 200ms）

### 2. 查看 Trace 文件

```bash
# 查看最新的 trace 文件
ls -lt traces/memory/ | head -10

# 查看具体 trace 内容
cat traces/memory/mem_trace_20260526_143022.txt
```

**Trace 文件包含：**
- Memory 召回的 memory_ids、namespaces、types
- 完整的 guidance 文本（如果注入会是什么样）
- Retrieval trace（候选数、匹配数、返回数）

### 3. 日志观测

```bash
# 查看 shadow mode 相关日志
tail -f logs/app.log | grep -E "SHADOW|MEMORY"

# 关键日志：
# [SHADOW-CONTROL] - 流量控制决策
# [MEMORY-SHADOW] - memory 召回和 trace 记录
# [SHADOW-METRICS] - 指标记录
```

---

## 常见问题排查

### 问题 1：Shadow 模式没有生效

**症状：** `requests_shadow_enabled` 始终为 0

**排查步骤：**
1. 检查 `.env` 配置是否正确加载
   ```bash
   curl http://localhost:9900/api/shadow-metrics
   # 如果 requests_total > 0 但 requests_shadow_enabled = 0，说明流量控制未通过
   ```

2. 检查请求中的 `memory_mode` 和 `memory_owner_id`
   ```bash
   # 正确的请求示例
   curl -X POST http://localhost:9900/api/aiops \
     -H "Content-Type: application/json" \
     -d '{
       "session_id": "test-123",
       "memory_mode": "shadow",
       "memory_owner_id": "user1"
     }'
   ```

3. 检查日志中的流量控制决策
   ```bash
   tail -f logs/app.log | grep SHADOW-CONTROL
   # 应该看到类似：
   # [SHADOW-CONTROL] owner=user1 in allowlist, enable shadow
   # 或
   # [SHADOW-CONTROL] owner=user2 sampled in (rate=0.1), enable shadow
   ```

### 问题 2：Memory 召回失败率高

**症状：** `memory_recall_errors / memory_recalls > 0.05`

**排查步骤：**
1. 检查 memory store 是否正常
   ```bash
   # 查看 memory 数据目录
   ls -la data/memory/
   ```

2. 检查错误日志
   ```bash
   tail -f logs/app.log | grep "memory_recall_errors"
   ```

3. 检查是否有 memory 数据
   ```bash
   # 如果没有 active memory，召回会返回空但不算错误
   # 真正的错误是异常导致的召回失败
   ```

### 问题 3：Trace 文件写入失败

**症状：** `trace_write_errors > 0`

**排查步骤：**
1. 检查 trace 目录权限
   ```bash
   ls -ld traces/memory/
   # 应该有写权限
   ```

2. 检查磁盘空间
   ```bash
   df -h
   ```

3. 检查错误日志
   ```bash
   tail -f logs/app.log | grep "trace_write"
   ```

### 问题 4：延迟过高

**症状：** `memory_recall_latency_p95 > 500ms`

**排查步骤：**
1. 检查 memory 数据量
   ```bash
   # 如果 active memory 过多（> 1000 条），考虑清理或优化
   ls -l data/memory/ | wc -l
   ```

2. 检查是否有慢查询
   ```bash
   tail -f logs/app.log | grep "memory_recall" | grep -E "[0-9]{3,}ms"
   ```

3. 考虑优化检索算法或添加索引

---

## 清理 Trace 文件

Shadow mode 会持续生成 trace 文件，需要定期清理避免磁盘占用过大。

### 手动清理

```bash
# 试运行：查看将删除哪些文件（默认保留 7 天）
.venv/bin/python scripts/cleanup_memory_traces.py --dry-run

# 实际清理 7 天前的 trace
.venv/bin/python scripts/cleanup_memory_traces.py

# 清理 30 天前的 trace
.venv/bin/python scripts/cleanup_memory_traces.py --retention-days 30
```

### 自动清理（Cron）

```bash
# 编辑 crontab
crontab -e

# 添加每天凌晨 2 点清理 7 天前的 trace
0 2 * * * cd /path/to/super_biz_agent_py && .venv/bin/python scripts/cleanup_memory_traces.py >> logs/trace_cleanup.log 2>&1
```

---

## 关闭 Shadow Mode

### 临时关闭

```bash
# 方法 1：设置采样率为 0，清空白名单
MEMORY_SHADOW_ALLOWLIST=""
MEMORY_SHADOW_SAMPLING_RATE=0.0

# 方法 2：客户端请求时使用 memory_mode="off"
curl -X POST http://localhost:9900/api/aiops \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-123",
    "memory_mode": "off"
  }'
```

### 永久关闭

编辑 `.env`，设置：

```bash
MEMORY_SHADOW_ALLOWLIST=""
MEMORY_SHADOW_SAMPLING_RATE=0.0
```

重启服务。

---

## 升级到 Active Mode

当 Shadow Mode 观测稳定后（建议至少运行 7-14 天），可以考虑升级到 Active Mode。

### 升级前检查清单

- [ ] Shadow mode 运行至少 7 天
- [ ] Memory 召回错误率 < 1%
- [ ] Trace 写入失败率 < 1%
- [ ] P95 延迟 < 200ms
- [ ] 人工抽查至少 20 个 trace 文件，确认 guidance 质量符合预期
- [ ] 与产品/业务团队确认升级计划

### 升级步骤

1. **小范围试点**：选择 1-2 个白名单用户，使用 `memory_mode="active"`
   ```bash
   curl -X POST http://localhost:9900/api/aiops \
     -H "Content-Type: application/json" \
     -d '{
       "session_id": "test-123",
       "memory_mode": "active",
       "memory_owner_id": "pilot_user1"
     }'
   ```

2. **观测试点效果**：
   - 对比 active 和 baseline 的诊断质量
   - 收集用户反馈
   - 监控延迟和错误率

3. **逐步扩大**：
   - 白名单扩展到更多用户
   - 或使用采样率逐步放量（5% → 10% → 20% → 50% → 100%）

4. **全量上线**：
   - 所有请求默认使用 `memory_mode="active"`
   - 保留 `memory_mode="off"` 作为降级开关

### 降级预案

如果 Active Mode 出现问题，立即降级：

```bash
# 方法 1：服务端强制关闭（最快）
# 修改 app/api/aiops.py，强制 final_memory_mode = "off"

# 方法 2：配置降级
MEMORY_SHADOW_ALLOWLIST=""
MEMORY_SHADOW_SAMPLING_RATE=0.0

# 方法 3：客户端降级
# 客户端请求时使用 memory_mode="off"
```

---

## 监控告警建议

建议配置以下告警规则（如果有监控系统）：

1. **Memory 召回错误率 > 5%**
   - 严重性：P2
   - 处理：检查 memory store 和日志

2. **Trace 写入失败率 > 5%**
   - 严重性：P3
   - 处理：检查磁盘空间和权限

3. **P95 延迟 > 500ms**
   - 严重性：P3
   - 处理：检查 memory 数据量和检索性能

4. **Shadow 模式请求数突降为 0**（如果预期应该有流量）
   - 严重性：P3
   - 处理：检查配置和流量控制逻辑

---

## 联系方式

如有问题或需要讨论 Active Mode 上线计划，请联系：

- **技术负责人**：[填写]
- **产品负责人**：[填写]
- **Slack 频道**：[填写]
