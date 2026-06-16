# P5 Shadow Mode 部署准备完成总结

## 完成时间
2026-05-26

## 背景
P5 memory guidance 集成已完成但保持 default-off 状态。为了在不影响实际输出的情况下观测 memory 召回效果，需要实现 shadow mode 及其配套的部署准备工作。

## 交付内容

### 1. 流量控制 (Flow Control)

**文件：**
- `app/services/shadow_mode_controller.py` - ShadowModeController 类
- `app/config.py` - 添加 shadow mode 配置字段
- `app/api/aiops.py` - 集成流量控制逻辑

**功能：**
- 白名单机制（优先级最高）：`MEMORY_SHADOW_ALLOWLIST` 环境变量，逗号分隔的 owner_id 列表
- 采样率控制：`MEMORY_SHADOW_SAMPLING_RATE` 环境变量，0.0-1.0 范围
- `ShadowModeController.resolve_memory_mode()` 解析最终 memory_mode：
  - 显式 `off` 或 `active` → 直接使用
  - 显式 `shadow` → 检查流量控制（白名单或采样）
  - 未指定 → 回退到 `enable_memory_guidance` 兼容逻辑

**验证：**
```bash
# 测试通过
.venv/bin/python -c "from app.services.shadow_mode_controller import ShadowModeController; ..."
```

### 2. 监控指标 (Monitoring Metrics)

**文件：**
- `app/services/shadow_mode_metrics.py` - ShadowModeMetrics 类和全局 shadow_metrics 实例
- `app/api/shadow_metrics.py` - 指标查询 API
- `app/main.py` - 注册 shadow_metrics router
- `app/api/aiops.py` - 集成请求指标收集
- `app/services/memory_retrieval_service.py` - 集成召回指标收集
- `app/services/memory_trace_service.py` - 集成 trace 写入指标收集

**指标：**
- `requests_total` - 总请求数
- `requests_shadow_enabled` - shadow 模式请求数
- `requests_shadow_disabled` - 非 shadow 模式请求数
- `allowlist_hits` - 白名单命中数
- `sampling_hits` - 采样命中数
- `memory_recalls` - memory 召回成功数
- `memory_recall_errors` - memory 召回失败数
- `trace_writes` - trace 写入成功数
- `trace_write_errors` - trace 写入失败数
- `memory_recall_latency_p50/p95/p99` - 召回延迟百分位数（毫秒）

**API：**
- `GET /api/shadow-metrics` - 获取当前指标快照
- `POST /api/shadow-metrics/reset` - 重置指标

**验证：**
```bash
# 测试通过
.venv/bin/python -c "from app.services.shadow_mode_metrics import shadow_metrics; ..."
```

### 3. Trace 清理 (Trace Cleanup)

**文件：**
- `scripts/cleanup_memory_traces.py` - 清理脚本（可执行）

**功能：**
- 解析 `mem_trace_YYYYMMDD_HHMMSS.txt` 文件名时间戳
- 删除超过保留期的 trace 文件（默认 7 天）
- 支持 `--dry-run` 试运行模式
- 支持 `--retention-days` 自定义保留天数
- 支持 `--trace-dir` 自定义 trace 目录
- Cron-ready 设计，可配置定时任务

**使用示例：**
```bash
# 试运行
.venv/bin/python scripts/cleanup_memory_traces.py --dry-run

# 实际清理 7 天前的 trace
.venv/bin/python scripts/cleanup_memory_traces.py

# 清理 30 天前的 trace
.venv/bin/python scripts/cleanup_memory_traces.py --retention-days 30

# Cron 配置（每天凌晨 2 点）
0 2 * * * cd /path/to/super_biz_agent_py && .venv/bin/python scripts/cleanup_memory_traces.py >> logs/trace_cleanup.log 2>&1
```

**验证：**
```bash
# 测试通过
.venv/bin/python scripts/cleanup_memory_traces.py --dry-run
```

### 4. Shadow Runbook

**文件：**
- `docs/P5_SHADOW_MODE_RUNBOOK.md`

**内容：**
- **启用 Shadow Mode**：配置流量控制、重启服务、验证配置
- **观测 Shadow Mode**：实时监控指标、查看 trace 文件、日志观测
- **常见问题排查**：4 个典型问题的排查步骤
  - Shadow 模式没有生效
  - Memory 召回失败率高
  - Trace 文件写入失败
  - 延迟过高
- **清理 Trace 文件**：手动清理和自动清理（Cron）
- **关闭 Shadow Mode**：临时关闭和永久关闭
- **升级到 Active Mode**：升级前检查清单、升级步骤、降级预案
- **监控告警建议**：4 个推荐告警规则

