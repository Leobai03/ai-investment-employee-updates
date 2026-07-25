from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import WORKSPACE_DIR
from .database import list_hypotheses, memory_candidates, memory_counts


MEMORY_FILES = {
    "研究原则（长期有效）": "03_研究原则.md",
    "老板决策（已确认）": "04_决策日志.md",
    "待确认记忆（只能提问确认，不能当事实）": "05_待确认记忆.md",
    "老板纠正（优先级最高）": "06_老板纠正与反馈.md",
}

STOP_TERMS = {
    "什么",
    "怎么",
    "这个",
    "那个",
    "一下",
    "可以",
    "需要",
    "老板",
    "分析",
    "研究",
    "报告",
    "今天",
}

HYPOTHESIS_STATUS_NAMES = {
    "tracking": "持续核验",
    "supported": "暂获支持",
    "challenged": "受到挑战",
    "invalidated": "已经失效",
    "closed": "停止跟踪",
}


def build_memory_context(query: str, *, max_chars: int = 12_000) -> str:
    """Build a bounded memory packet instead of sending the full archive every turn."""

    sections: list[str] = []
    budget = max(2_000, max_chars)
    for label, filename in MEMORY_FILES.items():
        text = _read_memory_file(WORKSPACE_DIR / filename)
        if not text:
            continue
        excerpt = _meaningful_excerpt(text, 2_200 if "纠正" in label else 1_500)
        if excerpt:
            sections.append(f"## {label}\n{excerpt}")

    terms = _query_terms(query)
    relevant_hypotheses: list[dict[str, Any]] = []
    for hypothesis in list_hypotheses():
        searchable = " ".join(
            [
                hypothesis.get("company_name", ""),
                hypothesis.get("company_symbol", ""),
                hypothesis.get("title", ""),
                hypothesis.get("statement", ""),
                *hypothesis.get("support_evidence", []),
                *hypothesis.get("counter_evidence", []),
                *hypothesis.get("validation_signals", []),
                *hypothesis.get("invalidation_signals", []),
            ]
        ).lower()
        if not terms or any(term in searchable for term in terms):
            relevant_hypotheses.append(hypothesis)
    if relevant_hypotheses:
        rows = []
        for item in relevant_hypotheses[:8]:
            rows.append(
                f"- [{item.get('company_name')}｜"
                f"{HYPOTHESIS_STATUS_NAMES.get(item.get('status'), item.get('status'))}] "
                f"{item.get('title')}：{_compact(item.get('statement', ''), 260)}；"
                f"反方证据：{_compact('；'.join(item.get('counter_evidence', [])) or '尚未记录', 220)}；"
                f"失效信号：{_compact('；'.join(item.get('invalidation_signals', [])) or '尚未记录', 220)}"
            )
        sections.append(
            "## 与当前问题相关的研究假设\n"
            "假设不是事实；必须结合最新公开信息继续证实或证伪。\n"
            + "\n".join(rows)
        )

    candidates = memory_candidates(terms=terms)
    ranked = _rank_candidates(query, candidates)
    if ranked:
        rows: list[str] = []
        for item in ranked[:12]:
            content = _compact(item.get("content", ""), 520)
            if not content:
                continue
            rows.append(
                f"- [{item.get('created_at', '')[:10]}｜{item.get('source', 'local')}｜"
                f"{item.get('title') or item.get('kind', '记录')}] "
                f"{'老板：' if item.get('role') == 'user' else '研究员：'}{content}"
            )
        if rows:
            sections.append("## 与当前问题最相关的历史记录\n" + "\n".join(rows))

    packet = "\n\n".join(sections)
    if len(packet) > budget:
        packet = packet[:budget].rsplit("\n", 1)[0] + "\n- （其余历史仍保存在本机，当前回答未全部载入）"
    return (
        "以下内容来自老板的本机长期记忆。已确认偏好、决策和纠正可以作为上下文；"
        "“待确认记忆”绝不能直接当成事实。历史里的市场事实仍需按当前时间重新联网核验。\n\n"
        + (packet or "目前还没有与本题直接相关的长期记忆。")
    )


def memory_overview() -> dict[str, Any]:
    counts = memory_counts()
    files: dict[str, dict[str, Any]] = {}
    for label, filename in MEMORY_FILES.items():
        path = WORKSPACE_DIR / filename
        text = _read_memory_file(path)
        content_lines = _content_lines(text)
        files[filename] = {
            "label": label,
            "exists": path.exists(),
            "items": len(content_lines),
            "preview": _compact("；".join(content_lines[-3:]), 260),
        }
    counts["memory_files"] = files
    counts["storage"] = str(WORKSPACE_DIR)
    counts["explanation"] = (
        "完整对话全部留存；回答时只取老板说明书、纠正、决策和与当前问题相关的历史，"
        "避免把几万字全部塞进一次回答。"
    )
    return counts


def _rank_candidates(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = _query_terms(query)
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for index, item in enumerate(candidates):
        content = f"{item.get('title', '')} {item.get('content', '')}".lower()
        score = 0.0
        for term in terms:
            hits = content.count(term)
            if hits:
                score += min(hits, 3) * (2.5 if len(term) >= 4 else 1.4)
        if item.get("role") == "user":
            score += 0.35
        if item.get("kind") == "report":
            score += 0.2
        score += max(0.0, 1.0 - index / max(len(candidates), 1)) * 0.25
        if score > 0.25 or (not terms and index < 12):
            ranked.append((score, -index, item))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [item for _, _, item in ranked]


def _query_terms(query: str) -> list[str]:
    lowered = query.lower()
    terms = set(re.findall(r"[a-z0-9][a-z0-9._-]{1,30}", lowered))
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,20}", lowered):
        if chunk not in STOP_TERMS:
            terms.add(chunk)
        for width in (2, 3, 4):
            if len(chunk) < width:
                continue
            for start in range(len(chunk) - width + 1):
                term = chunk[start : start + width]
                if term not in STOP_TERMS:
                    terms.add(term)
    return sorted(terms, key=len, reverse=True)[:80]


def _read_memory_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return ""


def _meaningful_excerpt(text: str, max_chars: int) -> str:
    lines = _content_lines(text)
    if not lines:
        return ""
    joined = "\n".join(f"- {line}" for line in lines[-20:])
    return joined[-max_chars:]


def _content_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if (
            not line
            or line.startswith("#")
            or line.startswith(">")
            or re.fullmatch(r"[-| :]+", line)
        ):
            continue
        clean = re.sub(r"^[-*]\s*", "", line)
        if clean in {"暂无。", "暂无", "待补充。", "待补充"}:
            continue
        lines.append(clean)
    return lines


def _compact(value: str, length: int) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip()
    return clean if len(clean) <= length else clean[:length].rstrip() + "…"
