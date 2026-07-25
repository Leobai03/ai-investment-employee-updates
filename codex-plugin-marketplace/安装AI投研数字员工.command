#!/bin/zsh
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

if command -v codex >/dev/null 2>&1; then
  CODEX="$(command -v codex)"
elif [ -x "/Applications/ChatGPT.app/Contents/Resources/codex" ]; then
  CODEX="/Applications/ChatGPT.app/Contents/Resources/codex"
else
  echo "没有找到 Codex。请先安装并打开 Codex 桌面版，再重新运行本文件。"
  read -r "?按回车键退出。"
  exit 1
fi

echo "正在添加 AI 投研数字员工插件源……"
"$CODEX" plugin marketplace add "$ROOT"

echo "正在安装插件……"
"$CODEX" plugin add ai-investment-employee@boss-investment

echo ""
echo "安装完成。"
echo "请重新打开 Codex，新建一个任务，然后输入："
echo "初始化我的投研数字员工。我的重点市场是 A 股和港股，请一次只问我一个问题。"
echo "初始化后，工作区会生成“打开AI投研驾驶舱.command”。"
echo ""
read -r "?按回车键退出。"
