from __future__ import annotations

import re

from .source_quality import INLINE_CITATION_PATTERN, MARKDOWN_LINK_PATTERN, NUMERIC_FACT_PATTERN


class OutputSafetyError(RuntimeError):
    """Raised when a generated answer still contains prohibited trading instructions."""


_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "action_instruction",
        "具体买卖或加减仓指令",
        re.compile(
            r"(?<!不)(?:建议|应该|应当|可考虑|可以考虑|值得|适合|现在|立即|立刻)"
            r"\s*(?:直接|逐步|分批|逢低|趁机|继续)?\s*"
            r"(?:买入|卖出|加仓|减仓|建仓|清仓|持有)"
        ),
    ),
    (
        "conditional_trade",
        "以价格或走势触发的交易指令",
        re.compile(
            r"(?:跌到|跌至|回落到|回落至|涨到|涨至|突破)"
            r"[^。\n]{0,32}(?:买入|卖出|加仓|减仓|建仓|清仓)"
        ),
    ),
    (
        "target_price",
        "目标价、止损价或止盈价",
        re.compile(
            r"(?:目标价|止损价|止盈价|建议买入价)\s*"
            r"(?:为|是|设为|设在|给到|看到|[:：])\s*"
            r"(?:人民币|港元|美元|日元|韩元|HKD|USD|CNY|RMB|[$¥￥])?\s*\d",
            re.IGNORECASE,
        ),
    ),
    (
        "position_sizing",
        "个性化仓位或持仓比例",
        re.compile(
            r"(?:(?:建议|应该|应当|可考虑|你的|您的|老板的)\s*)?"
            r"仓位\s*(?:控制|设|加|提高|降|降低|调整)"
            r"(?:在|为|到|至)?\s*\d+(?:\.\d+)?\s*%"
        ),
    ),
    (
        "guaranteed_return",
        "收益保证或确定性获利承诺",
        re.compile(
            r"(?:保证|确保|承诺)[^。\n]{0,12}(?:收益|回报|盈利)"
            r"|稳赚|必赚|保本保收益"
            r"|(?:一定|必然|肯定会)\s*(?:上涨|涨停|翻倍|赚钱|盈利)"
        ),
    ),
)


def audit_investment_output(content: str) -> dict:
    violations: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        for code, label, pattern in _RULES:
            match = pattern.search(line)
            if not match:
                continue
            key = (code, match.group(0))
            if key in seen:
                continue
            seen.add(key)
            violations.append(
                {
                    "code": code,
                    "label": label,
                    "line": line_number,
                    "excerpt": line[:180],
                }
            )
    return {
        "compliant": not violations,
        "violations": violations,
        "checked_rules": len(_RULES),
    }


def strip_research_preamble(content: str) -> str:
    """Remove a leading tool/skill narration while keeping the research itself intact."""

    stripped = content.lstrip()
    heading_index = stripped.find("\n#")
    if heading_index <= 0:
        return stripped
    preamble = stripped[:heading_index].strip()
    if re.search(
        r"(?:我会|我将|接下来).{0,80}(?:Skill|技能|工具|联网|检索|核对)",
        preamble,
        re.IGNORECASE | re.DOTALL,
    ):
        return stripped[heading_index + 1 :].lstrip()
    return stripped


def attach_explicit_table_sources(content: str) -> str:
    """Carry an explicitly introduced table source onto each numeric row."""

    lines = content.splitlines()
    previous_nonempty = ""
    table_url = ""
    in_table = False
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if line.startswith("|"):
            if not in_table:
                introduced = bool(
                    re.search(r"(?:如下|见下表|分部|表中)", previous_nonempty)
                )
                links = MARKDOWN_LINK_PATTERN.findall(previous_nonempty)
                table_url = links[-1][1] if introduced and links else ""
                in_table = True
            if (
                table_url
                and not line.startswith("|---")
                and not line.startswith("| ---")
                and NUMERIC_FACT_PATTERN.search(line)
                and not INLINE_CITATION_PATTERN.search(line)
            ):
                replacement = raw_line.rstrip()
                if replacement.endswith("|"):
                    replacement = replacement[:-1].rstrip()
                lines[index] = f"{replacement} [表格来源]({table_url}) |"
        else:
            if line:
                previous_nonempty = line
                in_table = False
                table_url = ""
    return "\n".join(lines)


def safety_policy_overview() -> dict:
    return {
        "mode": "research-only",
        "public_information_only": True,
        "trading_permissions": False,
        "output_gate": True,
        "rules": [
            {"code": code, "label": label}
            for code, label, _ in _RULES
        ],
        "action_on_violation": "先尝试改写为事实、条件、反方证据与验证信号；仍不合规则阻止归档。",
        "limitations": [
            "规则闸门不能替代人工判断。",
            "产品不连接证券账户、微信或通讯录，也不自动下单。",
        ],
    }
