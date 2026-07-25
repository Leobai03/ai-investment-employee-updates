#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT_ROOT / "scripts"))

from update_core import apply_update, rollback_update, verify_package  # noqa: E402


SECRET = "old-install-local-secret"
PREFERENCE = "升级前只研究公开信息，重点关注 A 股和港股。"
CONVERSATION = "升级前老板与数字员工的历史对话。"
REPORT = "升级前公司研究报告。"
DATABASE_VALUE = "升级前数据库记录"


def find_product_root(extracted: Path) -> Path:
    candidates = [
        path.parent.parent
        for path in extracted.rglob("app/main.py")
        if path.parent.name == "app" and path.parent.parent.name == "product"
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"旧版交付包 product 目录数量异常：{len(candidates)}")
    return candidates[0]


def seed_owner_data(product: Path) -> Path:
    workspace = product / "投研数字员工"
    (product / ".env").write_text(f"OPENAI_API_KEY={SECRET}\n", encoding="utf-8")
    (workspace / "00_老板投资说明书.md").write_text(PREFERENCE, encoding="utf-8")
    for relative, value in (
        ("conversations/before-upgrade.md", CONVERSATION),
        ("reports/before-upgrade.md", REPORT),
    ):
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    database = workspace / "data" / "research.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    database.unlink(missing_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE update_probe(value TEXT)")
        connection.execute("INSERT INTO update_probe VALUES (?)", (DATABASE_VALUE,))
    return workspace


def assert_owner_data(product: Path) -> None:
    workspace = product / "投研数字员工"
    assert SECRET in (product / ".env").read_text(encoding="utf-8-sig")
    assert (workspace / "00_老板投资说明书.md").read_text(encoding="utf-8") == PREFERENCE
    assert (workspace / "conversations" / "before-upgrade.md").read_text(encoding="utf-8") == CONVERSATION
    assert (workspace / "reports" / "before-upgrade.md").read_text(encoding="utf-8") == REPORT
    with sqlite3.connect(workspace / "data" / "research.db") as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT value FROM update_probe").fetchone()[0] == DATABASE_VALUE


def run(old_archive: Path, update_archive: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="ai-research-package-upgrade-") as temporary:
        root = Path(temporary)
        old_root = root / "old"
        update_root = root / "update"
        with zipfile.ZipFile(old_archive) as archive:
            archive.extractall(old_root)
        with zipfile.ZipFile(update_archive) as archive:
            archive.extractall(update_root)

        product = find_product_root(old_root)
        install_root = product.parent
        package_root = update_root / "AI投研数字员工_Update"
        manifest = verify_package(package_root)
        target_version = str(manifest["version"])
        version_path = product / "VERSION"
        previous_version = (
            version_path.read_text(encoding="utf-8-sig").strip()
            if version_path.exists()
            else "0.10.0"
        )
        previous_init = (product / "app" / "__init__.py").read_text(encoding="utf-8")
        seed_owner_data(product)

        result = apply_update(
            package_root,
            install_root,
            current_version=previous_version,
        )
        assert (product / "VERSION").read_text(encoding="utf-8-sig").strip() == target_version
        assert_owner_data(product)
        backup_root = Path(str(result["backup_root"]))
        assert (backup_root / "ROLLBACK_STATE.json").is_file()
        assert (backup_root / "老板资料升级前快照.zip").is_file()

        (product / ".env").write_text("OPENAI_API_KEY=temporary-change\n", encoding="utf-8")
        with sqlite3.connect(product / "投研数字员工" / "data" / "research.db") as connection:
            connection.execute("UPDATE update_probe SET value='temporary-change'")
        rollback_update(backup_root, install_root, restore_userdata=True)
        assert_owner_data(product)
        if previous_version == "0.10.0":
            assert not version_path.exists()
        else:
            assert version_path.read_text(encoding="utf-8-sig").strip() == previous_version
        assert (product / "app" / "__init__.py").read_text(encoding="utf-8") == previous_init

        return {
            "ok": True,
            "from_version": previous_version,
            "to_version": target_version,
            "owner_data_preserved": True,
            "rollback_verified": True,
            "update_files": len(manifest["files"]),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="真实交付包跨版本升级与回滚演练。")
    parser.add_argument("--old-archive", required=True, type=Path)
    parser.add_argument("--update-archive", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.old_archive, args.update_archive), ensure_ascii=False))


if __name__ == "__main__":
    main()
