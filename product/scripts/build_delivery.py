#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.11.1"
DIST_DIR = ROOT / "dist"
ARCHIVE_NAME = f"AI投研数字员工_v{VERSION}_老板交付.zip"

REQUIRED_FILES = (
    "README.md",
    "老板使用说明.md",
    "Windows使用说明.md",
    "自动更新与GitHub发布说明.md",
    "交付验收清单.md",
    "最终交付验收报告.md",
    "OPEN_SOURCE_PROVENANCE.md",
    "requirements.txt",
    "VERSION",
    "启动研究台.command",
    "首次配置.command",
    "安装开机常驻.command",
    "停止研究台.command",
    "Windows_首次配置.cmd",
    "Windows_启动研究台.cmd",
    "Windows_停止研究台.cmd",
    "Windows_系统自检.cmd",
    "Windows_安装开机自启.cmd",
    "Windows_卸载开机自启.cmd",
    "Windows_检查并更新.cmd",
    "scripts/windows/Common.ps1",
    "scripts/windows/setup.ps1",
    "scripts/windows/supervisor.ps1",
    "scripts/windows/update.ps1",
    "scripts/update_core.py",
    "scripts/build_update_bundle.py",
    "app/main.py",
    "app/data_sources.py",
    "app/source_quality.py",
    "投研数字员工/00_老板投资说明书.md",
    "投研数字员工/01_自选公司.md",
    "投研数字员工/03_研究原则.md",
    "投研数字员工/04_决策日志.md",
    "投研数字员工/06_老板纠正与反馈.md",
)

EXCLUDED_TOP_LEVEL = {
    ".git",
    ".pytest_cache",
    ".venv",
    "dist",
    "runtime",
}
EXCLUDED_WORKSPACE_DIRS = {
    "投研数字员工/backups",
    "投研数字员工/conversations",
    "投研数字员工/data",
    "投研数字员工/exports",
    "投研数字员工/reports",
    "投研数字员工/sources",
}
EXCLUDED_SUFFIXES = {
    ".db",
    ".db-shm",
    ".db-wal",
    ".log",
    ".pid",
    ".pyc",
    ".sqlite",
    ".sqlite3",
}
SECRET_PATTERNS = (
    ("OpenAI API Key", re.compile(rb"sk-[A-Za-z0-9_-]{20,}")),
    ("私钥", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)


def excluded(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    parts = relative.parts
    if not parts:
        return True
    if parts[0] in EXCLUDED_TOP_LEVEL:
        return True
    if path.name in {".env", ".DS_Store"}:
        return True
    if "__pycache__" in parts:
        return True
    posix = relative.as_posix()
    if any(posix == item or posix.startswith(f"{item}/") for item in EXCLUDED_WORKSPACE_DIRS):
        return True
    if any(path.name.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return True
    return False


def collect_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not excluded(path)
    )


def validate(files: list[Path]) -> list[str]:
    errors: list[str] = []
    available = {path.relative_to(ROOT).as_posix() for path in files}
    for required in REQUIRED_FILES:
        if required not in available:
            errors.append(f"缺少交付文件：{required}")

    for path in files:
        try:
            data = path.read_bytes()
        except OSError as exc:
            errors.append(f"无法读取：{path.relative_to(ROOT)}（{exc}）")
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(data):
                errors.append(f"检测到{label}：{path.relative_to(ROOT)}")

    main_text = (ROOT / "app/main.py").read_text(encoding="utf-8")
    init_text = (ROOT / "app/__init__.py").read_text(encoding="utf-8")
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    if f'APP_VERSION = "{VERSION}"' not in main_text:
        errors.append("app/main.py 版本号与打包版本不一致。")
    if f'__version__ = "{VERSION}"' not in init_text:
        errors.append("app/__init__.py 版本号与打包版本不一致。")
    if f"v{VERSION.rsplit('.', 1)[0]}" not in readme_text:
        errors.append("README 标题版本与打包版本不一致。")
    return errors


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_archive_file(
    archive: zipfile.ZipFile,
    archive_name: str,
    data: bytes,
    *,
    mode: int = 0o644,
) -> None:
    info = zipfile.ZipInfo(
        archive_name,
        date_time=datetime.now().timetuple()[:6],
    )
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (mode & 0xFFFF) << 16
    archive.writestr(info, data)


def build_archive(files: list[Path]) -> tuple[Path, Path]:
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
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            write_archive_file(
                archive,
                f"AI投研数字员工/{relative}",
                data,
                mode=stat.S_IMODE(path.stat().st_mode),
            )
            manifest_files.append(
                {"path": relative, "size_bytes": len(data), "sha256": digest(data)}
            )

        manifest = {
            "product": "天策 AI 投研数字员工",
            "version": VERSION,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "personalized_memory_included": [
                "老板投资说明书",
                "自选公司",
                "研究原则",
                "决策日志",
                "老板纠正与反馈",
            ],
            "privacy_exclusions": [
                ".env 与 API Key",
                "真实 SQLite 数据库",
                "历史对话与报告",
                "备份、导出、日志、PID、截图",
                "虚拟环境、缓存和编译产物",
            ],
            "files": manifest_files,
        }
        write_archive_file(
            archive,
            "AI投研数字员工/DELIVERY_MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    archive_digest = digest(archive_path.read_bytes())
    checksum_path.write_text(
        f"{archive_digest}  {archive_path.name}\n",
        encoding="utf-8",
    )
    return archive_path, checksum_path


def verify_archive(archive_path: Path) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        bad_file = archive.testzip()
        if bad_file:
            errors.append(f"ZIP CRC 校验失败：{bad_file}")
        infos = archive.infolist()
        names = [info.filename for info in infos]
        forbidden_fragments = (
            "/.venv/",
            "/runtime/",
            "/conversations/",
            "/reports/",
            "/backups/",
            "/exports/",
            "/data/research.db",
            "__pycache__",
        )
        for name in names:
            if name.endswith("/.env") or any(
                fragment in name for fragment in forbidden_fragments
            ):
                errors.append(f"交付包包含不应打包的文件：{name}")
        for info in infos:
            if info.filename.endswith(".command"):
                mode = (info.external_attr >> 16) & 0xFFFF
                if not mode & 0o111:
                    errors.append(f"交付脚本丢失可执行权限：{info.filename}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="构建无密钥、无真实数据库的老板交付包。")
    parser.add_argument("--check-only", action="store_true", help="只检查，不生成 ZIP。")
    args = parser.parse_args()

    files = collect_files()
    errors = validate(files)
    if errors:
        for error in errors:
            print(f"✗ {error}")
        return 1
    print(f"✓ 交付源文件检查通过：{len(files)} 个文件")
    print("✓ 未发现 API Key、私钥、真实数据库、历史对话或报告进入候选文件")
    if args.check_only:
        return 0

    archive_path, checksum_path = build_archive(files)
    errors = verify_archive(archive_path)
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
