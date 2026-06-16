# AIOps Lab

本目录是 `docs/aiops_真实模拟执行清单.md` 的第一版本地验证环境。

## 启动

```bash
python aiops_lab/cmdb/seed.py
docker compose -f aiops_lab/docker-compose.yml up --build
```

服务地址：

- data-sync-service: `http://localhost:9101`
- order-service: `http://localhost:9102`
- inventory-service: `http://localhost:9103`
- Prometheus: `http://localhost:9090`
- Alertmanager: `http://localhost:9093`
- MySQL: `localhost:3308`
- Redis: `localhost:6380`

## MCP 配置

本地运行 MCP server 时使用：

```bash
export AIOPS_PROMETHEUS_URL=http://localhost:9090
export AIOPS_ALERTMANAGER_URL=http://localhost:9093
export AIOPS_LOGS_DIR=aiops_lab/logs
export AIOPS_CMDB_SQLITE_PATH=aiops_lab/cmdb/aiops_context.db
```

如果把 MCP server 放进 Compose 内部，再把 Prometheus / Alertmanager 地址改为容器服务名。

## 故障注入

```bash
python aiops_lab/scripts/inject_fault.py data-sync-service CPUHigh --duration 120s
python aiops_lab/scripts/inject_fault.py data-sync-service DBSlowQuery --duration 120s
python aiops_lab/scripts/inject_fault.py data-sync-service RedisQueueBacklog --size 200 --duration 120s
python aiops_lab/scripts/reset_faults.py
```

## Smoke

只验证 lab 告警链路：

```bash
python aiops_lab/scripts/smoke_aiops.py --skip-aiops-api
```

连同 `/api/aiops` 一起验证时，先启动主应用和 MCP server，并提供可登录账号或 token：

```bash
python aiops_lab/scripts/smoke_aiops.py --api-url http://localhost:9900
```
