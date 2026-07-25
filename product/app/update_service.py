from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import (
    AUTO_UPDATE_ENABLED,
    AUTO_UPDATE_INTERVAL_HOURS,
    DEMO_MODE,
    PRODUCT_DIR,
    RUNTIME_DIR,
    UPDATE_REPOSITORY,
)


STATUS_FILE = RUNTIME_DIR / "update-status.json"
VERSION_FILE = PRODUCT_DIR / "VERSION"
DEFAULT_STATUS = {
    "state": "idle",
    "message": "等待首次检查。",
    "latest_version": "",
    "update_available": False,
    "last_checked_at": "",
    "backup_root": "",
}


class UpdateServiceError(RuntimeError):
    pass


def current_version() -> str:
    if VERSION_FILE.is_file():
        return VERSION_FILE.read_text(encoding="utf-8-sig").strip().lstrip("v")
    from . import __version__

    return __version__


def version_tuple(value: str) -> tuple[int, int, int]:
    normalized = value.strip().lstrip("v").split("+", 1)[0].split("-", 1)[0]
    pieces = normalized.split(".")
    if not 1 <= len(pieces) <= 3 or any(not piece.isdigit() for piece in pieces):
        raise UpdateServiceError(f"GitHub 返回了无效版本号：{value}")
    return tuple(int(piece) for piece in (pieces + ["0", "0"])[:3])


def update_status() -> dict[str, Any]:
    payload: dict[str, Any] = dict(DEFAULT_STATUS)
    if STATUS_FILE.is_file():
        try:
            stored = json.loads(STATUS_FILE.read_text(encoding="utf-8-sig"))
            if isinstance(stored, dict):
                payload.update(stored)
        except (OSError, json.JSONDecodeError):
            payload["state"] = "error"
            payload["message"] = "本机更新状态文件损坏，可重新检查更新。"
    payload.update(
        {
            "current_version": current_version(),
            "repository": UPDATE_REPOSITORY,
            "automatic": AUTO_UPDATE_ENABLED,
            "interval_hours": AUTO_UPDATE_INTERVAL_HOURS,
            "supported": platform.system() == "Windows",
        }
    )
    return payload


def _write_status(**values: Any) -> dict[str, Any]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = update_status()
    payload.update(values)
    temporary = STATUS_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, STATUS_FILE)
    return payload


def check_latest(
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    if "/" not in UPDATE_REPOSITORY:
        raise UpdateServiceError("GitHub 更新仓库格式不正确。")
    url = f"https://api.github.com/repos/{UPDATE_REPOSITORY}/releases/latest"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ai-investment-employee-updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener(request, timeout=20) as response:
            release = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        payload = _write_status(
            state="error",
            message=f"GitHub 更新检查失败：{exc}",
            last_checked_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        return payload

    if not isinstance(release, dict):
        return _write_status(
            state="error",
            message="GitHub 更新接口返回格式不正确。",
            last_checked_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
    latest = str(release.get("tag_name") or "").strip().lstrip("v")
    current = current_version()
    try:
        available = version_tuple(latest) > version_tuple(current)
    except UpdateServiceError as exc:
        return _write_status(
            state="error",
            message=str(exc),
            last_checked_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
    message = f"发现新版本 v{latest}。" if available else "当前已经是最新版本。"
    return _write_status(
        state="available" if available else "current",
        message=message,
        current_version=current,
        latest_version=latest,
        update_available=available,
        release_url=str(release.get("html_url") or ""),
        last_checked_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def windows_update_command(*, automatic: bool = False) -> list[str]:
    system_root = os.getenv("SystemRoot", r"C:\Windows")
    powershell = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    command = [
        str(powershell),
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PRODUCT_DIR / "scripts" / "windows" / "update.ps1"),
    ]
    if automatic:
        command.append("-Automatic")
    return command


def launch_updater(*, automatic: bool = False) -> dict[str, Any]:
    if platform.system() != "Windows":
        raise UpdateServiceError("当前自动覆盖安装仅在 Windows 正式交付版启用。")
    script = PRODUCT_DIR / "scripts" / "windows" / "update.ps1"
    if not script.is_file():
        raise UpdateServiceError("本机缺少 Windows 更新脚本。")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess,
        "DETACHED_PROCESS",
        0,
    )
    subprocess.Popen(
        windows_update_command(automatic=automatic),
        cwd=PRODUCT_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    return _write_status(
        state="queued",
        message="更新程序已经启动；网页会短暂断开，完成后自动恢复。",
    )


async def automatic_update_loop() -> None:
    await asyncio.sleep(120)
    while True:
        try:
            status = await asyncio.to_thread(check_latest)
            if status.get("update_available"):
                await asyncio.to_thread(launch_updater, automatic=True)
                return
        except Exception as exc:
            await asyncio.to_thread(
                _write_status,
                state="error",
                message=f"自动更新检查失败：{str(exc)[:240]}",
            )
        await asyncio.sleep(AUTO_UPDATE_INTERVAL_HOURS * 3600)


def should_run_automatic_loop() -> bool:
    return (
        AUTO_UPDATE_ENABLED
        and not DEMO_MODE
        and platform.system() == "Windows"
    )
