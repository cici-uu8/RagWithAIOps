# AIOps 真实模拟执行清单

## 目标

在本地构建一个足够接近企业运维场景的 AIOps 验证环境，用真实指标、真实告警、真实日志、真实依赖数据来验证现有 `AIOpsService` 的诊断能力。

本清单的目标不是生产部署，也不是把项目改成企业全套技术栈。核心原则是：

- 保留当前 Python / FastAPI / LangGraph / FastMCP 项目主线。
- 用 Docker Compose 搭建本地可复现环境。
- 用 Prometheus + Alertmanager 建立真实告警链路。
- 用 JSON 日志文件作为第一版日志源，后续再升级 Elasticsearch。
- 用 MySQL / Redis 模拟高频业务故障。
- 用本地 CMDB / 工单 / 发布记录表模拟企业上下文。
- AIOps 仍通过 MCP 工具查询外部信号，不让 `AIOpsService` 直接查数据库或监控系统。

当前实现状态（2026-06-03）：第一版代码、配置、MCP 工具、本地服务级 smoke、真实 8003/8004 MCP discovery、Docker Compose lab、Alertmanager 三故障活跃告警链路和 `/api/aiops` 三场景 3/3 根因验收均已完成。最终复验已覆盖 AIOps lab targeted tests 13/13、P6 timeout 单测复跑、AIOps 相关回归 51/51、targeted `ruff check`、targeted `compileall`、Compose config、`--skip-aiops-api` 告警链路 smoke 3/3 和完整 `/api/aiops` smoke 3/3。

## 非目标

第一版不做以下内容：

- 不接真实生产系统。
- 不接真实 CAS / LDAP。
- 不上 Kubernetes。
- 不接 Oracle / 达梦。
- 不接 SkyWalking。
- 不接 DLP / 敏感词审核。
- 不接 SharePoint / NAS / 对象存储。
- 不把数据库工具加入默认 AIOps MCP 工具池。
- 不修改 planner / executor / replanner 的核心 LangGraph state contract。

这些内容属于后续公司试点或生产接入阶段，不作为本地 AIOps 诊断能力验证的前置条件。

## 推荐技术栈

| 层级 | 第一版技术 | 目的 |
| --- | --- | --- |
| 业务服务 | Python FastAPI | 模拟 data-sync / order / inventory 等服务 |
| 指标采集 | Prometheus | 采集服务指标和故障指标 |
| 告警管理 | Alertmanager | 产生和查询活跃告警 |
| 日志源 | JSON 日志文件 | 第一版轻量跑通日志查询 |
| 日志升级 | Elasticsearch + Kibana | 第二版更贴近 ELK |
| 数据库 | MySQL | 模拟慢查询、连接池、业务数据异常 |
| 缓存 | Redis | 模拟缓存击穿、连接失败、队列积压 |
| 企业上下文 | SQLite 或 MySQL | 存 CMDB、发布记录、历史工单、负责人 |
| 工具接入 | FastMCP | 保持当前 AIOps 工具边界 |
| Agent 编排 | 现有 AIOpsService | 继续使用 planner -> executor -> replanner |

## 目标架构

```text
FastAPI 模拟业务服务
  ├─ /metrics
  ├─ /inject/*
  └─ JSON logs

Prometheus
  └─ alert rules

Alertmanager
  └─ active alerts

MySQL / Redis
  └─ failure signals

CMDB / tickets / deployments
  └─ service context

FastMCP tools
  ├─ Monitor MCP -> Alertmanager / Prometheus
  ├─ CLS MCP -> JSON logs or Elasticsearch
  └─ CMDB MCP -> service context tables

AIOpsService
  └─ planner -> executor -> replanner -> diagnosis report
```

## 目录建议

```text
aiops_lab/
  docker-compose.yml
  prometheus/
    prometheus.yml
    alert_rules.yml
  alertmanager/
    alertmanager.yml
  services/
    data_sync_service/
      app.py
    order_service/
      app.py
    inventory_service/
      app.py
  mysql/
    business_schema.sql
    seed_business_data.sql
  cmdb/
    schema.sql
    seed.py
  logs/
    data-sync-service.jsonl
    order-service.jsonl
    inventory-service.jsonl
  scripts/
    inject_fault.py
    reset_faults.py
    smoke_aiops.py
```

