#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVER_URL="http://localhost:9900"
HEALTH_URL="${SERVER_URL}/health"
FRONTEND_URL="${SERVER_URL}/"
FRONTEND_CACHE_BUST_URL="${SERVER_URL}/?v=$(date +%s)"
DASHBOARD_URL="${SERVER_URL}/static/enterprise-dashboard.html"
TOTAL_STEPS=6
INCLUDE_AIOPS_LAB="${INCLUDE_AIOPS_LAB:-0}"
AIOPS_DATA_SYNC_HEALTH_URL="http://localhost:9101/health"
AIOPS_PROMETHEUS_READY_URL="http://localhost:9090/-/ready"
AIOPS_ALERTMANAGER_READY_URL="http://localhost:9093/-/ready"

if [ "$INCLUDE_AIOPS_LAB" = "1" ]; then
  TOTAL_STEPS=7
fi

cd "$PROJECT_ROOT" || exit 1
mkdir -p logs

LOG_FILE="${PROJECT_ROOT}/logs/launcher_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

step() {
  printf '\n[%s/%s] %s\n' "$1" "$TOTAL_STEPS" "$2"
}

ok() {
  printf 'OK: %s\n' "$1"
}

warn() {
  printf 'WARN: %s\n' "$1"
}

fail() {
  printf '\nERROR: %s\n' "$1"
  printf '日志文件: %s\n' "$LOG_FILE"
  exit 1
}

wait_for_docker() {
  local max_attempts=90
  local attempt=0

  while [ "$attempt" -lt "$max_attempts" ]; do
    if docker info >/dev/null 2>&1; then
      printf '\n'
      ok "Docker 已就绪"
      return 0
    fi
    attempt=$((attempt + 1))
    printf '\r等待 Docker 启动... [%s/%s]' "$attempt" "$max_attempts"
    sleep 1
  done

  printf '\n'
  return 1
}

wait_for_health() {
  local max_attempts=90
  local attempt=0

  while [ "$attempt" -lt "$max_attempts" ]; do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
      printf '\n'
      ok "后端健康检查通过: ${HEALTH_URL}"
      return 0
    fi
    attempt=$((attempt + 1))
    printf '\r等待后端服务就绪... [%s/%s]' "$attempt" "$max_attempts"
    sleep 1
  done

  printf '\n'
  return 1
}

