from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .config import DEMO_MODE, FIRST_SETUP_ENTRY, OPENAI_API_KEY, OPENAI_MODEL
from .source_quality import enrich_sources


class ResearchUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class ResearchResult:
    content: str
    sources: list[dict[str, str]]
    model: str
    engine: str = "api"


class ResearchClient:
    def __init__(
        self,
        *,
        client: Any | None = None,
        api_key: str = OPENAI_API_KEY,
        model: str = OPENAI_MODEL,
        demo_mode: bool = DEMO_MODE,
    ) -> None:
        self._client = client
        self.api_key = api_key
        self.model = model
        self.demo_mode = demo_mode

    @property
    def configured(self) -> bool:
        return bool(self.api_key) or self.demo_mode

    async def run(self, instructions: str, prompt: str, *, depth: str = "balanced") -> ResearchResult:
        if self.demo_mode:
            return self._demo_result(prompt)
        if not self.api_key:
            raise ResearchUnavailable(f"尚未配置 OpenAI API Key，请先运行“{FIRST_SETUP_ENTRY}”。")

        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:  # pragma: no cover - launcher installs it
                raise ResearchUnavailable("缺少 openai 依赖，请重新运行启动器安装依赖。") from exc
            self._client = AsyncOpenAI(api_key=self.api_key, timeout=180.0, max_retries=2)

        reasoning_effort = "medium" if depth == "deep" else "low"
        search_context_size = "high" if depth == "deep" else "medium"
        response = await self._client.responses.create(
            model=self.model,
            reasoning={"effort": reasoning_effort},
            instructions=instructions,
            input=prompt,
            tools=[{"type": "web_search", "search_context_size": search_context_size}],
            tool_choice="auto",
            include=["web_search_call.action.sources"],
            text={"verbosity": "medium"},
            safety_identifier="investment-research-local-owner",
            store=False,
        )
        payload = response.model_dump(mode="json")
        content, citation_sources = _extract_cited_text(payload)
        all_sources = _extract_all_sources(payload)
        sources = enrich_sources(_deduplicate_sources([*citation_sources, *all_sources]))
        if not content.strip():
            content = response.output_text or "研究没有返回可显示的正文。"
        return ResearchResult(
            content=content,
            sources=sources,
            model=payload.get("model", self.model),
            engine="api",
        )

    async def chat(
        self,
        instructions: str,
        messages: list[dict[str, str]],
        *,
        use_web: bool = True,
    ) -> ResearchResult:
        if self.demo_mode:
            last = messages[-1]["content"] if messages else "空白问题"
            return self._demo_result(last)
        if not self.api_key:
            raise ResearchUnavailable(f"尚未配置 OpenAI API Key，请先运行“{FIRST_SETUP_ENTRY}”。")
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:  # pragma: no cover
                raise ResearchUnavailable("缺少 openai 依赖，请重新运行启动器安装依赖。") from exc
            self._client = AsyncOpenAI(api_key=self.api_key, timeout=180.0, max_retries=2)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "reasoning": {"effort": "low"},
            "instructions": instructions,
            "input": messages[-24:],
            "text": {"verbosity": "medium"},
            "safety_identifier": "investment-research-local-owner",
            "store": False,
        }
        if use_web:
            kwargs.update(
                {
                    "tools": [{"type": "web_search", "search_context_size": "medium"}],
                    "tool_choice": "auto",
                    "include": ["web_search_call.action.sources"],
                }
            )
        response = await self._client.responses.create(**kwargs)
        payload = response.model_dump(mode="json")
        content, citation_sources = _extract_cited_text(payload)
        all_sources = _extract_all_sources(payload)
        sources = enrich_sources(_deduplicate_sources([*citation_sources, *all_sources]))
        if not content.strip():
            content = response.output_text or "研究没有返回可显示的正文。"
        return ResearchResult(
            content=content,
            sources=sources,
            model=payload.get("model", self.model),
            engine="api",
        )

    def _demo_result(self, prompt: str) -> ResearchResult:
        now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        content = f"""# 演示模式（不是实时研究）

当前为界面验收用的离线示例，时间：{now}。它不会引用或捏造今天的市场数据。

# 你提交的任务

{prompt[:900]}

# 正式运行后会发生什么

- 系统联网检索监管机构、交易所、公司公告和财报等来源。
- 关键事实旁边会出现可点击来源，结论会拆成事实、分析、反方证据和风险。
- 结果会保存到本机历史记录，但不会连接微信或证券账户。

# 当前缺失

请退出演示模式，并登录 Codex 或配置自己的 OpenAI API Key，才能生成实时报告。

本报告用于信息整理和研究辅助，不构成任何投资建议。"""
        return ResearchResult(
            content=content,
            sources=[],
            model="demo-no-live-data",
            engine="demo",
        )


def _extract_cited_text(payload: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    chunks: list[str] = []
    sources: list[dict[str, str]] = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if part.get("type") != "output_text":
                continue
            raw_text = part.get("text", "")
            annotations = [a for a in part.get("annotations", []) if a.get("type") == "url_citation"]
            cited_text, part_sources = _replace_citations(raw_text, annotations)
            chunks.append(cited_text)
            sources.extend(part_sources)
    return "\n\n".join(chunk for chunk in chunks if chunk), sources


def _replace_citations(text: str, annotations: list[dict[str, Any]]) -> tuple[str, list[dict[str, str]]]:
    replacements: list[tuple[int, int, str]] = []
    sources: list[dict[str, str]] = []
    for annotation in annotations:
        url = str(annotation.get("url", "")).strip()
        if not url.startswith(("https://", "http://")):
            continue
        title = str(annotation.get("title", "来源")).strip() or "来源"
        start = int(annotation.get("start_index", 0) or 0)
        end = int(annotation.get("end_index", start) or start)
        label = f"〔来源：{title}〕"
        replacement = f"[{label}]({url})"
        if 0 <= start <= end <= len(text):
            replacements.append((start, end, replacement))
        sources.append({"title": html.unescape(title), "url": url, "kind": "citation"})
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text, sources


def _extract_all_sources(payload: dict[str, Any]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for item in payload.get("output", []):
        if item.get("type") != "web_search_call":
            continue
        action = item.get("action") or {}
        for source in action.get("sources") or []:
            url = str(source.get("url", "")).strip()
            if not url.startswith(("https://", "http://")):
                continue
            sources.append(
                {
                    "title": str(source.get("title") or source.get("name") or url),
                    "url": url,
                    "kind": str(source.get("type") or "consulted"),
                }
            )
    return sources


def _deduplicate_sources(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for source in sources:
        url = source.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(source)
    return result
