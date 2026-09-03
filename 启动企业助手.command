#!/bin/bash

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

cd "$PROJECT_ROOT" || {
  echo "无法进入项目目录: $PROJECT_ROOT"
  read -r -p "按回车关闭窗口..."
  exit 1
}

bash "$PROJECT_ROOT/scripts/launcher/start_enterprise_assistant.sh"
status=$?

echo
if [ "$status" -eq 0 ]; then
  echo "启动完成。可以在浏览器里直接对话。"
  echo
  echo "重要：请保持这个启动窗口打开。"
  echo "关闭这个窗口会让后端服务停止，前端会出现 Failed to fetch。"
  echo "需要停止时，请双击“停止企业助手.command”。"
  echo
  echo "正在监控后端健康状态，每 15 秒检查一次..."
  while true; do
    if curl -fsS "http://localhost:9900/health" >/dev/null 2>&1; then
      sleep 15
    else
      echo
      echo "检测到后端服务已停止。"
      break
    fi
  done
else
  echo "启动失败。请查看上方错误和 logs/launcher_*.log。"
fi

read -r -p "按回车关闭窗口..."
exit "$status"
