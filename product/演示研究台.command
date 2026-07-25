#!/bin/zsh
set -e
cd "$(dirname "$0")"
mkdir -p runtime data

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, openai' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi

if [[ -f runtime/demo.pid ]] && kill -0 "$(cat runtime/demo.pid)" >/dev/null 2>&1; then
  open http://127.0.0.1:8766
  exit 0
fi

AI_RESEARCH_DEMO=1 AI_RESEARCH_PORT=8766 AI_RESEARCH_DB="$PWD/data/demo.db" nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8766 > runtime/demo.log 2>&1 &
echo $! > runtime/demo.pid
for i in {1..40}; do
  if curl -fsS http://127.0.0.1:8766/api/health >/dev/null 2>&1; then
    open http://127.0.0.1:8766
    echo "演示版已打开。注意：演示版不检索实时市场数据。"
    exit 0
  fi
  sleep 0.5
done
echo "演示版启动失败，请查看 runtime/demo.log。"

