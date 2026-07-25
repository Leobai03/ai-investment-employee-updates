#!/bin/zsh
set -e

cd "$(dirname "$0")"

PYTHON_BIN="python3"
[[ -x ".venv/bin/python" ]] && PYTHON_BIN=".venv/bin/python"

echo ""
echo "天策 AI 投研数字员工｜交付前自检"
echo "--------------------------------"

"$PYTHON_BIN" scripts/build_delivery.py --check-only
"$PYTHON_BIN" -m compileall -q app

if [[ -x ".venv/bin/pytest" ]]; then
  .venv/bin/pytest -q
else
  echo "△ 当前环境没有 pytest，已跳过自动化测试；开发机交付前必须安装 requirements-dev.txt 后再跑。"
fi

if command -v node >/dev/null 2>&1; then
  node --check app/static/app.js
else
  echo "△ 当前电脑没有 Node.js，已跳过 JavaScript 语法检查。"
fi

echo ""
echo "自检完成。"
read "REPLY?按回车关闭窗口。"

