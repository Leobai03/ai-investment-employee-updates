#!/bin/zsh
cd "$(dirname "$0")"
if [[ -f runtime/app.log ]]; then
  tail -n 120 runtime/app.log
else
  echo "目前还没有运行日志。"
fi
echo ""
read "REPLY?按回车关闭窗口。"

