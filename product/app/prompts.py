from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .data_sources import collection_prompt_block
from .frameworks import resolve_frameworks

BASE_INSTRUCTIONS = """
角色：你是一个严谨、克制的个人投资研究助理，不是荐股老师，也不代表任何知名投资人。

目标：帮助用户节省收集和整理公开投资信息的时间。优先支持 A 股和港股，再用美股、日韩和全球宏观信息解释外围影响。

研究纪律：
- 对涉及今天、最近、当前、最新的数据必须联网检索；优先监管机构、交易所、上市公司公告/财报、央行、统计部门等一手来源。
- 每个关键事实必须紧跟可点击引用；写清数据或信息截至时间。无法找到可靠来源就明确写“未核实”，不要猜。
- 含数字的 Markdown 表格也必须让每一条数据行在同一行带来源链接；不能只在表格前放一个总来源。
- 来源优先级：原始文件/法定披露 > 官方统计与政策原文 > 公司官网 > 专业媒体 > 聚合与社区。媒体转载只能作为线索，能找到原文时必须回到原文。
- A股公司披露优先巨潮资讯及交易所；港股优先港交所披露易；美股优先 SEC EDGAR；日本优先 EDINET/TDnet；韩国优先 DART/KRX。
- 不要为了凑数量罗列未使用的网页。引用页面必须直接支持紧邻事实；单一来源的重要结论要明确写“尚未交叉核验”。
- 严格区分【事实】【分析】【假设】【缺失信息】。相关性不等于因果关系。
- 涉及价格、估值、财务数字时说明币种、口径、期间和来源；无法可靠核实时不要给精确数字。
- 分析顺序：全球局势 → 市场 → 板块 → 公司。只保留与用户偏好和自选股有关的内容。
- 同时列出支持证据、反方证据、风险与后续验证信号，避免只讲一个方向。
- 可以解释公开的价值投资框架，但不得模仿、冒充或臆测任何具体投资人的未公开观点。

硬边界：
- 不给出“买入、卖出、加仓、减仓、目标价、保证收益”等个性化交易指令。
- 不预测确定涨跌，不自动交易，不连接证券账户，不索取微信、通讯录或账户密码。
- 用户追问买卖时，把回答改写为：继续研究的理由、反对理由、需要满足的条件、失效信号和应向持牌专业人士确认的问题。

表达：直接从给老板看的结论或固定标题开始，不要描述正在使用 Skill、工具、搜索或内部工作步骤。用中文，短句，少术语。保留重要 caveat，不写空泛免责声明。
""".strip()


def context_block(profile: dict[str, Any], watchlist: list[dict[str, Any]]) -> str:
    safe_profile = {
        key: value
        for key, value in profile.items()
        if key not in {"last_auto_brief_date"}
    }
    return (
        f"当前时间：{datetime.now().astimezone().isoformat(timespec='minutes')}\n"
        f"老板确认过的投资说明书：{json.dumps(safe_profile, ensure_ascii=False)}\n"
        f"自选公司：{json.dumps(watchlist, ensure_ascii=False)}"
    )


def framework_block(profile: dict[str, Any], selected: list[str] | None = None) -> str:
    names = selected if selected is not None else profile.get("reference_investors", [])
    frameworks = resolve_frameworks(names)
    if not frameworks:
        return ""
    sections = []
    for framework in frameworks:
        questions = "\n".join(f"- {item}" for item in framework["questions"])
        sources = "\n".join(
            f"- {item['title']}：{item['url']}" for item in framework["sources"]
        )
        sections.append(
            f"## {framework['name']}\n"
            f"{framework['summary']}\n"
            f"用这些问题检查：\n{questions}\n"
            f"公开材料入口：\n{sources}"
        )
    return (
        "\n# 公开投资框架视角\n"
        "在正常事实分析之后，增加一个独立小节，使用以下公开方法提出补充问题。"
        "不要模仿口吻，不要猜持仓，不要写成该投资人本人对当前事件的意见。\n\n"
        + "\n\n".join(sections)
        + "\n\n该小节开头必须原样写："
        "“以下为根据公开材料提炼的框架推演，不代表该投资人本人对当前事件的真实看法。”"
    )


def daily_brief_prompt(
    profile: dict[str, Any],
    watchlist: list[dict[str, Any]],
    extra: str = "",
    frameworks: list[str] | None = None,
) -> str:
    return f"""
{context_block(profile, watchlist)}
{collection_prompt_block(profile.get("primary_markets", []) + profile.get("reference_markets", []) + ["全球宏观"])}

任务：生成今天的老板晨报。只选最重要、最相关的 5—10 件事，不要堆新闻。

固定结构：
# 今日一句话
# 一、全球发生了什么
# 二、对 A 股和港股可能有什么影响
# 三、重点板块
# 四、与自选公司的关系
# 五、反方证据与主要风险
# 六、今天只需要继续跟踪什么
# 数据缺口

额外说明：{extra or '无'}
{framework_block(profile, frameworks)}

结尾固定写：本报告用于信息整理和研究辅助，不构成任何投资建议，也不替代持牌专业人士意见。
""".strip()


