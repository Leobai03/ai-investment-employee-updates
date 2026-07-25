from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote


MARKET_ALIASES = {
    "A": "A股",
    "A股": "A股",
    "沪深": "A股",
    "港股": "港股",
    "香港": "港股",
    "美股": "美股",
    "美国": "美股",
    "日本": "日本",
    "日股": "日本",
    "韩国": "韩国",
    "韩股": "韩国",
    "全球": "全球宏观",
    "全球宏观": "全球宏观",
}


PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "id": "cninfo",
        "name": "巨潮资讯",
        "market": "A股",
        "kind": "法定披露",
        "quality": "一手来源",
        "access_mode": "公开网页",
        "auth_required": False,
        "url": "https://www.cninfo.com.cn/new/fulltextSearch?keyWord={query}",
        "capabilities": ["定期报告", "临时公告", "公司治理", "重大事项"],
        "note": "A股公司披露首选；按公司代码与公告日期核对原始 PDF。",
    },
    {
        "id": "sse",
        "name": "上海证券交易所",
        "market": "A股",
        "kind": "交易所",
        "quality": "一手来源",
        "access_mode": "公开网页",
        "auth_required": False,
        "url": "https://www.sse.com.cn/assortment/stock/list/info/announcement/",
        "capabilities": ["沪市公告", "监管问询", "交易规则"],
        "note": "沪市公告和监管文件交叉核验入口。",
    },
    {
        "id": "szse",
        "name": "深圳证券交易所",
        "market": "A股",
        "kind": "交易所",
        "quality": "一手来源",
        "access_mode": "公开网页",
        "auth_required": False,
        "url": "https://www.szse.cn/disclosure/notice/company/index.html",
        "capabilities": ["深市公告", "监管信息", "交易规则"],
        "note": "深市公告和监管文件交叉核验入口。",
    },
    {
        "id": "hkexnews",
        "name": "港交所披露易",
        "market": "港股",
        "kind": "法定披露",
        "quality": "一手来源",
        "access_mode": "公开网页",
        "auth_required": False,
        "url": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh",
        "capabilities": ["业绩公告", "年报/中报", "通函", "权益披露"],
        "note": "港股公司披露首选；实时行情另有许可条件，不能与公告数据混为一谈。",
    },
    {
        "id": "sec_edgar",
        "name": "SEC EDGAR",
        "market": "美股",
        "kind": "法定披露/API",
        "quality": "一手来源",
        "access_mode": "公开网页 + 官方 JSON API",
        "auth_required": False,
        "url": "https://www.sec.gov/edgar/search/#/q={query}",
        "api_url": "https://data.sec.gov/",
        "capabilities": ["申报文件", "公司提交历史", "XBRL Company Facts"],
        "note": "自动访问需遵守 SEC Fair Access，并携带可识别 User-Agent。",
    },
    {
        "id": "edinet",
        "name": "日本 EDINET",
        "market": "日本",
        "kind": "法定披露/API",
        "quality": "一手来源",
        "access_mode": "公开网页；结构化 API 需订阅密钥",
        "auth_required": True,
        "url": "https://disclosure2.edinet-fsa.go.jp/WEEK0010.aspx",
        "api_url": "https://api.edinet-fsa.go.jp/api/v2/",
        "capabilities": ["有价证券报告书", "季度报告", "XBRL/CSV"],
        "note": "未配置 EDINET 密钥时只使用公开网页和原始文件，不绕过认证。",
    },
    {
        "id": "jpx",
        "name": "日本交易所集团 JPX",
        "market": "日本",
        "kind": "交易所",
        "quality": "一手来源",
        "access_mode": "公开网页；部分行情/API 为付费服务",
        "auth_required": True,
        "url": "https://www.jpx.co.jp/english/",
        "capabilities": ["交易日历", "上市公司资料", "交易所规则"],
        "note": "价格数据必须标明延迟程度和授权来源。",
    },
    {
        "id": "open_dart",
        "name": "韩国 Open DART",
        "market": "韩国",
        "kind": "法定披露/API",
        "quality": "一手来源",
        "access_mode": "公开网页；结构化 API 需认证密钥",
        "auth_required": True,
        "url": "https://englishdart.fss.or.kr/",
        "api_url": "https://engopendart.fss.or.kr/engapi/",
        "capabilities": ["披露检索", "原始文件", "主要财务科目"],
        "note": "未配置 DART 密钥时只使用公开网页和原始披露。",
    },
    {
        "id": "krx",
        "name": "韩国交易所 KRX",
        "market": "韩国",
        "kind": "交易所/API",
        "quality": "一手来源",
        "access_mode": "公开网页；Open API 需申请认证密钥",
        "auth_required": True,
        "url": "https://data.krx.co.kr/",
        "api_url": "https://openapi.krx.co.kr/",
        "capabilities": ["交易日历", "市场统计", "证券产品数据"],
        "note": "价格和统计字段必须保留基准日、币种和市场口径。",
    },
    {
        "id": "global_macro",
        "name": "央行、统计机构与国际组织",
        "market": "全球宏观",
        "kind": "宏观原始数据",
        "quality": "一手来源",
        "access_mode": "公开网页/API（依机构规则）",
        "auth_required": False,
        "url": "https://www.bis.org/statistics/",
        "capabilities": ["利率", "通胀", "就业", "增长", "跨境金融"],
        "note": "中国优先央行/统计局，美国优先 Fed/BLS/BEA，日本优先 BOJ，韩国优先 BOK。",
    },
)


