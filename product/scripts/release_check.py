#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MANIFEST = (
    ROOT.parent
    / "codex-plugin-marketplace"
    / "plugins"
    / "ai-investment-employee"
    / ".codex-plugin"
    / "plugin.json"
)


def fail(message: str) -> int:
    print(f"✗ {message}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="发布前统一版本并构建 GitHub 更新包。")
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()

    if not re.fullmatch(r"v\d+\.\d+\.\d+", args.tag):
        return fail(f"Git 标签格式错误：{args.tag}")
    version = args.tag.removeprefix("v")
    version_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version_file != version:
        return fail(f"VERSION 是 {version_file}，标签是 {version}。")
    main_text = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    init_text = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    build_text = (ROOT / "scripts" / "build_delivery.py").read_text(encoding="utf-8")
    plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    if f'APP_VERSION = "{version}"' not in main_text:
        return fail("app/main.py 版本不一致。")
    if f'__version__ = "{version}"' not in init_text:
        return fail("app/__init__.py 版本不一致。")
    if f'VERSION = "{version}"' not in build_text:
        return fail("打包器版本不一致。")
    if not str(plugin.get("version") or "").startswith(f"{version}+"):
        return fail("Codex 插件版本不一致。")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_update_bundle.py")],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        return result.returncode
    archive = ROOT / "dist" / f"ai-investment-employee-update-v{version}.zip"
    checksum = archive.with_suffix(".zip.sha256")
    if not archive.is_file() or not checksum.is_file():
        return fail("更新包或校验文件没有生成。")
    print(f"✓ 版本 v{version} 可以发布。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
