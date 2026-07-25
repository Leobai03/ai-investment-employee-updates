#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = 1
MANIFEST_NAME = "UPDATE_MANIFEST.json"
ALLOWED_TARGET_ROOTS = {"product", "codex-plugin-marketplace"}
PROTECTED_PRODUCT_NAMES = {
    ".env",
    ".git",
    ".venv",
    "data",
    "dist",
    "runtime",
}
PROTECTED_WORKSPACE = "投研数字员工"


class UpdateError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_tuple(value: str) -> tuple[int, int, int]:
    normalized = value.strip().lstrip("v").split("+", 1)[0].split("-", 1)[0]
    pieces = normalized.split(".")
    if not 1 <= len(pieces) <= 3 or any(not piece.isdigit() for piece in pieces):
        raise UpdateError(f"无效版本号：{value}")
    return tuple(int(piece) for piece in (pieces + ["0", "0"])[:3])


def normalize_target(value: str) -> str:
    raw = value.replace("\\", "/").strip("/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise UpdateError(f"更新目标路径不安全：{value}")
    if path.parts[0] not in ALLOWED_TARGET_ROOTS:
        raise UpdateError(f"更新目标不在允许目录：{value}")
    if path.parts[0] == "product":
        if len(path.parts) == 1:
            raise UpdateError("更新目标不能是整个 product 目录。")
        first = path.parts[1]
        if first in PROTECTED_PRODUCT_NAMES:
            raise UpdateError(f"更新包试图覆盖受保护数据：{value}")
        if first == PROTECTED_WORKSPACE:
            if len(path.parts) < 4 or path.parts[2] != ".system":
                raise UpdateError(f"更新包试图覆盖老板长期资料：{value}")
    return path.as_posix()


def load_manifest(package_root: Path) -> dict[str, Any]:
    manifest_path = package_root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise UpdateError(f"更新包缺少 {MANIFEST_NAME}。")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError(f"更新清单无法读取：{exc}") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise UpdateError(
            f"更新清单版本不兼容：{manifest.get('schema_version')}，当前只支持 {SCHEMA_VERSION}。"
        )
    version_tuple(str(manifest.get("version") or ""))
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise UpdateError("更新清单没有程序文件。")
    return manifest


def verify_package(package_root: Path) -> dict[str, Any]:
    package_root = package_root.resolve()
    manifest = load_manifest(package_root)
    declared: set[str] = set()
    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            raise UpdateError("更新文件清单格式错误。")
        target = normalize_target(str(entry.get("path") or ""))
        if target in declared:
            raise UpdateError(f"更新文件重复：{target}")
        declared.add(target)
        source = package_root / Path(target)
        if not source.is_file():
            raise UpdateError(f"更新包缺少文件：{target}")
        expected = str(entry.get("sha256") or "").lower()
        if len(expected) != 64 or sha256_file(source) != expected:
            raise UpdateError(f"更新文件校验失败：{target}")

    removed = manifest.get("removed_files") or []
    if not isinstance(removed, list):
        raise UpdateError("removed_files 必须是数组。")
    for target in removed:
        normalized = normalize_target(str(target))
        if normalized in declared:
            raise UpdateError(f"文件不能同时更新和删除：{normalized}")

    actual = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and path.name != MANIFEST_NAME
    }
    extras = sorted(actual - declared)
    if extras:
        raise UpdateError(f"更新包包含未声明文件：{extras[0]}")
    missing = sorted(declared - actual)
    if missing:
        raise UpdateError(f"更新清单文件缺失：{missing[0]}")
    return manifest


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.update-{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _database_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source, timeout=30) as source_conn:
        with sqlite3.connect(target) as target_conn:
            source_conn.backup(target_conn)
            result = target_conn.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                raise UpdateError("升级前数据库备份完整性检查失败。")


