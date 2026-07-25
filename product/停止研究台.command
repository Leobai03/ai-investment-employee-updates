#!/bin/zsh
set -e
cd "$(dirname "$0")"

STOPPED=0
for PID_FILE in runtime/app.pid runtime/demo.pid; do
  if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" >/dev/null 2>&1; then
      kill "$PID"
      STOPPED=1
    fi
    rm -f "$PID_FILE"
  fi
done

if [[ "$STOPPED" == "1" ]]; then
  echo "研究台已停止。"
else
  echo "研究台当前没有运行。"
fi

PLIST="$HOME/Library/LaunchAgents/icu.leobai825.ai-research.plist"
if [[ -f "$PLIST" ]]; then
  echo "注意：这台电脑已安装“开机常驻”，后台服务可能会被系统重新拉起。"
  echo "如需彻底停用，请双击“卸载开机常驻.command”。"
fi

read "REPLY?按回车关闭窗口。"
