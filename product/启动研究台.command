#!/bin/zsh
set -e

cd "$(dirname "$0")"
mkdir -p runtime data

echo ""
echo "天策 AI 投研数字员工｜正在启动"
echo "--------------------------------"

if ! command -v python3 >/dev/null 2>&1; then
  echo "没有找到 Python 3。请先安装 Python 3.11 或更高版本。"
  read "REPLY?按回车关闭窗口。"
  exit 1
fi

PY_OK=$(python3 - <<'PY'
import sys
print("yes" if sys.version_info >= (3, 11) else "no")
PY
)
if [[ "$PY_OK" != "yes" ]]; then
  echo "Python 版本太旧，请安装 Python 3.11 或更高版本。"
  read "REPLY?按回车关闭窗口。"
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "第一次启动：正在创建独立运行环境…"
  python3 -m venv .venv
fi

if ! .venv/bin/python -c 'import fastapi, uvicorn, openai' >/dev/null 2>&1; then
  echo "第一次启动：正在安装必要组件，通常需要 1—3 分钟…"
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

if [[ ! -f .env ]]; then
  echo "提示：尚未生成双引擎配置。"
  echo "如果 Codex 已使用 ChatGPT 登录，网页仍可直接调用订阅引擎；建议稍后运行“首次配置.command”。"
fi

if [[ -f runtime/app.pid ]] && kill -0 "$(cat runtime/app.pid)" >/dev/null 2>&1; then
  echo "研究台已经在运行，正在打开网页…"
else
  echo "正在启动本地网页…"
  nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 > runtime/app.log 2>&1 &
  echo $! > runtime/app.pid
fi

for i in {1..40}; do
  if curl -fsS http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
    open http://127.0.0.1:8765
    echo "启动成功。网页地址：http://127.0.0.1:8765"
    echo "这个终端窗口现在可以关闭，研究台会继续运行。"
    exit 0
  fi
  sleep 0.5
done

echo "启动没有成功。请双击“查看运行日志.command”查看原因。"
read "REPLY?按回车关闭窗口。"
exit 1
