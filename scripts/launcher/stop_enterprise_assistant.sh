#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVER_URL="http://localhost:9900"
INCLUDE_AIOPS_LAB="${INCLUDE_AIOPS_LAB:-0}"

cd "$PROJECT_ROOT" || exit 1
mkdir -p logs

LOG_FILE="${PROJECT_ROOT}/logs/launcher_stop_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

ok() {
  printf 'OK: %s\n' "$1"
}

warn() {
  printf 'WARN: %s\n' "$1"
}

print_header() {
  printf '==========================================\n'
  if [ "$INCLUDE_AIOPS_LAB" = "1" ]; then
    printf '企业助手&数据库停止器\n'
  else
    printf '企业助手停止器\n'
  fi
  printf '时间: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
  printf '项目: %s\n' "$PROJECT_ROOT"
  printf '==========================================\n'
  printf '日志文件: %s\n' "$LOG_FILE"
}

print_status() {
  printf '\n当前状态:\n'

  if docker info >/dev/null 2>&1; then
    ok "Docker 运行中"
    if docker ps --format '{{.Names}}' | grep -q '^milvus-standalone$'; then
      ok "Milvus 容器运行中"
    else
      warn "Milvus 容器未运行"
    fi
  else
    warn "Docker 未运行"
  fi

  if curl -fsS "${SERVER_URL}/health" >/dev/null 2>&1; then
    ok "FastAPI 健康: ${SERVER_URL}"
  elif lsof -nP -iTCP:9900 -sTCP:LISTEN >/dev/null 2>&1; then
    warn "端口 9900 有进程监听，但健康检查未通过"
    lsof -nP -iTCP:9900 -sTCP:LISTEN || true
  else
    warn "FastAPI 未运行"
  fi

  if pgrep -f "mcp_servers/cls_server.py" >/dev/null 2>&1; then
    ok "CLS MCP 运行中"
  else
    warn "CLS MCP 未运行"
  fi

  if pgrep -f "mcp_servers/monitor_server.py" >/dev/null 2>&1; then
    ok "Monitor MCP 运行中"
  else
    warn "Monitor MCP 未运行"
  fi

  if pgrep -f "app.workers.document_processing_worker" >/dev/null 2>&1; then
    ok "文档处理 RQ worker 运行中"
  else
    warn "文档处理 RQ worker 未运行"
  fi

  if [ "$INCLUDE_AIOPS_LAB" = "1" ] && docker info >/dev/null 2>&1; then
    if docker compose -f aiops_lab/docker-compose.yml ps --services --filter status=running 2>/dev/null | grep -q .; then
      ok "AIOps lab 容器运行中"
    else
      warn "AIOps lab 容器未运行"
    fi
  fi
}

stop_document_worker() {
  printf '\n停止文档处理 worker:\n'
  if [ -f document_worker.pid ]; then
    pid="$(cat document_worker.pid)"
    if ps -p "$pid" >/dev/null 2>&1; then
      kill "$pid"
      ok "文档处理 RQ worker 已停止 (PID: $pid)"
    else
      warn "文档处理 RQ worker pid 文件存在，但进程不存在 (PID: $pid)"
    fi
    rm -f document_worker.pid
  else
    pkill -f "app.workers.document_processing_worker" 2>/dev/null && \
      ok "已停止所有文档处理 RQ worker 进程" || \
      warn "没有运行中的文档处理 RQ worker 进程"
  fi
}

stop_services() {
  printf '\n停止应用服务:\n'
  make stop || {
    warn "make stop 返回失败，尝试直接停止残留进程。"
    pkill -f "uvicorn app.main:app" 2>/dev/null || true
    pkill -f "mcp_servers/cls_server.py" 2>/dev/null || true
    pkill -f "mcp_servers/monitor_server.py" 2>/dev/null || true
  }
}

stop_aiops_lab() {
  [ "$INCLUDE_AIOPS_LAB" = "1" ] || return 0

  printf '\n停止 AIOps lab:\n'
  if docker info >/dev/null 2>&1; then
    docker compose -f aiops_lab/docker-compose.yml down || \
      warn "AIOps lab docker compose down 返回失败，请手动检查容器状态。"
  else
    warn "Docker 未运行，跳过 AIOps lab 停止。"
  fi
}

print_footer() {
  printf '\n==========================================\n'
  if [ "$INCLUDE_AIOPS_LAB" = "1" ]; then
    printf '企业助手&数据库服务已停止\n'
  else
    printf '企业助手应用服务已停止\n'
  fi
  printf 'Milvus/Docker 容器默认保留，方便下次快速启动。\n'
  printf '如果需要彻底关闭容器，可在项目目录手动运行: make down\n'
  printf '日志文件: %s\n' "$LOG_FILE"
  printf '==========================================\n'
}

print_header
print_status
stop_document_worker
stop_services
stop_aiops_lab
print_footer