FIELD_CONTRACTS = {
    "disclosure": [
        "公司名称与证券代码",
        "文件标题与公告/提交日期",
        "报告期间",
        "币种与单位",
        "合并/母公司口径",
        "原始文件 URL",
        "采集时间",
    ],
    "financial_metric": [
        "指标名称",
        "数值",
        "币种/单位",
        "期间",
        "TTM/年度/季度口径",
        "审计状态",
        "原始文件及页码/章节",
    ],
    "market_quote": [
        "证券与交易所",
        "收盘/实时/延迟类型",
        "时间与时区",
        "币种",
        "复权方式",
        "数据提供者",
        "第二来源核验状态",
    ],
}


def normalize_markets(markets: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for market in markets or []:
        name = MARKET_ALIASES.get(str(market).strip(), str(market).strip())
        if name and name not in normalized:
            normalized.append(name)
    return normalized


def build_collection_plan(
    markets: list[str] | None,
    *,
    company: str = "",
    symbol: str = "",
) -> dict[str, Any]:
    selected = normalize_markets(markets)
    query_text = " ".join(part for part in (symbol.strip(), company.strip()) if part).strip()
    query = quote(query_text)
    providers: list[dict[str, Any]] = []
    for provider in PROVIDERS:
        if provider["market"] not in selected:
            continue
        item = dict(provider)
        item["url"] = item["url"].format(query=query)
        providers.append(item)
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "markets": selected,
        "company": company.strip(),
        "symbol": symbol.strip(),
        "providers": providers,
        "field_contracts": FIELD_CONTRACTS,
        "fallback_policy": [
            "官方结构化接口可用时优先使用；保留原始 URL、查询时间和字段口径。",
            "接口需要密钥、许可或暂时不可用时，降级到同一机构公开网页和原始文件。",
            "免费行情、聚合网站和媒体只作辅助；精确数字必须回到原始披露或独立来源交叉核验。",
            "任何来源失败都应明确记录缺失，不用旧值、缓存值或模型猜测填空。",
        ],
        "boundary": "只读公开信息；不连接证券账户，不含下单、持仓或交易角色。",
    }


def collection_prompt_block(
    markets: list[str] | None,
    *,
    company: str = "",
    symbol: str = "",
) -> str:
    plan = build_collection_plan(markets, company=company, symbol=symbol)
    provider_lines = "\n".join(
        f"- {item['market']}｜{item['name']}｜{item['access_mode']}｜{item['url']}｜"
        f"{'需单独授权' if item['auth_required'] else '无需账户'}"
        for item in plan["providers"]
    )
    contracts = "；".join(FIELD_CONTRACTS["financial_metric"])
    return (
        "# 本任务公开数据采集契约\n"
        f"优先入口：\n{provider_lines or '- 当前市场未登记专用入口，先查监管、交易所和公司官网。'}\n"
        f"财务数字必须同时保留：{contracts}。\n"
        "结构化接口不可用时回到同一机构公开网页和原始文件；"
        "免费行情或聚合数据只能辅助定位，不能替代公告核验；失败时明确写缺失，不猜值。"
    )