第一版可以放在 repo 内的新目录，或先放在 `scripts/aiops_lab/` 下。正式进入实现前再决定最终目录。

## 阶段 0：收口边界

- [x] 确认 DB-MySQL-4 已提交，AIOps 模拟环境作为新 track 开始。
- [x] 确认当前工作树没有任何数据库轨道未提交改动，包括 DB-MySQL-4 或后续文档 / 状态文件。
- [x] 如果存在数据库轨道未提交改动，先单独提交、暂存或移到独立分支；不能把 DB 和 AIOps 改动混在一个提交里。
- [x] 确认第一版只做本地 AIOps 验证环境，不改生产接入策略。
- [x] 确认不把 database tools 加入默认 `config.mcp_servers`。
- [x] 确认新增内容不会改变已有 `/api/aiops` 事件语义。
- [x] 开工前检查当前前后端可用功能是否一致：聊天页和管理员后台已对齐；执行看板缺 Bearer token 已修复；后端 API-only 能力暂不强行产品化为 UI。

验收：

- `git log --oneline` 能看到 DB-MySQL-4 收口提交。
- `git status --short` 中没有 DB 轨道相关未提交文件。
- AIOps 清单、代码、验证输出能和 DB 轨道文件明确分开。
- 本清单作为新 track 的执行依据。

## 阶段 1：模拟业务服务

目标：构建 2-3 个真实运行的 FastAPI 服务，能产生指标、日志和故障。

执行方式必须增量化：先完成 `data-sync-service + CPUHigh + Prometheus + Alertmanager + /api/aiops smoke`，证明最小闭环成立后，再扩展 `order-service` 和 `inventory-service`。不要等三个服务都写完才接监控链路。

服务建议：

- `data-sync-service`
  - 模拟元数据同步。
  - 连接 MySQL 和 Redis。
  - 支持 CPUHigh、DBSlowQuery、RedisQueueBacklog 场景。
- `order-service`
  - 模拟订单查询和写入。
  - 依赖 MySQL。
  - 支持慢查询和 5xx 错误。
- `inventory-service`
  - 模拟库存查询。
  - 依赖 Redis 缓存。
  - 支持 cache miss 和缓存击穿。

每个服务至少实现：

- [x] `GET /health`
- [x] `GET /metrics`
- [x] `POST /inject/reset`
- [x] 结构化 JSON 日志输出。
- [x] 服务名、环境、实例 ID 等基础标签。

业务 MySQL schema 第一版必须定义：

```text
sync_jobs
  job_id
  source_system
  target_system
  status
  last_sync_at
  updated_rows

sync_runs
  run_id
  job_id
  started_at
  finished_at
  status
  latency_ms

orders
  order_id
  customer_id
  status
  total_amount
  created_at

order_items
  item_id
  order_id
  sku
  quantity
  unit_price

inventory_items
  sku
  warehouse_id
  available_quantity
  reserved_quantity
  updated_at

inventory_reservations
  reservation_id
  sku
  order_id
  quantity
  status
  created_at
```

这些表属于模拟业务服务自己的数据，不等同于 CMDB / 工单 / 发布记录表。`business_schema.sql` 负责建业务表，`seed_business_data.sql` 负责插入可复现初始数据。

验收：

- 浏览器或 `curl` 能访问每个服务的 `/health`。
- Prometheus 能 scrape 每个服务的 `/metrics`。
- 日志文件能看到 `service_name`、`level`、`message`、`trace_id`、`timestamp`。
- MySQL 启动后能建出业务表，并有足够数据支撑慢查询、订单查询、库存查询和同步任务场景。

## 阶段 2：故障注入

目标：故障必须可控、可复现、可恢复，不能靠“等服务自己坏”。

每个故障注入接口建议：

```text
POST /inject/cpu-high?duration=30s
POST /inject/db-slow?duration=60s
POST /inject/redis-queue-backlog?size=200
POST /inject/cache-miss?duration=60s
POST /inject/error-rate?rate=0.3&duration=60s
POST /inject/reset
```

