from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse


# Intentionally conservative: titles never make a source "primary". The
# hostname must match a known official organization or issuer.
OFFICIAL_SOURCES: tuple[dict[str, Any], ...] = (
    {"domain": "cninfo.com.cn", "publisher": "巨潮资讯", "source_type": "disclosure", "markets": ["A股"]},
    {"domain": "sse.com.cn", "publisher": "上海证券交易所", "source_type": "exchange", "markets": ["A股"]},
    {"domain": "szse.cn", "publisher": "深圳证券交易所", "source_type": "exchange", "markets": ["A股"]},
    {"domain": "bse.cn", "publisher": "北京证券交易所", "source_type": "exchange", "markets": ["A股"]},
    {"domain": "csrc.gov.cn", "publisher": "中国证监会", "source_type": "regulator", "markets": ["A股", "港股"]},
    {"domain": "pbc.gov.cn", "publisher": "中国人民银行", "source_type": "central_bank", "markets": ["中国宏观"]},
    {"domain": "stats.gov.cn", "publisher": "国家统计局", "source_type": "statistics", "markets": ["中国宏观"]},
    {"domain": "ndrc.gov.cn", "publisher": "国家发展改革委", "source_type": "government", "markets": ["中国宏观"]},
    {"domain": "mof.gov.cn", "publisher": "财政部", "source_type": "government", "markets": ["中国宏观"]},
    {"domain": "safe.gov.cn", "publisher": "国家外汇管理局", "source_type": "regulator", "markets": ["中国宏观"]},
    {"domain": "gov.cn", "publisher": "中国政府网", "source_type": "government", "markets": ["中国宏观"]},
    {"domain": "hkexnews.hk", "publisher": "港交所披露易", "source_type": "disclosure", "markets": ["港股"]},
    {"domain": "hkex.com.hk", "publisher": "香港交易所", "source_type": "exchange", "markets": ["港股"]},
    {"domain": "sfc.hk", "publisher": "香港证监会", "source_type": "regulator", "markets": ["港股"]},
    {"domain": "hkma.gov.hk", "publisher": "香港金融管理局", "source_type": "central_bank", "markets": ["港股"]},
    {"domain": "censtatd.gov.hk", "publisher": "香港政府统计处", "source_type": "statistics", "markets": ["港股"]},
    {"domain": "sec.gov", "publisher": "美国证券交易委员会", "source_type": "disclosure", "markets": ["美股"]},
    {"domain": "federalreserve.gov", "publisher": "美国联邦储备委员会", "source_type": "central_bank", "markets": ["美股", "全球宏观"]},
    {"domain": "bls.gov", "publisher": "美国劳工统计局", "source_type": "statistics", "markets": ["美股", "全球宏观"]},
    {"domain": "bea.gov", "publisher": "美国经济分析局", "source_type": "statistics", "markets": ["美股", "全球宏观"]},
    {"domain": "treasury.gov", "publisher": "美国财政部", "source_type": "government", "markets": ["美股", "全球宏观"]},
    {"domain": "boj.or.jp", "publisher": "日本银行", "source_type": "central_bank", "markets": ["日本"]},
    {"domain": "jpx.co.jp", "publisher": "日本交易所集团", "source_type": "exchange", "markets": ["日本"]},
    {"domain": "edinet-fsa.go.jp", "publisher": "EDINET", "source_type": "disclosure", "markets": ["日本"]},
    {"domain": "fsa.go.jp", "publisher": "日本金融厅", "source_type": "regulator", "markets": ["日本"]},
    {"domain": "stat.go.jp", "publisher": "日本总务省统计局", "source_type": "statistics", "markets": ["日本"]},
    {"domain": "dart.fss.or.kr", "publisher": "韩国 DART", "source_type": "disclosure", "markets": ["韩国"]},
    {"domain": "fss.or.kr", "publisher": "韩国金融监督院", "source_type": "regulator", "markets": ["韩国"]},
    {"domain": "krx.co.kr", "publisher": "韩国交易所", "source_type": "exchange", "markets": ["韩国"]},
    {"domain": "bok.or.kr", "publisher": "韩国银行", "source_type": "central_bank", "markets": ["韩国"]},
    {"domain": "kostat.go.kr", "publisher": "韩国统计厅", "source_type": "statistics", "markets": ["韩国"]},
    {"domain": "imf.org", "publisher": "国际货币基金组织", "source_type": "multilateral", "markets": ["全球宏观"]},
    {"domain": "worldbank.org", "publisher": "世界银行", "source_type": "multilateral", "markets": ["全球宏观"]},
    {"domain": "bis.org", "publisher": "国际清算银行", "source_type": "multilateral", "markets": ["全球宏观"]},
    {"domain": "oecd.org", "publisher": "经合组织", "source_type": "multilateral", "markets": ["全球宏观"]},
    {"domain": "wto.org", "publisher": "世界贸易组织", "source_type": "multilateral", "markets": ["全球宏观"]},
    {"domain": "tencent.com", "publisher": "腾讯公司官网", "source_type": "issuer", "markets": ["港股"]},
    {"domain": "alibabagroup.com", "publisher": "阿里巴巴集团官网", "source_type": "issuer", "markets": ["港股", "美股"]},
    {"domain": "mi.com", "publisher": "小米公司官网", "source_type": "issuer", "markets": ["港股"]},
)

