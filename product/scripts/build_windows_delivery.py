#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import build_delivery


ROOT = build_delivery.ROOT
PLUGIN_ROOT = ROOT.parent / "codex-plugin-marketplace"
VERSION = build_delivery.VERSION
DIST_DIR = ROOT / "dist"
ARCHIVE_NAME = f"ai-investment-employee-windows-v{VERSION}.zip"
PACKAGE_ROOT = "AI投研数字员工_Windows"

WINDOWS_REQUIRED = {
    "Windows使用说明.md",
    "自动更新与GitHub发布说明.md",
    "Windows_首次配置.cmd",
    "打开AI投研驾驶舱.cmd",
    "Windows_启动研究台.cmd",
    "Windows_停止研究台.cmd",
    "Windows_打开研究台.cmd",
    "Windows_查看运行日志.cmd",
    "Windows_演示研究台.cmd",
    "Windows_系统自检.cmd",
    "Windows_安装开机自启.cmd",
    "Windows_卸载开机自启.cmd",
    "Windows_检查并更新.cmd",
    "scripts/windows/Common.ps1",
    "scripts/windows/setup.ps1",
    "scripts/windows/start.ps1",
    "scripts/windows/stop.ps1",
    "scripts/windows/supervisor.ps1",
    "scripts/windows/install-autostart.ps1",
    "scripts/windows/uninstall-autostart.ps1",
    "scripts/windows/doctor.ps1",
    "scripts/windows/update.ps1",
    "scripts/update_core.py",
}
PLUGIN_REQUIRED = {
    ".agents/plugins/marketplace.json",
    "安装AI投研数字员工_Windows.cmd",
    "scripts/windows/install-plugin.ps1",
    "plugins/ai-investment-employee/.codex-plugin/plugin.json",
    "plugins/ai-investment-employee/skills/ai-investment-employee/SKILL.md",
}


def product_files() -> list[Path]:
    return [
        path
        for path in build_delivery.collect_files()
        if path.suffix.lower() != ".command"
    ]


def plugin_files() -> list[Path]:
    return sorted(
        path
        for path in PLUGIN_ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() != ".command"
        and path.suffix.lower() not in {".pyc", ".log", ".db"}
        and "__pycache__" not in path.parts
        and path.name != ".DS_Store"
    )


def validate(products: list[Path], plugins: list[Path]) -> list[str]:
    errors = build_delivery.validate(build_delivery.collect_files())
    product_names = {path.relative_to(ROOT).as_posix() for path in products}
    plugin_names = {path.relative_to(PLUGIN_ROOT).as_posix() for path in plugins}
    for name in sorted(WINDOWS_REQUIRED - product_names):
        errors.append(f"Windows 产品文件缺失：{name}")
    for name in sorted(PLUGIN_REQUIRED - plugin_names):
        errors.append(f"Windows 插件文件缺失：{name}")

    for base, paths in ((ROOT, products), (PLUGIN_ROOT, plugins)):
        for path in paths:
            data = path.read_bytes()
            for label, pattern in build_delivery.SECRET_PATTERNS:
                if pattern.search(data):
                    errors.append(f"检测到{label}：{path.relative_to(base)}")
    return errors


def add_file(
    archive: zipfile.ZipFile,
    archive_name: str,
    path: Path,
    manifest: list[dict[str, object]],
) -> None:
    data = path.read_bytes()
    if path.suffix.lower() in {".cmd", ".ps1"}:
        text = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        data = b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8")
    build_delivery.write_archive_file(archive, archive_name, data)
    manifest.append(
        {
            "path": archive_name.removeprefix(f"{PACKAGE_ROOT}/"),
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    )


def build(products: list[Path], plugins: list[Path]) -> tuple[Path, Path]:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = DIST_DIR / ARCHIVE_NAME
    checksum_path = archive_path.with_suffix(".zip.sha256")
    archive_path.unlink(missing_ok=True)
    checksum_path.unlink(missing_ok=True)

    manifest_files: list[dict[str, object]] = []
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        windows_guide = ROOT / "Windows使用说明.md"
        add_file(
            archive,
            f"{PACKAGE_ROOT}/先看这里_Windows安装说明.md",
            windows_guide,
            manifest_files,
        )
        for path in products:
            relative = path.relative_to(ROOT).as_posix()
            add_file(
                archive,
                f"{PACKAGE_ROOT}/product/{relative}",
                path,
                manifest_files,
            )
        for path in plugins:
            relative = path.relative_to(PLUGIN_ROOT).as_posix()
            add_file(
                archive,
                f"{PACKAGE_ROOT}/codex-plugin-marketplace/{relative}",
                path,
                manifest_files,
            )

        manifest = {
            "product": "天策 AI 投研数字员工",
            "version": VERSION,
            "platform": "Windows 10/11",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "first_step": "解压后打开 product，双击 Windows_首次配置.cmd",
            "privacy_exclusions": [
                ".env 与 API Key",
                "真实 SQLite 数据库",
                "历史对话、报告、导出与备份",
                "运行日志、PID、截图、虚拟环境和缓存",
                "Mac 专用 .command 文件",
            ],
            "files": manifest_files,
        }
        build_delivery.write_archive_file(
            archive,
            f"{PACKAGE_ROOT}/DELIVERY_MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{checksum}  {archive_path.name}\n", encoding="utf-8")
    return archive_path, checksum_path


def verify(archive_path: Path) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        bad = archive.testzip()
        if bad:
            errors.append(f"ZIP CRC 校验失败：{bad}")
        names = archive.namelist()
        if any(name.lower().endswith(".command") for name in names):
            errors.append("Windows 交付包仍包含 Mac .command 文件。")
        forbidden = (
            "/.venv/",
            "/runtime/",
            "/__pycache__/",
            "/data/research.db",
            "/conversations/",
            "/reports/",
            "/backups/",
        )
        for name in names:
            normalized = f"/{name.lower()}"
            if normalized.endswith("/.env"):
                errors.append(f"交付包包含本机配置：{name}")
            if any(fragment.lower() in normalized for fragment in forbidden):
                errors.append(f"交付包包含运行数据或缓存：{name}")
        for name in names:
            if name.endswith("/"):
                continue
            data = archive.read(name)
            if re.search(rb"sk-[A-Za-z0-9_-]{20,}", data):
                errors.append(f"交付包检测到疑似 API Key：{name}")
    return errors


def main() -> int:
    products = product_files()
    plugins = plugin_files()
    errors = validate(products, plugins)
    if errors:
        for error in errors:
            print(f"✗ {error}")
        return 1
    print(f"✓ Windows 源文件检查通过：产品 {len(products)} 个，插件 {len(plugins)} 个")

    archive_path, checksum_path = build(products, plugins)
    errors = verify(archive_path)
    if errors:
        archive_path.unlink(missing_ok=True)
        checksum_path.unlink(missing_ok=True)
        for error in errors:
            print(f"✗ {error}")
        return 1
    print(f"✓ 已生成：{archive_path}")
    print(f"✓ SHA-256：{checksum_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