第一版必须实现：

- [x] CPUHigh：让服务指标超过 80%。
- [x] DBSlowQuery：让查询延迟超过 2 秒。
- [x] RedisQueueBacklog：让队列长度超过 100。
- [x] Reset：恢复正常状态，避免影响下一轮测试。

验收：

- 手动触发注入后，Prometheus 指标能变化。
- reset 后指标恢复。
- 每次注入会写一条结构化日志，包含 fault type 和 duration。

## 阶段 3：Prometheus 和 Alertmanager

目标：建立真实的“指标异常 -> 告警触发 -> Agent 查询告警”链路。

Prometheus 配置：

- [x] scrape `data-sync-service`
- [x] scrape `order-service`
- [x] scrape `inventory-service`
- [x] 加载 `alert_rules.yml`

Docker Compose 和 MCP 地址要求：

- [x] Prometheus 对宿主机暴露 `localhost:9090`。
- [x] Alertmanager 对宿主机暴露 `localhost:9093`。
- [x] Docker 内部服务名固定为 `prometheus:9090` 和 `alertmanager:9093`。
- [x] Monitor MCP 通过配置读取地址，不在工具函数里硬编码。
- [x] 本地默认配置建议：

```text
AIOPS_PROMETHEUS_URL=http://localhost:9090
AIOPS_ALERTMANAGER_URL=http://localhost:9093
```

如果 Monitor MCP 也放进 Docker Compose，则容器内配置改为：

```text
AIOPS_PROMETHEUS_URL=http://prometheus:9090
AIOPS_ALERTMANAGER_URL=http://alertmanager:9093
```

告警规则第一版：

```yaml
groups:
  - name: aiops-lab
    rules:
      - alert: CPUHigh
        expr: service_cpu_percent > 80
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "CPU usage is high on {{ $labels.service_name }}"

      - alert: DBSlowQuery
        expr: mysql_query_latency_seconds > 2
        for: 30s
        labels:
          severity: warning
        annotations:
          summary: "Database query latency is high on {{ $labels.service_name }}"

      - alert: RedisQueueBacklog
        expr: redis_queue_length > 100
        for: 30s
        labels:
          severity: warning
        annotations:
          summary: "Redis queue backlog is high on {{ $labels.service_name }}"
```

验收：

- `curl http://localhost:9090/-/ready` 返回 ready。
- `curl http://localhost:9093/api/v2/alerts` 能返回 JSON。
- CPUHigh 注入后 Alertmanager 出现活跃告警。
- DBSlowQuery 注入后 Alertmanager 出现活跃告警。
- RedisQueueBacklog 注入后 Alertmanager 出现活跃告警。
- reset 后告警能恢复或进入 resolved 状态。

## 阶段 4：日志链路

第一版目标：不先上 ES，先用 JSON 日志文件验证证据链。

日志字段要求：

```json
{
  "timestamp": "2026-06-02T10:00:00+08:00",
  "service_name": "data-sync-service",
  "instance_id": "data-sync-1",
  "level": "ERROR",
  "trace_id": "trace-xxx",
  "event_type": "db_slow_query",
  "message": "metadata sync query exceeded latency threshold",
  "latency_ms": 3200
}
```

必须支持：

- [x] 按服务名查询日志。
- [x] 按时间范围查询日志。
- [x] 按 level 过滤。
- [x] 按 keyword 过滤。
- [x] 对错误类型做简单聚合。

第二版升级：

- [ ] 接 Elasticsearch。
- [ ] `CLS MCP` 从 ES 查询日志。
- [ ] Kibana 仅作为人工观察界面，不作为 Agent 必需依赖。

验收：

- 注入 DBSlowQuery 后，日志里能查到慢查询证据。
- 注入 RedisQueueBacklog 后，日志里能查到队列积压证据。
- AIOps 报告能引用具体日志证据，而不是只说“可能”。

## 阶段 5：CMDB / 工单 / 发布记录

目标：让 Agent 不只看指标和日志，还能查企业上下文。

本地表建议：

