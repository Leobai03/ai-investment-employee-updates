#!/bin/zsh
set -e

cd "$(dirname "$0")"
PLIST="$HOME/Library/LaunchAgents/icu.leobai825.ai-research.plist"
TRASH_DIR="$HOME/.Trash"

echo ""
echo "天策 AI 投研数字员工｜卸载开机常驻"
echo "--------------------------------"

launchctl bootout "gui/$UID" "$PLIST" >/dev/null 2>&1 || true

if [[ -f "$PLIST" ]]; then
  mkdir -p "$TRASH_DIR"
  STAMP=$(date +%Y%m%d-%H%M%S)
  mv "$PLIST" "$TRASH_DIR/icu.leobai825.ai-research-$STAMP.plist"
  echo "已关闭开机常驻，并把配置移到废纸篓。"
else
  echo "没有发现开机常驻配置，后台常驻已处于关闭状态。"
fi

for PID_FILE in runtime/app.pid runtime/demo.pid; do
  if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" >/dev/null 2>&1; then
      kill "$PID" >/dev/null 2>&1 || true
    fi
    rm -f "$PID_FILE"
  fi
done

echo "本地资料、对话和报告都保留，没有删除。"
read "REPLY?按回车关闭窗口。"
