from __future__ import annotations

from typing import Any


FRAMEWORKS: list[dict[str, Any]] = [
    {
        "id": "duan_yongping",
        "name": "段永平公开方法",
        "short_name": "段永平框架",
        "summary": "先把股票当公司看，再检查生意、文化、能力圈、长期现金流和可承受风险。",
        "principles": [
            "买股票就是买公司，不把短期价格波动当成公司价值。",
            "先问自己是否真的理解商业模式、竞争优势和企业文化。",
            "看长远，远离无法承受的高风险；不懂的地方明确列为待核验。",
            "估值不是追求小数点，而是比较长期价值、价格和机会成本。",
        ],
        "questions": [
            "这家公司长期靠什么赚钱，十年后这个逻辑还在吗？",
            "它的商业模式和企业文化，哪些证据可以被验证？",
            "如果股价今天不报价，我还愿意持有这家公司吗？",
            "最大的认知盲区和无法承受的风险是什么？",
        ],
        "sources": [
            {
                "title": "浙江大学见面会实录：最重要的不是勤奋，而是做对事情",
                "url": "https://zdpx.zju.edu.cn/peixun/zdnews_1144_301.html",
                "publisher": "浙江大学培训中心",
                "note": "公开对谈原始实录，涉及价值投资、商业模式、企业文化、风险与长期视角。",
            },
            {
                "title": "段永平谈商业模式和企业文化",
                "url": "https://xueqiu.com/1093341439/232153192",
                "publisher": "雪球公开讨论",
                "note": "公开言论索引，用于回到原讨论核验，不作为本人当前持仓或即时观点。",
            },
        ],
    },
    {
        "id": "dan_bin",
        "name": "但斌公开方法",
        "short_name": "但斌框架",
        "summary": "在大产业趋势里找有壁垒的优秀企业，以合理价格长期参与，同时明确卖出与风控条件。",
        "principles": [
            "发掘杰出的企业，以合理价格投资并长期持有。",
            "重视竞争壁垒、盈利质量、行业空间和全球化比较。",
            "把时代与产业趋势放进公司研究，但不能只靠故事代替财务证据。",
            "持续检查四类退出原因：更好机会、明显高估、企业变坏、系统性风险。",
        ],
        "questions": [
            "这是不是足够大的长期产业趋势，还是短期热门叙事？",
            "公司是不是趋势中的真正龙头，壁垒能否转成现金流？",
            "当前价格是否已经透支了过度乐观的预期？",
            "公司变坏或系统性风险出现时，哪些信号能被提前观察？",
        ],
        "sources": [
            {
                "title": "港湾理念",
                "url": "https://www.ohim.cn/dfgw/yxgw/gwln/index.html",
                "publisher": "深圳东方港湾",
                "note": "东方港湾官方投资理念与优秀企业筛选要点。",
            },
            {
                "title": "2026 年投资者交流会：投资三个核心原则",
                "url": "https://www.ohim.cn/dfgw/contents/2026/2/9-fc97c52cdbad4ccc829a72f5df1fa630.html",
                "publisher": "深圳东方港湾",
                "note": "公司官方发布的公开交流会内容。",
            },
            {
                "title": "选股票不是零和游戏，做好风控才能穿越牛熊",
                "url": "https://cbssite.isimu123.com/dfgw/contents/2020/4/1-5b33b5b72dde4fa09c7b787e9fb94a35.html",
                "publisher": "深圳东方港湾",
                "note": "官方转载专访，含公开的四类卖出规则。",
            },
        ],
    },
]


def list_frameworks() -> list[dict[str, Any]]:
    return FRAMEWORKS


def resolve_frameworks(names: list[str] | None) -> list[dict[str, Any]]:
    selected = {item.strip() for item in (names or []) if item.strip()}
    if not selected:
        return []
    result = []
    for framework in FRAMEWORKS:
        if framework["id"] in selected or framework["name"] in selected or framework["short_name"] in selected:
            result.append(framework)
    return result