```text
services
  service_name
  owner_team
  owner_user
  environment
  dependencies
  runbook_url

deployments
  deployment_id
  service_name
  version
  deployed_at
  operator
  change_summary

tickets
  ticket_id
  service_name
  alert_name
  root_cause
  resolution
  created_at
```

第一版数据：

- [x] `data-sync-service` owner 为 `platform-team`。
- [x] `data-sync-service` 最近有一次发布记录。
- [x] 历史工单包含一次 CPUHigh / DBSlowQuery 类似问题。
- [x] `order-service` 依赖 MySQL。
- [x] `inventory-service` 依赖 Redis。

验收：

- MCP 工具能查到服务负责人。
- MCP 工具能查到最近发布。
- MCP 工具能查到相似历史工单。
- AIOps 报告能把“最近发布 / 历史工单 / 当前日志指标”合并成诊断证据。

## 阶段 6：MCP 工具改造

目标：保持现有 AIOps 编排不变，把真实数据源挂到工具后面。

### Monitor MCP

改造 `mcp_servers/monitor_server.py`：

- [x] `query_active_alerts()`
  - 查询 Alertmanager `/api/v2/alerts`。
  - 返回活跃告警列表。
- [x] `query_metric_series(service_name, metric_name, start_time, end_time)`
  - 查询 Prometheus HTTP API。
  - 返回时序点和统计摘要。
- [x] `get_service_health(service_name)`
  - 汇总活跃告警、关键指标、健康状态。

### CLS MCP

改造 `mcp_servers/cls_server.py`：

- [x] `search_service_logs(service_name, start_time, end_time, level=None, keyword=None, limit=100)`
  - 第一版查 JSON 日志文件。
  - 第二版查 Elasticsearch。
- [x] `analyze_log_pattern(service_name, start_time, end_time)`
  - 汇总 error、timeout、slow_query、redis_backlog 等模式。

### CMDB MCP

新增或扩展工具：

- [x] `get_service_info(service_name)`
- [x] `get_recent_deployments(service_name, limit=5)`
- [x] `search_historical_tickets(service_name, alert_name=None, limit=5)`
- [x] `list_service_dependencies(service_name)`

验收：

- `get_mcp_tools_with_retry()` 能发现新增工具。
- planner 能在工具描述中看到 `query_active_alerts`。
- executor 能实际调用工具并返回真实数据。
- 不改变已有 local tools：`get_current_time`、`retrieve_knowledge`。

当前证据：2026-06-03 临时启动 8003/8004 MCP server 后，`get_mcp_tools_with_retry(force_new_first=True)` 发现 16 个工具，包含新增 Monitor / CLS / CMDB 工具和旧 Monitor / CLS 工具。完整 `/api/aiops` smoke 三个 case 的 `actual_tools` 均包含 `query_active_alerts`、`query_metric_series`、`search_service_logs`。

## 阶段 7：AIOps 默认任务调整

目标：让默认诊断从“泛泛诊断系统”变成“先查活跃告警，再按告警展开”。

建议调整 `aiops_service.py` 默认任务描述，但不要改 LangGraph state contract。

默认诊断步骤应表达为：

```text
1. 先调用 query_active_alerts 查询当前活跃告警。
2. 如果没有活跃告警，说明未发现当前告警，并给出已检查的数据源。
3. 如果有活跃告警，按 severity 和 last_triggered_at 排序。
4. 对每个告警查询相关服务指标、日志、最近发布、历史工单和依赖关系。
5. 基于证据输出根因判断、处理建议和风险评估。
6. 不得编造未查询到的数据。
```

验收：

- 没有告警时，报告明确说明“未发现活跃告警”，并列出检查过的数据源。
- 有 CPUHigh 告警时，报告必须包含：
  - 告警名。
  - 服务名。
  - 指标趋势。
  - 日志证据。
  - 服务负责人或 owner team。
  - 根因判断。
  - 处理建议。

## 阶段 8：端到端 smoke

第一轮 smoke 场景：

```text
场景: data-sync-service CPUHigh
操作:
1. 启动 Docker Compose。
2. 触发 /inject/cpu-high?duration=90s。
3. 等待 Alertmanager 产生 CPUHigh。
4. 调用 /api/aiops。
5. 检查诊断报告。
```

验收条件：