wait_for_url() {
  local label="$1"
  local url="$2"
  local max_attempts="${3:-90}"
  local attempt=0

  while [ "$attempt" -lt "$max_attempts" ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      printf '\n'
      ok "${label} 已就绪: ${url}"
      return 0
    fi
    attempt=$((attempt + 1))
    printf '\r等待 %s 就绪... [%s/%s]' "$label" "$attempt" "$max_attempts"
    sleep 1
  done

  printf '\n'
  return 1
}

print_header() {
  printf '==========================================\n'
  if [ "$INCLUDE_AIOPS_LAB" = "1" ]; then
    printf '企业助手&数据库启动器\n'
  else
    printf '企业助手启动器\n'
  fi
  printf '时间: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
  printf '项目: %s\n' "$PROJECT_ROOT"
  printf '==========================================\n'
  printf '日志文件: %s\n' "$LOG_FILE"
}

check_environment() {
  command -v docker >/dev/null 2>&1 || fail "未找到 docker 命令，请先安装 Docker Desktop。"
  command -v make >/dev/null 2>&1 || fail "未找到 make 命令。"
  command -v curl >/dev/null 2>&1 || fail "未找到 curl 命令。"
  command -v open >/dev/null 2>&1 || fail "未找到 macOS open 命令，无法自动打开浏览器。"

  [ -f ".env" ] || fail "缺少 .env 文件，请先按 README 配置 DASHSCOPE_API_KEY。"
  [ -d ".venv" ] || fail "缺少 .venv 虚拟环境，请先运行: uv sync --frozen"
  [ -x ".venv/bin/python" ] || fail ".venv/bin/python 不存在或不可执行，请检查 Python 环境。"

  if ! grep -Eq '^DASHSCOPE_API_KEY=.+$' .env || grep -Eq '^DASHSCOPE_API_KEY=(your-api-key|your_api_key)?$' .env; then
    warn ".env 中未检测到有效 DASHSCOPE_API_KEY；前端能打开，但模型对话可能失败。"
  else
    ok "环境文件和虚拟环境已存在"
  fi
}

configure_aiops_lab_env() {
  [ "$INCLUDE_AIOPS_LAB" = "1" ] || return 0

  export AIOPS_PROMETHEUS_URL="http://localhost:9090"
  export AIOPS_ALERTMANAGER_URL="http://localhost:9093"
  export AIOPS_LOGS_DIR="aiops_lab/logs"
  export AIOPS_CMDB_SQLITE_PATH="aiops_lab/cmdb/aiops_context.db"

  ok "AIOps lab 环境变量已配置"
}

ensure_docker_running() {
  if docker info >/dev/null 2>&1; then
    ok "Docker 已运行"
    return 0
  fi

  warn "Docker 未运行，尝试启动 Docker Desktop。"
  if ! open -ga Docker >/dev/null 2>&1; then
    if command -v colima >/dev/null 2>&1; then
      warn "Docker Desktop 未能通过 open 启动，尝试启动 Colima。"
      colima start || fail "Colima 启动失败，请手动启动 Docker。"
    else
      fail "无法启动 Docker Desktop，请手动打开 Docker 后重试。"
    fi
  fi

  wait_for_docker || fail "Docker 启动超时，请确认 Docker Desktop 已完全启动。"
}

ensure_port_available_or_healthy() {
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    ok "后端已经运行"
    return 0
  fi

  if lsof -nP -iTCP:9900 -sTCP:LISTEN >/dev/null 2>&1; then
    printf '\n端口 9900 当前占用:\n'
    lsof -nP -iTCP:9900 -sTCP:LISTEN || true
    fail "端口 9900 已被占用，但 /health 不健康。请先停止占用进程。"
  fi
}

start_dependencies() {
  make up || fail "Milvus/Docker 依赖启动失败。"
  ok "Milvus 依赖启动命令完成"
}

start_aiops_lab() {
  printf '准备 AIOps lab CMDB...\n'
  .venv/bin/python aiops_lab/cmdb/seed.py >/dev/null || fail "AIOps lab CMDB seed 失败。"

  printf '启动 AIOps lab: Prometheus / Alertmanager / MySQL / Redis / 三个模拟服务...\n'
  docker compose -f aiops_lab/docker-compose.yml up --build -d || fail "AIOps lab Docker Compose 启动失败。"

  wait_for_url "data-sync-service" "$AIOPS_DATA_SYNC_HEALTH_URL" 120 || fail "data-sync-service 启动超时。"
  wait_for_url "Prometheus" "$AIOPS_PROMETHEUS_READY_URL" 120 || fail "Prometheus 启动超时。"
  wait_for_url "Alertmanager" "$AIOPS_ALERTMANAGER_READY_URL" 120 || fail "Alertmanager 启动超时。"

  ok "AIOps lab 已接入主应用诊断链路"
  warn "AIOps lab 启动不会自动制造故障；需要演示故障时再手动注入或运行 smoke。"
}

start_services() {
  make start || fail "MCP 或 FastAPI 启动失败。"
  wait_for_health || fail "后端健康检查超时，请查看 server.log。"
}

start_document_worker() {
  if pgrep -f "app.workers.document_processing_worker" >/dev/null 2>&1; then
    ok "文档处理 RQ worker 已经在运行中"
    return 0
  fi

  printf '启动文档处理 RQ worker...\n'
  nohup .venv/bin/python -m app.workers.document_processing_worker > document_worker.log 2>&1 &
  echo $! > document_worker.pid
  sleep 2

  if pgrep -f "app.workers.document_processing_worker" >/dev/null 2>&1; then
    ok "文档处理 RQ worker 启动成功"
    printf '   PID: %s\n' "$(cat document_worker.pid)"
    printf '   日志: document_worker.log\n'
  else
    fail "文档处理 RQ worker 启动失败，请查看 document_worker.log。"
  fi
}

open_frontend() {
  open "$FRONTEND_CACHE_BUST_URL" || fail "无法打开前端页面。"
  ok "聊天前端已打开: ${FRONTEND_CACHE_BUST_URL}"
}

print_footer() {
  printf '\n==========================================\n'
  if [ "$INCLUDE_AIOPS_LAB" = "1" ]; then
    printf '企业助手&数据库已准备好\n'
  else
    printf '企业助手已准备好\n'
  fi
  printf '聊天前端: %s\n' "$FRONTEND_URL"
  printf '执行看板: %s\n' "$DASHBOARD_URL"
  printf 'API 文档: %s/docs\n' "$SERVER_URL"
  printf '文档 worker 日志: %s/document_worker.log\n' "$PROJECT_ROOT"
  if [ "$INCLUDE_AIOPS_LAB" = "1" ]; then
    printf 'AIOps lab data-sync-service: %s\n' "$AIOPS_DATA_SYNC_HEALTH_URL"
    printf 'AIOps lab Prometheus: http://localhost:9090\n'
    printf 'AIOps lab Alertmanager: http://localhost:9093\n'
  fi
  if [ "$INCLUDE_AIOPS_LAB" = "1" ]; then
    printf '停止服务: 双击 停止企业助手&数据库.command\n'
  else
    printf '停止服务: 双击 停止企业助手.command\n'
  fi
  printf '日志文件: %s\n' "$LOG_FILE"
  printf '==========================================\n'
}

print_header
CURRENT_STEP=1

run_step() {
  step "$CURRENT_STEP" "$1"
  CURRENT_STEP=$((CURRENT_STEP + 1))
}

run_step "检查本地环境"
check_environment
configure_aiops_lab_env

run_step "检查 Docker"
ensure_docker_running

run_step "启动 Milvus"
start_dependencies

if [ "$INCLUDE_AIOPS_LAB" = "1" ]; then
  run_step "启动 AIOps lab"
  start_aiops_lab
fi

run_step "启动 MCP 和 FastAPI"
ensure_port_available_or_healthy
start_services

run_step "启动文档处理 worker"
start_document_worker

run_step "打开聊天前端"
open_frontend

print_footer
