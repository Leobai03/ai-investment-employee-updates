#!/bin/zsh
set -e

cd "$(dirname "$0")"
mkdir -p runtime "$HOME/Library/LaunchAgents"

echo ""
echo "天策 AI 投研数字员工｜安装开机常驻"
echo "--------------------------------"

if [[ ! -d .venv ]] || ! .venv/bin/python -c 'import fastapi, uvicorn, openai' >/dev/null 2>&1; then
  echo "请先双击“启动研究台.command”，完成运行环境安装。"
  read "REPLY?按回车关闭窗口。"
  exit 1
fi

ROOT="$PWD"
PLIST="$HOME/Library/LaunchAgents/icu.leobai825.ai-research.plist"

/usr/bin/python3 - "$ROOT" "$PLIST" <<'PY'
import plistlib
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
plist = Path(sys.argv[2])
payload = {
    "Label": "icu.leobai825.ai-research",
    "ProgramArguments": [
        str(root / ".venv" / "bin" / "python"),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
    ],
    "WorkingDirectory": str(root),
    "RunAtLoad": True,
    "KeepAlive": True,
    "ProcessType": "Background",
    "StandardOutPath": str(root / "runtime" / "launchagent.log"),
    "StandardErrorPath": str(root / "runtime" / "launchagent.log"),
}
with plist.open("wb") as handle:
    plistlib.dump(payload, handle)
PY

chmod 600 "$PLIST"
launchctl bootout "gui/$UID" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$UID" "$PLIST"
launchctl kickstart -k "gui/$UID/icu.leobai825.ai-research"

echo ""
echo "安装完成。以后登录这台 Mac 后，研究台会在后台自动运行。"
echo "网页地址：http://127.0.0.1:8765"
echo "关闭浏览器不会停止任务；关机或睡眠期间任务不会运行。"
open http://127.0.0.1:8765
read "REPLY?按回车关闭窗口。"
