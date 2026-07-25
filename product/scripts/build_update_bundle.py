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
from update_core import MANIFEST_NAME, SCHEMA_VERSION, normalize_target, verify_package


PRODUCT_ROOT = build_delivery.ROOT
INSTALL_ROOT = PRODUCT_ROOT.parent
PLUGIN_ROOT = INSTALL_ROOT / "codex-plugin-marketplace"
VERSION = build_delivery.VERSION
DIST_DIR = PRODUCT_ROOT / "dist"
PACKAGE_ROOT = "AI投研数字员工_Update"
ARCHIVE_NAME = f"ai-investment-employee-update-v{VERSION}.zip"

EXCLUDED_PRODUCT_TOP_LEVEL = {
    ".git",
    ".pytest_cache",
    ".venv",
    "data",
    "dist",
    "runtime",
}
EXCLUDED_NAMES = {".DS_Store", ".env"}
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


def transformed_data(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() in {".cmd", ".ps1"}:
        text = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        return b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8")
    return data


def excluded_common(path: Path) -> bool:
    return (
        path.name in EXCLUDED_NAMES
        or "__pycache__" in path.parts
        or any(path.name.endswith(suffix) for suffix in EXCLUDED_SUFFIXES)
    )


def product_files() -> list[Path]:
    files: list[Path] = []
    for path in PRODUCT_ROOT.rglob("*"):
        if not path.is_file() or excluded_common(path):
            continue
        relative = path.relative_to(PRODUCT_ROOT)
        if relative.parts[0] in EXCLUDED_PRODUCT_TOP_LEVEL:
            continue
        if relative.parts[0] == "投研数字员工":
            if len(relative.parts) < 3 or relative.parts[1] != ".system":
                continue
        files.append(path)
    return sorted(files)


def plugin_files() -> list[Path]:
    return sorted(
        path
        for path in PLUGIN_ROOT.rglob("*")
        if path.is_file() and not excluded_common(path)
    )


def build() -> tuple[Path, Path, dict]:
    products = product_files()
    plugins = plugin_files()
    if not products or not plugins:
        raise RuntimeError("更新包源文件不完整。")

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = DIST_DIR / ARCHIVE_NAME
    checksum_path = archive_path.with_suffix(".zip.sha256")
    archive_path.unlink(missing_ok=True)
    checksum_path.unlink(missing_ok=True)

    files: list[dict[str, object]] = []
    payloads: list[tuple[str, bytes]] = []
    for base_name, base, paths in (
        ("product", PRODUCT_ROOT, products),
        ("codex-plugin-marketplace", PLUGIN_ROOT, plugins),
    ):
        for path in paths:
            relative = path.relative_to(base).as_posix()
            target = normalize_target(f"{base_name}/{relative}")
            data = transformed_data(path)
            digest = hashlib.sha256(data).hexdigest()
            files.append({"path": target, "size_bytes": len(data), "sha256": digest})
            payloads.append((target, data))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "product": "天策 AI 投研数字员工",
        "version": VERSION,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "data_policy": {
            "preserved": [
                "product/.env",
                "product/.venv/",
                "product/runtime/",
                "product/dist/",
                "product/投研数字员工/（除 .system 程序脚本）",
            ],
            "pre_update_snapshot": True,
            "automatic_rollback": True,
        },
        "files": files,
        "removed_files": [],
    }

    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for target, data in payloads:
            build_delivery.write_archive_file(
                archive,
                f"{PACKAGE_ROOT}/{target}",
                data,
            )
        build_delivery.write_archive_file(
            archive,
            f"{PACKAGE_ROOT}/{MANIFEST_NAME}",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{checksum}  {archive_path.name}\n", encoding="utf-8")
    return archive_path, checksum_path, manifest


def verify_archive(archive_path: Path, manifest: dict) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        bad = archive.testzip()
        if bad:
            errors.append(f"ZIP CRC 校验失败：{bad}")
        names = archive.namelist()
        lowered = [name.lower() for name in names]
        forbidden = (
            "/.venv/",
            "/runtime/",
            "/dist/",
            "/conversations/",
            "/reports/",
            "/backups/",
            "/data/research.db",
            "__pycache__",
        )
        for name in lowered:
            if name.endswith("/.env") or any(fragment in name for fragment in forbidden):
                errors.append(f"更新包包含受保护数据：{name}")
        for name in names:
            if name.endswith("/"):
                continue
            data = archive.read(name)
            if re.search(rb"sk-[A-Za-z0-9_-]{20,}", data):
                errors.append(f"更新包检测到疑似 API Key：{name}")

    with tempfile_directory() as extracted:
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extracted)
        try:
            verified = verify_package(extracted / PACKAGE_ROOT)
            if verified["version"] != manifest["version"]:
                errors.append("解压后的更新版本与构建版本不一致。")
        except Exception as exc:
            errors.append(f"解压后更新清单验证失败：{exc}")
    return errors


class tempfile_directory:
    def __enter__(self) -> Path:
        import tempfile

        self._temporary = tempfile.TemporaryDirectory(prefix="ai-research-update-build-")
        return Path(self._temporary.name)

    def __exit__(self, *_: object) -> None:
        self._temporary.cleanup()


def main() -> int:
    try:
        archive_path, checksum_path, manifest = build()
        errors = verify_archive(archive_path, manifest)
    except Exception as exc:
        print(f"✗ 更新包构建失败：{exc}")
        return 1
    if errors:
        archive_path.unlink(missing_ok=True)
        checksum_path.unlink(missing_ok=True)
        for error in errors:
            print(f"✗ {error}")
        return 1
    print(f"✓ 更新包文件：{len(manifest['files'])} 个")
    print("✓ 老板数据库、对话、报告、偏好、密钥和运行目录均未进入更新包")
    print(f"✓ 已生成：{archive_path}")
    print(f"✓ SHA-256：{checksum_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
