#!/bin/bash

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

cd "$PROJECT_ROOT" || {
  echo "无法进入项目目录: $PROJECT_ROOT"
  read -r -p "按回车关闭窗口..."
  exit 1
}

INCLUDE_AIOPS_LAB=1 bash "$PROJECT_ROOT/scripts/launcher/stop_enterprise_assistant.sh"
status=$?

echo
if [ "$status" -eq 0 ]; then
  echo "主应用和 AIOps lab 停止完成。"
else
  echo "停止过程遇到问题。请查看上方输出和 logs/launcher_stop_*.log。"
fi

read -r -p "按回车关闭窗口..."
exit "$status"
