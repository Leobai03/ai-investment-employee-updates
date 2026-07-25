#!/bin/zsh
set -e

cd "$(dirname "$0")"

PYTHON_BIN="python3"
[[ -x ".venv/bin/python" ]] && PYTHON_BIN=".venv/bin/python"

echo ""
echo "天策 AI 投研数字员工｜生成老板交付包"
echo "------------------------------------"
"$PYTHON_BIN" scripts/build_delivery.py

echo ""
echo "交付包位于 dist 文件夹。"
open dist 2>/dev/null || true
read "REPLY?按回车关闭窗口。"