PROFESSIONAL_SOURCES: tuple[dict[str, str], ...] = (
    {"domain": "reuters.com", "publisher": "Reuters"},
    {"domain": "bloomberg.com", "publisher": "Bloomberg"},
    {"domain": "ft.com", "publisher": "Financial Times"},
    {"domain": "wsj.com", "publisher": "The Wall Street Journal"},
    {"domain": "nikkei.com", "publisher": "Nikkei"},
    {"domain": "caixin.com", "publisher": "财新"},
)

AGGREGATOR_SOURCES: tuple[dict[str, str], ...] = (
    {"domain": "xueqiu.com", "publisher": "雪球"},
    {"domain": "eastmoney.com", "publisher": "东方财富"},
    {"domain": "10jqka.com.cn", "publisher": "同花顺"},
    {"domain": "finance.yahoo.com", "publisher": "Yahoo Finance"},
    {"domain": "finance.sina.com.cn", "publisher": "新浪财经"},
)

SOURCE_TYPE_LABELS = {
    "disclosure": "法定披露",
    "exchange": "交易所",
    "regulator": "监管机构",
    "central_bank": "央行",
    "statistics": "统计机构",
    "government": "政府部门",
    "multilateral": "国际组织",
    "issuer": "公司官网",
    "professional_media": "专业媒体",
    "aggregator": "聚合/社区",
    "unknown": "待核验",
    "invalid": "无效链接",
}


def _hostname(url: str) -> str:
    try:
        hostname = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return hostname[4:] if hostname.startswith("www.") else hostname


