#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


FILES = {
    "00_老板投资说明书.md": """# 老板投资说明书

> 这里只记录老板明确确认过的长期偏好。没有回答的内容保持“待确认”。

## 基本信息

- 称呼：老板
- 重点市场：待确认
- 参考市场：待确认
- 投资周期：待确认
- 报告偏好：先给结论，再给证据和风险

## 重点板块

- 待确认

## 常用指标

- 待确认

## 风险边界

- 不连接证券账户，不自动下单
- 不保存账号密码、验证码和无必要的精确仓位
- 其他待确认

## 数据权限

- 已授权数据终端：待确认
- 公开网页研究：允许

## 更新记录

""",
    "01_自选公司.md": """# 自选公司

每家公司记录：代码、市场、加入日期、研究理由、当前状态和最近报告。

| 公司 | 代码 | 市场 | 加入日期 | 最初研究理由 | 状态 |
| --- | --- | --- | --- | --- | --- |

""",
    "02_重点板块.md": """# 重点板块

| 板块 | 关注理由 | 领先指标 | 跟踪频率 | 状态 |
| --- | --- | --- | --- | --- |

""",
    "03_研究原则.md": """# 研究原则

1. 最新事实必须联网核验并保留来源。
2. 严格区分事实、分析、假设和缺失信息。
3. 同时寻找支持证据与反方证据。
4. 不给个性化买卖指令、目标价或收益保证。
5. 精确行情、估值和财务数字回到一手来源或合法授权终端复核。

""",
    "04_决策日志.md": """# 决策日志

> 记录重要研究判断及其后续变化，不记录自动交易指令。

""",
    "05_待确认记忆.md": """# 待确认记忆

> 系统推测但老板尚未确认的偏好只能放在这里。

""",
    "06_老板纠正与反馈.md": """# 老板纠正与反馈

> 记录老板指出的误解、表达偏差，以及以后必须遵守的改进。

""",
}

DIRECTORIES = [
    "inbox",
    "reports/daily",
    "reports/company",
    "reports/questions",
    "reports/reviews",
    "sources",
    ".system",
    "data",
]


def initialize(root: Path) -> tuple[list[Path], list[Path]]:
    base = root.expanduser().resolve() / "投研数字员工"
    created: list[Path] = []
    preserved: list[Path] = []
    base.mkdir(parents=True, exist_ok=True)

    for directory in DIRECTORIES:
        path = base / directory
        path.mkdir(parents=True, exist_ok=True)

    for name, content in FILES.items():
        path = base / name
        if path.exists():
            preserved.append(path)
            continue
        path.write_text(content, encoding="utf-8")
        created.append(path)

    source_dashboard = Path(__file__).with_name("serve_dashboard.py")
    target_dashboard = base / ".system" / "serve_dashboard.py"
    shutil.copy2(source_dashboard, target_dashboard)
    target_dashboard.chmod(0o755)

    source_recorder = Path(__file__).with_name("record_codex_turn.py")
    target_recorder = base / ".system" / "record_codex_turn.py"
    shutil.copy2(source_recorder, target_recorder)
    target_recorder.chmod(0o755)

    workspace_root = root.expanduser().resolve()
    launcher = workspace_root / "打开AI投研驾驶舱.command"
    if (workspace_root / "启动研究台.command").exists():
        launcher_body = """#!/bin/zsh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
"$ROOT/启动研究台.command"
"""
    else:
        launcher_body = """#!/bin/zsh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
python3 "$ROOT/投研数字员工/.system/serve_dashboard.py" \
  --data-dir "$ROOT/投研数字员工"
"""
    launcher.write_text(launcher_body, encoding="utf-8")
    launcher.chmod(0o755)

    windows_launcher = workspace_root / "打开AI投研驾驶舱.cmd"
    if (workspace_root / "Windows_启动研究台.cmd").exists():
        windows_body = """@echo off
call "%~dp0Windows_启动研究台.cmd"
"""
    else:
        windows_body = """@echo off
chcp 65001 > nul
cd /d "%~dp0"
where py.exe > nul 2>&1
if not errorlevel 1 (
  py -3 "投研数字员工\\.system\\serve_dashboard.py" --data-dir "投研数字员工"
  exit /b %ERRORLEVEL%
)
python "投研数字员工\\.system\\serve_dashboard.py" --data-dir "投研数字员工"
"""
    windows_launcher.write_text(windows_body, encoding="utf-8")

    return created, preserved


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化 AI 投研数字员工长期工作区")
    parser.add_argument(
        "--path",
        default=".",
        help="Codex 当前工作区路径，默认是当前目录",
    )
    args = parser.parse_args()
    created, preserved = initialize(Path(args.path))

    print(f"已创建 {len(created)} 个文件；保留 {len(preserved)} 个已有文件。")
    print(f"工作区：{(Path(args.path).expanduser().resolve() / '投研数字员工')}")
    print("可视化入口：Windows 使用“打开AI投研驾驶舱.cmd”，Mac 使用“.command”入口。")
    if preserved:
        print("未覆盖已有长期记忆。")


if __name__ == "__main__":
    main()
