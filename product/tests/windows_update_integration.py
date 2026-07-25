#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path


PACKAGE_ROOT_NAME = "AI投研数字员工_Update"
SECRET_VALUE = "local-only-test-secret"


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def prepare(install_root: Path, output_dir: Path, target_version: str) -> Path:
    product = install_root / "product"
    current = (product / "VERSION").read_text(encoding="utf-8").strip()
    workspace = product / "投研数字员工"
    write(product / ".env", f"OPENAI_API_KEY={SECRET_VALUE}\n".encode())
    write(workspace / "00_老板投资说明书.md", "Windows 升级前偏好\n".encode("utf-8"))
    write(workspace / "conversations" / "before.md", "Windows 升级前对话\n".encode("utf-8"))
    write(workspace / "reports" / "before.md", "Windows 升级前报告\n".encode("utf-8"))
    database = workspace / "data" / "research.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE update_probe(value TEXT)")
        connection.execute("INSERT INTO update_probe VALUES ('Windows 升级前数据库')")

    replacements = {
        "product/VERSION": f"{target_version}\n".encode(),
        "product/app/__init__.py": (product / "app" / "__init__.py")
        .read_text(encoding="utf-8")
        .replace(current, target_version)
        .encode("utf-8"),
        "product/app/main.py": (product / "app" / "main.py")
        .read_text(encoding="utf-8")
        .replace(f'APP_VERSION = "{current}"', f'APP_VERSION = "{target_version}"')
        .encode("utf-8"),
        "product/scripts/update_core.py": (product / "scripts" / "update_core.py").read_bytes(),
    }
    package_root = output_dir / PACKAGE_ROOT_NAME
    files = []
    for target, data in replacements.items():
        path = package_root / target
        write(path, data)
        files.append(
            {
                "path": target,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {
        "schema_version": 1,
        "version": target_version,
        "files": files,
        "removed_files": [],
    }
    write(
        package_root / "UPDATE_MANIFEST.json",
        json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
    )
    archive_path = output_dir / f"ai-investment-employee-update-v{target_version}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in package_root.rglob("*"):
            if path.is_file():
                archive.write(path, f"{PACKAGE_ROOT_NAME}/{path.relative_to(package_root).as_posix()}")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    archive_path.with_suffix(".zip.sha256").write_text(
        f"{digest}  {archive_path.name}\n",
        encoding="utf-8",
    )
    print(archive_path)
    return archive_path


def verify(install_root: Path, target_version: str) -> None:
    product = install_root / "product"
    workspace = product / "投研数字员工"
    assert (product / "VERSION").read_text(encoding="utf-8-sig").strip() == target_version
    assert SECRET_VALUE in (product / ".env").read_text(encoding="utf-8-sig")
    assert "Windows 升级前偏好" in (workspace / "00_老板投资说明书.md").read_text(encoding="utf-8")
    assert "Windows 升级前对话" in (workspace / "conversations" / "before.md").read_text(encoding="utf-8")
    assert "Windows 升级前报告" in (workspace / "reports" / "before.md").read_text(encoding="utf-8")
    with sqlite3.connect(workspace / "data" / "research.db") as connection:
        assert connection.execute("SELECT value FROM update_probe").fetchone()[0] == "Windows 升级前数据库"
    backups = list((workspace / "backups").glob("update-*-from-v*-to-v*"))
    assert backups
    assert (backups[-1] / "ROLLBACK_STATE.json").is_file()
    assert (backups[-1] / "老板资料升级前快照.zip").is_file()
    print("Windows native update integration passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "verify"))
    parser.add_argument("--install-root", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--target-version", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        if not args.output_dir:
            raise SystemExit("prepare requires --output-dir")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        prepare(args.install_root, args.output_dir, args.target_version)
    else:
        verify(args.install_root, args.target_version)


if __name__ == "__main__":
    main()
