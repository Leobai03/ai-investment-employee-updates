from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT_ROOT / "scripts"))

from update_core import (  # noqa: E402
    UpdateError,
    apply_update,
    rollback_update,
    verify_package,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_install(tmp_path: Path) -> Path:
    install = tmp_path / "AI投研数字员工_Windows"
    _write(install / "product" / "VERSION", "0.10.0\n")
    _write(install / "product" / "app" / "program.txt", "old program")
    _write(install / "product" / "scripts" / "update_core.py", "old updater")
    _write(
        install / "codex-plugin-marketplace" / "plugins" / "plugin.txt",
        "old plugin",
    )
    _write(install / "product" / ".env", "OPENAI_API_KEY=local-secret\n")
    workspace = install / "product" / "投研数字员工"
    _write(workspace / "00_老板投资说明书.md", "只看 A 股和港股")
    _write(workspace / "conversations" / "old.md", "老板历史对话")
    _write(workspace / "reports" / "old.md", "老板历史报告")
    database = workspace / "data" / "research.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, content TEXT)")
        connection.execute("INSERT INTO messages(content) VALUES ('老板历史消息')")
        connection.commit()
    return install


def _build_package(tmp_path: Path, *, target_version: str = "0.11.0") -> Path:
    package = tmp_path / "AI投研数字员工_Update"
    payloads = {
        "product/VERSION": f"{target_version}\n",
        "product/app/program.txt": "new program",
        "product/scripts/update_core.py": "new updater",
        "product/投研数字员工/.system/helper.py": "new helper",
        "codex-plugin-marketplace/plugins/plugin.txt": "new plugin",
    }
    files = []
    for target, content in payloads.items():
        path = package / target
        _write(path, content)
        data = path.read_bytes()
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
    _write(
        package / "UPDATE_MANIFEST.json",
        json.dumps(manifest, ensure_ascii=False),
    )
    return package


def _database_message(install: Path) -> str:
    database = install / "product" / "投研数字员工" / "data" / "research.db"
    with closing(sqlite3.connect(database)) as connection:
        return str(connection.execute("SELECT content FROM messages").fetchone()[0])


def test_update_replaces_program_but_preserves_all_owner_data(tmp_path: Path) -> None:
    install = _build_install(tmp_path)
    package = _build_package(tmp_path)

    result = apply_update(package, install, current_version="0.10.0")

    assert result["to_version"] == "0.11.0"
    assert (install / "product" / "app" / "program.txt").read_text(encoding="utf-8") == "new program"
    assert (
        install / "codex-plugin-marketplace" / "plugins" / "plugin.txt"
    ).read_text(encoding="utf-8") == "new plugin"
    assert (install / "product" / ".env").read_text(encoding="utf-8") == "OPENAI_API_KEY=local-secret\n"
    workspace = install / "product" / "投研数字员工"
    assert (workspace / "00_老板投资说明书.md").read_text(encoding="utf-8") == "只看 A 股和港股"
    assert (workspace / "conversations" / "old.md").read_text(encoding="utf-8") == "老板历史对话"
    assert (workspace / "reports" / "old.md").read_text(encoding="utf-8") == "老板历史报告"
    assert _database_message(install) == "老板历史消息"

    backup = Path(result["backup_root"])
    assert (backup / "ROLLBACK_STATE.json").is_file()
    assert (backup / "老板资料升级前快照.zip").is_file()


def test_failed_health_can_roll_back_program_and_database(tmp_path: Path) -> None:
    install = _build_install(tmp_path)
    package = _build_package(tmp_path)
    result = apply_update(package, install, current_version="0.10.0")

    database = install / "product" / "投研数字员工" / "data" / "research.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE messages SET content='升级后临时变化'")
        connection.commit()
    _write(install / "product" / ".env", "OPENAI_API_KEY=changed\n")

    rolled_back = rollback_update(
        Path(result["backup_root"]),
        install,
        restore_userdata=True,
    )

    assert rolled_back["restored_version"] == "0.10.0"
    assert (install / "product" / "app" / "program.txt").read_text(encoding="utf-8") == "old program"
    assert (
        install / "codex-plugin-marketplace" / "plugins" / "plugin.txt"
    ).read_text(encoding="utf-8") == "old plugin"
    assert _database_message(install) == "老板历史消息"
    assert (install / "product" / ".env").read_text(encoding="utf-8") == "OPENAI_API_KEY=local-secret\n"


@pytest.mark.parametrize(
    "protected_target",
    [
        "product/.env",
        "product/.venv/secret.txt",
        "product/runtime/app.log",
        "product/投研数字员工/data/research.db",
        "product/投研数字员工/conversations/old.md",
        "product/投研数字员工/00_老板投资说明书.md",
        "outside/file.txt",
        "product/../outside.txt",
    ],
)
def test_update_manifest_cannot_target_owner_data(
    tmp_path: Path,
    protected_target: str,
) -> None:
    package = _build_package(tmp_path)
    manifest_path = package / "UPDATE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    source = package / Path(protected_target.replace("..", "dotdot"))
    _write(source, "forbidden")
    manifest["files"].append(
        {
            "path": protected_target,
            "size_bytes": 9,
            "sha256": hashlib.sha256(b"forbidden").hexdigest(),
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(UpdateError):
        verify_package(package)


def test_tampered_update_file_is_rejected(tmp_path: Path) -> None:
    package = _build_package(tmp_path)
    _write(package / "product" / "app" / "program.txt", "tampered")
    with pytest.raises(UpdateError, match="校验失败"):
        verify_package(package)


def test_downgrade_and_same_version_are_rejected(tmp_path: Path) -> None:
    install = _build_install(tmp_path)
    package = _build_package(tmp_path, target_version="0.10.0")
    with pytest.raises(UpdateError, match="不高于当前"):
        apply_update(package, install, current_version="0.10.0")