def _snapshot_userdata(product_root: Path, backup_root: Path) -> dict[str, Any]:
    archive_path = backup_root / "老板资料升级前快照.zip"
    workspace = product_root / PROTECTED_WORKSPACE
    database = workspace / "data" / "research.db"
    database_copy = backup_root / "userdata" / "research.db"
    if database.is_file():
        _database_backup(database, database_copy)

    recorded: list[str] = []
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        env_file = product_root / ".env"
        if env_file.is_file():
            archive.write(env_file, "product/.env")
            recorded.append("product/.env")

        if workspace.is_dir():
            for path in sorted(workspace.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(workspace)
                if relative.parts and relative.parts[0] in {"backups", ".system"}:
                    continue
                if relative.as_posix() in {
                    "data/research.db",
                    "data/research.db-shm",
                    "data/research.db-wal",
                }:
                    continue
                arcname = f"product/{PROTECTED_WORKSPACE}/{relative.as_posix()}"
                archive.write(path, arcname)
                recorded.append(arcname)
        if database_copy.is_file():
            archive.write(database_copy, f"product/{PROTECTED_WORKSPACE}/data/research.db")
            recorded.append(f"product/{PROTECTED_WORKSPACE}/data/research.db")

    if not archive_path.is_file():
        raise UpdateError("无法生成升级前用户资料快照。")
    return {
        "archive": str(archive_path),
        "sha256": sha256_file(archive_path),
        "files": len(recorded),
        "database_backed_up": database_copy.is_file(),
    }


def create_snapshot(
    install_root: Path,
    manifest: dict[str, Any],
    *,
    current_version: str,
) -> tuple[Path, dict[str, Any]]:
    install_root = install_root.resolve()
    product_root = install_root / "product"
    backup_parent = product_root / PROTECTED_WORKSPACE / "backups"
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    target_version = str(manifest["version"])
    backup_root = backup_parent / (
        f"update-{stamp}-from-v{current_version}-to-v{target_version}"
    )
    if backup_root.exists():
        raise UpdateError(f"升级备份目录已存在：{backup_root}")
    files_root = backup_root / "program-files"
    files_root.mkdir(parents=True, exist_ok=False)

    backed_up: list[str] = []
    originally_missing: list[str] = []
    targets = [str(entry["path"]) for entry in manifest["files"]]
    targets.extend(str(item) for item in (manifest.get("removed_files") or []))
    for raw_target in targets:
        target = normalize_target(raw_target)
        source = install_root / Path(target)
        if source.is_file():
            destination = files_root / Path(target)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            backed_up.append(target)
        elif source.exists():
            raise UpdateError(f"更新目标不是普通文件：{target}")
        else:
            originally_missing.append(target)

    userdata = _snapshot_userdata(product_root, backup_root)
    state = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "from_version": current_version,
        "to_version": target_version,
        "install_root": str(install_root),
        "backed_up": backed_up,
        "originally_missing": originally_missing,
        "userdata": userdata,
    }
    (backup_root / "ROLLBACK_STATE.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return backup_root, state


def apply_update(
    package_root: Path,
    install_root: Path,
    *,
    current_version: str,
    allow_downgrade: bool = False,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    install_root = install_root.resolve()
    manifest = verify_package(package_root)
    target_version = str(manifest["version"])
    if not allow_downgrade and version_tuple(target_version) <= version_tuple(current_version):
        raise UpdateError(
            f"目标版本 v{target_version} 不高于当前 v{current_version}，已拒绝覆盖。"
        )

    backup_root, _ = create_snapshot(
        install_root,
        manifest,
        current_version=current_version,
    )
    try:
        for entry in manifest["files"]:
            target = normalize_target(str(entry["path"]))
            _atomic_copy(package_root / Path(target), install_root / Path(target))
        for raw_target in manifest.get("removed_files") or []:
            target = normalize_target(str(raw_target))
            path = install_root / Path(target)
            if path.is_dir():
                raise UpdateError(f"更新器不自动删除目录：{target}")
            path.unlink(missing_ok=True)
    except Exception:
        rollback_update(backup_root, install_root, restore_userdata=True)
        raise

    result = {
        "ok": True,
        "from_version": current_version,
        "to_version": target_version,
        "backup_root": str(backup_root),
        "files_updated": len(manifest["files"]),
        "files_removed": len(manifest.get("removed_files") or []),
    }
    (backup_root / "APPLY_RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def rollback_update(
    backup_root: Path,
    install_root: Path,
    *,
    restore_userdata: bool,
) -> dict[str, Any]:
    backup_root = backup_root.resolve()
    install_root = install_root.resolve()
    state_path = backup_root / "ROLLBACK_STATE.json"
    if not state_path.is_file():
        raise UpdateError("回滚状态文件不存在。")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    expected_root = Path(str(state.get("install_root") or "")).resolve()
    if expected_root != install_root:
        raise UpdateError("回滚目标与升级时安装目录不一致。")

    files_root = backup_root / "program-files"
    for target in state.get("backed_up") or []:
        normalized = normalize_target(str(target))
        source = files_root / Path(normalized)
        if not source.is_file():
            raise UpdateError(f"回滚备份缺少程序文件：{normalized}")
        _atomic_copy(source, install_root / Path(normalized))
    for target in state.get("originally_missing") or []:
        normalized = normalize_target(str(target))
        path = install_root / Path(normalized)
        if path.is_dir():
            raise UpdateError(f"回滚器不自动删除目录：{normalized}")
        path.unlink(missing_ok=True)

    userdata_restored = False
    if restore_userdata:
        userdata = state.get("userdata") or {}
        archive_path = Path(str(userdata.get("archive") or ""))
        expected_hash = str(userdata.get("sha256") or "")
        if not archive_path.is_file() or sha256_file(archive_path) != expected_hash:
            raise UpdateError("用户资料回滚快照校验失败。")
        with tempfile.TemporaryDirectory(prefix="ai-research-rollback-") as temporary:
            extracted = Path(temporary)
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extracted)
            for source in sorted((extracted / "product").rglob("*")):
                if not source.is_file():
                    continue
                relative = source.relative_to(extracted)
                target = install_root / relative
                if relative.as_posix() == "product/.env" or relative.parts[1] == PROTECTED_WORKSPACE:
                    _atomic_copy(source, target)
                else:
                    raise UpdateError(f"用户资料快照包含越界文件：{relative}")
        userdata_restored = True

    result = {
        "ok": True,
        "restored_version": state.get("from_version"),
        "backup_root": str(backup_root),
        "userdata_restored": userdata_restored,
    }
    (backup_root / "ROLLBACK_RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 投研数字员工安全更新核心。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--package-root", required=True, type=Path)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--package-root", required=True, type=Path)
    apply_parser.add_argument("--install-root", required=True, type=Path)
    apply_parser.add_argument("--current-version", required=True)
    apply_parser.add_argument("--allow-downgrade", action="store_true")

    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("--backup-root", required=True, type=Path)
    rollback_parser.add_argument("--install-root", required=True, type=Path)
    rollback_parser.add_argument("--restore-userdata", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "verify":
            manifest = verify_package(args.package_root)
            _print_result(
                {
                    "ok": True,
                    "version": manifest["version"],
                    "files": len(manifest["files"]),
                }
            )
        elif args.command == "apply":
            _print_result(
                apply_update(
                    args.package_root,
                    args.install_root,
                    current_version=args.current_version,
                    allow_downgrade=args.allow_downgrade,
                )
            )
        else:
            _print_result(
                rollback_update(
                    args.backup_root,
                    args.install_root,
                    restore_userdata=args.restore_userdata,
                )
            )
        return 0
    except (UpdateError, OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())