**推荐灰度策略：**
- 初期（第 1-3 天）：白名单 1-2 个内部测试账号，采样率 0.0
- 扩大（第 4-7 天）：白名单扩展到 5-10 个账号，采样率 0.05（5%）
- 稳定（第 8-14 天）：采样率提升到 0.1-0.2（10%-20%）

**健康标准：**
- `memory_recall_errors / memory_recalls < 0.01`（错误率 < 1%）
- `trace_write_errors / trace_writes < 0.01`（写入失败率 < 1%）
- `memory_recall_latency_p95 < 200ms`（P95 延迟 < 200ms）

## 验证结果

### 单元测试
```bash
.venv/bin/python -m unittest discover tests
# 结果：276 tests passed
```

### 组件测试
```bash
# ShadowModeController 测试通过
# ShadowModeMetrics 测试通过
# cleanup_memory_traces.py 测试通过
```

## 文档更新

### PROJECT_STATE.md
- 添加 P5 shadow mode 部署准备完成条目（2026-05-26）
- 更新 P6 next steps：标记 (1) 和 (2) 为 COMPLETE
- 添加新文件到 Key Paths：
  - `app/services/shadow_mode_controller.py`
  - `app/services/shadow_mode_metrics.py`
  - `app/services/memory_trace_service.py`
  - `app/services/memory_guidance_service.py`
  - `app/api/shadow_metrics.py`
  - `scripts/cleanup_memory_traces.py`
  - `docs/P5_SHADOW_MODE_RUNBOOK.md`

## 设计原则遵守

### Memory 默认关闭
- ✅ Memory 仍然默认 `memory_mode=off`
- ✅ Shadow mode 需要显式 `memory_mode="shadow"` + 流量控制批准
- ✅ Active mode 仍然 gated on P6 full eval + pilot validation

### 不影响现有语义
- ✅ 不注入 agent prompts（shadow mode 只记录，不注入）
- ✅ 不改变 `retrieve_knowledge` / `RetrievalService` / citation 语义
- ✅ 不添加 `retrieve_memory` 到默认 `RagAgentService.tools`

### 外层控制
- ✅ `ShadowModeController` 是外层流量控制，不侵入 planner 内部
- ✅ 流量控制在 API 层完成，service 层只接收最终 `memory_mode`

## 下一步

### 立即可做
1. **启用 Shadow Mode 观测**：
   - 配置白名单（1-2 个内部测试账号）
   - 启动服务并观测指标
   - 人工抽查 trace 文件质量

2. **完成 P6 Full Eval 执行**：
   - 修复评估环境（MCP server, Milvus, DashScope API）
   - 运行 `.venv/bin/python evals/memory/run_p6_memory_eval.py`
   - 验证 `eval_status=valid`（不是 `infra_failed`）
   - 根据 `continue_rollout` 结果更新文档

### 后续工作
3. **Shadow Mode 稳定运行**（建议 7-14 天）：
   - 监控健康指标
   - 收集 trace 样本
   - 人工评估 guidance 质量

4. **Active Mode 试点**：
   - 选择 1-2 个白名单用户
   - 使用 `memory_mode="active"`
   - 对比 active 和 baseline 诊断质量

5. **逐步放量**：
   - 扩大白名单或提升采样率
   - 最终全量上线（所有请求默认 `memory_mode="active"`）

## 风险和限制

### 当前限制
- Shadow mode 只支持 AIOps 诊断场景（`/api/aiops`）
- RAG chat 场景暂不支持 shadow mode
- 指标收集是内存级别，重启服务会丢失（未持久化到数据库）

### 已知风险
- Trace 文件持续增长可能占用磁盘空间（需定期清理）
- 高流量场景下 memory 召回可能增加延迟（需监控 P95）
- 白名单和采样率配置需要重启服务才能生效

### 降级方案
- 临时关闭：设置 `MEMORY_SHADOW_SAMPLING_RATE=0.0` 并重启
- 永久关闭：客户端请求时使用 `memory_mode="off"`
- 紧急降级：修改 `app/api/aiops.py` 强制 `final_memory_mode = "off"`

## 总结

P5 Shadow Mode 部署准备的 4 个组件全部完成：

1. ✅ 流量控制（白名单 + 采样率）
2. ✅ 监控指标（请求/召回/trace + 延迟）
3. ✅ Trace 清理（脚本 + Cron-ready）
4. ✅ Shadow Runbook（启用/观测/排查/升级）

所有组件已验证通过（276 单元测试 + 组件测试），文档已更新。

Memory 保持默认关闭，shadow mode 需要显式配置和流量控制批准，active mode 仍然 gated on P6 full eval。

建议优先完成 P6 full eval 执行，然后启用 shadow mode 进行灰度观测。