- [x] `/api/aiops` 能完成，不出现 MCP get_tools 连接失败。
- [x] planner 计划包含查询活跃告警。
- [x] executor 至少调用一次 Monitor MCP。
- [x] executor 至少调用一次 CLS MCP。
- [x] 报告包含 CPUHigh、data-sync-service、CPU 指标、日志证据。
- [x] 报告不出现没有工具证据支持的编造结论。

当前证据：`python3 aiops_lab/scripts/smoke_aiops.py --api-url http://127.0.0.1:9900` 在 CPUHigh、DBSlowQuery、RedisQueueBacklog 三个 case 均返回 `alert_found=true`、`missing_tools=[]`、`diagnosis_contains_required_evidence=true`、`diagnosis_root_cause_correct=true`、`infra_error=null`。

第二轮 smoke 场景：

```text
场景: DBSlowQuery
操作:
1. 触发 /inject/db-slow?duration=90s。
2. 等待 DBSlowQuery 告警。
3. 调用 /api/aiops。
4. 检查报告是否定位到 MySQL 慢查询。
```

第三轮 smoke 场景：

```text
场景: RedisQueueBacklog
操作:
1. 触发 /inject/redis-queue-backlog?size=200。
2. 等待 RedisQueueBacklog 告警。
3. 调用 /api/aiops。
4. 检查报告是否定位到队列积压。
```

## 阶段 9：质量评估

目标：把“看起来能跑”变成可评估结果。

建议记录每次 smoke：

```text
case_id
fault_type
service_name
expected_root_cause
expected_tools
actual_tools
diagnosis_contains_required_evidence
diagnosis_root_cause_correct
latency_seconds
infra_error
notes
```

第一版通过标准：

- [x] 3 个故障场景全部能触发告警。
- [x] 3 个故障场景 AIOps 都能完成报告。
- [x] 3 个故障场景报告都包含指标和日志证据。
- [x] 3/3 根因判断正确。受控注入场景不是模糊线上事故，CPUHigh、DBSlowQuery、RedisQueueBacklog 都应被准确定位。
- [x] 不出现工具连接失败。
- [x] 不出现明显编造证据。

## 阶段 10：后续升级

只有第一版跑通后，再考虑：

- [ ] JSON 日志升级 Elasticsearch。
- [ ] Grafana dashboard。
- [ ] SkyWalking 或 OpenTelemetry trace。
- [ ] 接公司统一 AI 平台代理。
- [ ] 接 CAS / LDAP。
- [ ] 接 DLP / 敏感词审核。
- [ ] 接 SharePoint / NAS / 对象存储。
- [ ] 小规模 Docker 试点。
- [ ] 生产 K8s / PaaS 部署方案。

这些升级必须基于第一版本地 smoke 的真实缺口，不按“看起来企业化”直接堆技术栈。

## 推荐执行顺序

1. 先把 DB 轨道未提交改动单独收口，保证 AIOps track 工作树干净。
2. 建 `aiops_lab` 目录和 Docker Compose。
3. 写 `business_schema.sql` 和 `seed_business_data.sql`，先只支撑 `data-sync-service`。
4. 写一个 `data-sync-service`，先只做 CPUHigh 和 JSON 日志。
5. 接 Prometheus + Alertmanager，并固定 `9090` / `9093` 地址。
6. 改 Monitor MCP 的 `query_active_alerts` 和 `query_metric_series`。
7. 改 CLS MCP 查 JSON 日志文件。
8. 跑 CPUHigh 端到端 smoke，必须一次闭环成功后再扩服务。
9. 再扩展 DBSlowQuery 和业务 MySQL 慢查询。
10. 再扩展 RedisQueueBacklog。
11. 补 CMDB / 工单 / 发布记录。
12. 形成 3 个固定评估 case，并要求 3/3 根因正确。

## 当前边界结论

本 track 的核心验收不是“技术栈像不像生产”，而是：

- 告警是否由真实指标触发。
- Agent 是否能查询真实告警、指标、日志和上下文。
- 诊断报告是否基于证据。
- 故障是否可复现、可恢复、可评估。

只要这四点成立，本地 AIOps 验证环境就达到了第一阶段目标。
