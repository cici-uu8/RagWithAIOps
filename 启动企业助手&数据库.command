#!/bin/bash

PROJECT_ROOT="/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"

cd "$PROJECT_ROOT" || {
  echo "无法进入项目目录: $PROJECT_ROOT"
  read -r -p "按回车关闭窗口..."
  exit 1
}

INCLUDE_AIOPS_LAB=1 bash "$PROJECT_ROOT/scripts/launcher/start_enterprise_assistant.sh"
status=$?

echo
if [ "$status" -eq 0 ]; then
  echo "启动完成。主应用和 AIOps lab 都已接好。"
  echo
  echo "重要：请保持这个启动窗口打开。"
  echo "关闭这个窗口会让后端服务停止，前端会出现 Failed to fetch。"
  echo "故障不会自动制造；需要演示 CPUHigh/DBSlowQuery 时再手动注入或运行 smoke。"
  echo "需要完整停止时，请双击“停止企业助手&数据库.command”。"
  echo
  echo "正在监控主应用和 AIOps lab 健康状态，每 15 秒检查一次..."
  while true; do
    if \
      curl -fsS "http://localhost:9900/health" >/dev/null 2>&1 && \
      curl -fsS "http://localhost:9101/health" >/dev/null 2>&1 && \
      curl -fsS "http://localhost:9090/-/ready" >/dev/null 2>&1 && \
      curl -fsS "http://localhost:9093/-/ready" >/dev/null 2>&1; then
      sleep 15
    else
      echo
      echo "检测到主应用或 AIOps lab 已停止。"
      break
    fi
  done
else
  echo "启动失败。请查看上方错误和 logs/launcher_*.log。"
fi

read -r -p "按回车关闭窗口..."
exit "$status"