def _matches(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def _find_source(hostname: str, registry: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
    matches = [item for item in registry if _matches(hostname, str(item["domain"]))]
    if not matches:
        return None
    return max(matches, key=lambda item: len(str(item["domain"])))


def assess_source(source: dict[str, Any]) -> dict[str, Any]:
    result = dict(source)
    url = str(result.get("url") or "").strip()
    hostname = _hostname(url)
    result["url"] = url
    result["domain"] = hostname
    result["citation_role"] = "正文引用" if result.get("kind") == "citation" else "检索参考"

    if not hostname or not url.startswith(("https://", "http://")):
        result.update(
            publisher="未知",
            source_type="invalid",
            source_type_label=SOURCE_TYPE_LABELS["invalid"],
            quality_tier=5,
            quality_label="无效",
            is_primary=False,
            markets=[],
        )
        return result

    official = _find_source(hostname, OFFICIAL_SOURCES)
    if official:
        source_type = str(official["source_type"])
        result.update(
            publisher=official["publisher"],
            source_type=source_type,
            source_type_label=SOURCE_TYPE_LABELS[source_type],
            quality_tier=1,
            quality_label="一手来源",
            is_primary=True,
            markets=list(official.get("markets", [])),
        )
        return result

    professional = _find_source(hostname, PROFESSIONAL_SOURCES)
    if professional:
        result.update(
            publisher=professional["publisher"],
            source_type="professional_media",
            source_type_label=SOURCE_TYPE_LABELS["professional_media"],
            quality_tier=2,
            quality_label="专业二手",
            is_primary=False,
            markets=[],
        )
        return result

    aggregator = _find_source(hostname, AGGREGATOR_SOURCES)
    if aggregator:
        result.update(
            publisher=aggregator["publisher"],
            source_type="aggregator",
            source_type_label=SOURCE_TYPE_LABELS["aggregator"],
            quality_tier=4,
            quality_label="聚合/社区",
            is_primary=False,
            markets=[],
        )
        return result

    result.update(
        publisher=hostname,
        source_type="unknown",
        source_type_label=SOURCE_TYPE_LABELS["unknown"],
        quality_tier=3,
        quality_label="待核验",
        is_primary=False,
        markets=[],
    )
    return result


def enrich_sources(sources: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    enriched: list[dict[str, Any]] = []
    for source in sources or []:
        assessed = assess_source(source)
        url = assessed["url"]
        if not url or url in seen:
            continue
        seen.add(url)
        enriched.append(assessed)
    return enriched


NUMERIC_FACT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:\d{4}年|\d+(?:[.,]\d+)?\s*(?:%|亿元|万元|万亿|亿|万|元|"
    r"美元|港元|人民币|日元|韩元|倍|个百分点|季度|财年))"
)
INLINE_CITATION_PATTERN = re.compile(r"\]\(https?://[^)]+\)")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")


def align_sources_with_content(
    sources: list[dict[str, Any]] | None,
    content: str,
) -> list[dict[str, Any]]:
    inline_links = MARKDOWN_LINK_PATTERN.findall(content or "")
    inline_urls = {url for _, url in inline_links}
    aligned: list[dict[str, Any]] = []
    known_urls: set[str] = set()
    for source in sources or []:
        item = dict(source)
        url = str(item.get("url") or "").strip()
        if url in inline_urls:
            item["kind"] = "citation"
        aligned.append(item)
        if url:
            known_urls.add(url)
    for title, url in inline_links:
        if url in known_urls:
            continue
        aligned.append({"title": title.strip(), "url": url, "kind": "citation"})
        known_urls.add(url)
    return enrich_sources(aligned)


def _numeric_citation_audit(content: str) -> dict[str, Any]:
    claim_lines: list[str] = []
    cited_lines: list[str] = []
    in_code_block = False
    for raw_line in (content or "").splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if (
            in_code_block
            or not line
            or line.startswith("#")
            or line.startswith("| ---")
            or line.startswith(("数据截至", "资料截至", "报告生成时间"))
            or not NUMERIC_FACT_PATTERN.search(line)
        ):
            continue
        claim_lines.append(line)
        if INLINE_CITATION_PATTERN.search(line):
            cited_lines.append(line)
    total = len(claim_lines)
    cited = len(cited_lines)
    return {
        "numeric_claim_count": total,
        "cited_numeric_claim_count": cited,
        "numeric_citation_ratio": round(cited / total, 3) if total else None,
        "uncited_numeric_samples": [
            line[:180] for line in claim_lines if line not in cited_lines
        ][:3],
    }


def audit_sources(
    sources: list[dict[str, Any]] | None,
    content: str = "",
) -> dict[str, Any]:
    items = align_sources_with_content(sources, content)
    total = len(items)
    primary = sum(1 for item in items if item["is_primary"])
    cited = sum(1 for item in items if item["citation_role"] == "正文引用")
    domains = {item["domain"] for item in items if item["domain"]}
    domain_counts = Counter(item["domain"] for item in items if item["domain"])
    types = Counter(item["source_type"] for item in items)
    markets = sorted({market for item in items for market in item.get("markets", [])})
    warnings: list[str] = []

    if not total:
        level, label = "none", "无联网来源"
        warnings.append("正式实时研究必须补充可点击来源。")
    elif primary >= 2 and cited >= 1 and len(domains) >= 2:
        level, label = "strong", "一手证据较充分"
    elif primary >= 1:
        level, label = "adequate", "含一手来源"
        if len(domains) < 2:
            warnings.append("来源集中在单一域名，重要结论宜交叉核验。")
    else:
        level, label = "limited", "缺少已识别一手来源"
        warnings.append("当前清单未识别到监管、交易所、央行、统计机构或已登记公司官网。")

    if total and cited == 0:
        warnings.append("来源均为检索参考，未确认已在正文中逐条引用。")
    if types.get("aggregator", 0):
        warnings.append("聚合或社区来源只能作为线索，关键事实应回到原始文件。")
    if types.get("unknown", 0):
        warnings.append("“待核验”只表示域名尚未登记，不等于该来源不可靠。")
    if total >= 3 and domain_counts:
        top_domain, top_count = domain_counts.most_common(1)[0]
        if top_count / total >= 0.75:
            warnings.append(
                f"来源过度集中：{top_domain} 占 {top_count}/{total}，重要数字应增加独立来源核验。"
            )

    numeric_audit = _numeric_citation_audit(content)
    numeric_total = numeric_audit["numeric_claim_count"]
    numeric_cited = numeric_audit["cited_numeric_claim_count"]
    if numeric_total and numeric_cited < numeric_total:
        warnings.append(
            f"检测到 {numeric_total - numeric_cited}/{numeric_total} 行数字事实没有同一行可点击引用；"
            "请逐条核对币种、期间和口径。"
        )

    return {
        "total": total,
        "primary_count": primary,
        "cited_count": cited,
        "unique_domains": len(domains),
        "coverage_level": level,
        "coverage_label": label,
        "types": dict(types),
        "markets": markets,
        "warnings": warnings,
        **numeric_audit,
    }


def source_policy_overview() -> dict[str, Any]:
    return {
        "principle": "域名保守识别；标题不会让媒体转载自动升级为一手来源。",
        "tier_labels": {
            "1": "一手来源：监管、交易所、法定披露、央行、统计机构、国际组织或已登记公司官网",
            "2": "专业二手：已登记的专业媒体",
            "3": "待核验：尚未登记的公开网站",
            "4": "聚合/社区：只作线索，不替代原始文件",
            "5": "无效链接",
        },
        "official_sources": [dict(item) for item in OFFICIAL_SOURCES],
    }