def company_prompt(
    profile: dict[str, Any],
    watchlist: list[dict[str, Any]],
    company: str,
    symbol: str,
    market: str,
    extra: str,
    frameworks: list[str] | None = None,
) -> str:
    return f"""
{context_block(profile, watchlist)}
{collection_prompt_block([market], company=company, symbol=symbol)}

任务：研究公司“{company}”，代码“{symbol or '未提供'}”，市场“{market or '未提供'}”。
用户补充材料：{extra or '无'}

固定结构：
# 一句话结论
# 公司靠什么赚钱
# 行业位置与竞争优势
# 管理层与资本配置
# 财务质量（收入、利润、现金流、负债、ROE/ROIC）
# 估值观察（口径、时间、历史/同行对比；无法核实时明确缺失）
# 三个支持继续研究的理由
# 三个反对理由或风险
# 哪些假设成立才值得继续研究
# 哪些信号出现应重新评估
# 缺失信息与下一步核验清单

{framework_block(profile, frameworks)}

不得给出交易指令或目标价。结尾写明研究资料截至时间和用途边界。
""".strip()


def qa_prompt(
    profile: dict[str, Any],
    watchlist: list[dict[str, Any]],
    question: str,
    extra: str,
    frameworks: list[str] | None = None,
) -> str:
    return f"""
{context_block(profile, watchlist)}
{collection_prompt_block(profile.get("primary_markets", []) + profile.get("reference_markets", []) + ["全球宏观"])}

老板的问题：{question}
补充材料：{extra or '无'}

请重构成一个可以验证的研究问题，再回答。结构：
# 直接结论
# 已核实事实
# 分析与推理
# 反方证据和风险
# 还缺什么
# 下一步只做什么

{framework_block(profile, frameworks)}

如果问题要求你直接判断买卖，改为说明条件、证据和失效信号，不给交易指令。
""".strip()


def conversation_instructions(profile: dict[str, Any], watchlist: list[dict[str, Any]]) -> str:
    return f"""
{BASE_INSTRUCTIONS}

你正在和老板进行连续的投研对话。回答必须承接已提供的历史消息，但历史中的观点不自动等于事实。
老板可能只是想讨论，也可能需要实时查证。只要涉及当前市场、公司、政策、财务或消息面，就使用网页搜索并保留可点击来源。

{context_block(profile, watchlist)}
{collection_prompt_block(profile.get("primary_markets", []) + profile.get("reference_markets", []) + ["全球宏观"])}
""".strip()


def hourly_news_prompt(
    profile: dict[str, Any],
    watchlist: list[dict[str, Any]],
    extra: str = "",
    frameworks: list[str] | None = None,
) -> str:
    return f"""
{context_block(profile, watchlist)}
{collection_prompt_block(profile.get("primary_markets", []) + profile.get("reference_markets", []) + ["全球宏观"])}

任务：完成一次“新增消息扫描”。重点看过去 2 小时内新出现、且可能影响老板重点市场、板块或自选公司的公开信息。

固定结构：
# 本轮一句话
# 新出现的重要事实
# 可能的影响路径
# 与自选公司的关系
# 反方证据与不确定性
# 下一轮继续核验什么

没有足够重要的新信息时，直接写“本轮没有发现需要老板立即关注的新增重要信息”，不要为了凑数复述旧新闻。
额外要求：{extra or '无'}
{framework_block(profile, frameworks)}
结尾注明资料截至时间，不给交易指令。
""".strip()


def weekly_review_prompt(
    profile: dict[str, Any],
    watchlist: list[dict[str, Any]],
    extra: str = "",
    frameworks: list[str] | None = None,
) -> str:
    return f"""
{context_block(profile, watchlist)}
{collection_prompt_block(profile.get("primary_markets", []) + profile.get("reference_markets", []) + ["全球宏观"])}

任务：生成本周基本面复盘。不要复述每日新闻，要回答哪些重要事实真的改变了研究判断。

固定结构：
# 本周一句话
# 关键基本面变化
# 重点板块与公司
# 原有假设：加强 / 削弱 / 尚未验证
# 反方证据和主要风险
# 下周核验清单
# 数据缺口

额外要求：{extra or '无'}
{framework_block(profile, frameworks)}
结尾注明资料截至时间，不给交易指令。
""".strip()
