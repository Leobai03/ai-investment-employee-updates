from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


PRODUCT_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = Path(os.getenv("AI_RESEARCH_WORKSPACE", PRODUCT_DIR / "投研数字员工"))
DATA_DIR = WORKSPACE_DIR / "data"
RUNTIME_DIR = PRODUCT_DIR / "runtime"
STATIC_DIR = Path(__file__).resolve().parent / "static"
DB_PATH = Path(os.getenv("AI_RESEARCH_DB", DATA_DIR / "research.db"))
REPORTS_DIR = WORKSPACE_DIR / "reports"
CONVERSATIONS_DIR = WORKSPACE_DIR / "conversations"
EXPORTS_DIR = WORKSPACE_DIR / "exports"
BACKUPS_DIR = WORKSPACE_DIR / "backups"


def load_local_env() -> None:
    """Load a tiny .env file without adding another dependency.

    Existing process variables always win. Values may be quoted, and comment or
    malformed lines are ignored.
    """

    env_path = PRODUCT_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()

APP_HOST = os.getenv("AI_RESEARCH_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("AI_RESEARCH_PORT", "8765"))
LAN_ACCESS_TOKEN = os.getenv("AI_RESEARCH_LAN_TOKEN", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
DEMO_MODE = os.getenv("AI_RESEARCH_DEMO", "0") == "1"
RESEARCH_ENGINE_DEFAULT = os.getenv("AI_RESEARCH_ENGINE", "auto").strip().lower()
CODEX_MODEL = os.getenv("CODEX_MODEL", "").strip()
AUTO_UPDATE_ENABLED = os.getenv("AUTO_UPDATE_ENABLED", "1").strip() != "0"
AUTO_UPDATE_INTERVAL_HOURS = max(
    1,
    int(os.getenv("AUTO_UPDATE_INTERVAL_HOURS", "6")),
)
UPDATE_REPOSITORY = (
    os.getenv("UPDATE_REPOSITORY", "").strip()
    or "Leobai03/ai-investment-employee-updates"
)


def discover_codex_bin(*, platform_name: str = sys.platform) -> str:
    configured = os.getenv("CODEX_BIN", "").strip()
    if configured:
        return configured

    found = shutil.which("codex") or shutil.which("codex.exe") or shutil.which("codex.cmd")
    if found:
        return found

    if platform_name.startswith("win"):
        appdata = os.getenv("APPDATA", "").strip()
        if appdata:
            npm_wrapper = Path(appdata) / "npm" / "codex.cmd"
            if npm_wrapper.exists():
                return str(npm_wrapper)
        return ""

    if platform_name == "darwin":
        bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
        if bundled.exists():
            return str(bundled)
    return ""


def codex_app_server_command(
    executable: str,
    *,
    platform_name: str = sys.platform,
    comspec: str | None = None,
) -> list[str]:
    if not executable:
        return []
    arguments = [executable, "app-server", "--listen", "stdio://"]
    if platform_name.startswith("win") and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        shell = comspec or os.getenv("COMSPEC", "") or r"C:\Windows\System32\cmd.exe"
        return [shell, "/d", "/s", "/c", subprocess.list2cmdline(arguments)]
    return arguments


CODEX_BIN = discover_codex_bin()
FIRST_SETUP_ENTRY = "Windows_首次配置.cmd" if os.name == "nt" else "首次配置.command"


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("daily", "company", "questions", "reviews", "scheduled"):
        (REPORTS_DIR / name).mkdir(parents=True, exist_ok=True)
