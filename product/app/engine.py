from __future__ import annotations

from typing import Literal

from .codex_engine import CodexResearchClient, CodexUnavailable
from .config import DEMO_MODE, RESEARCH_ENGINE_DEFAULT
from .research import ResearchClient, ResearchResult, ResearchUnavailable


EngineName = Literal["auto", "codex", "api"]


class DualResearchClient:
    def __init__(
        self,
        *,
        api_client: ResearchClient | None = None,
        codex_client: CodexResearchClient | None = None,
    ) -> None:
        self.api = api_client or ResearchClient()
        self.codex = codex_client or CodexResearchClient()

    async def status(self) -> dict:
        codex = (
            {
                "available": False,
                "logged_in": False,
                "auth_type": "",
                "plan_type": "",
                "detail": "演示模式不检查本机 Codex 登录",
            }
            if DEMO_MODE
            else (await self.codex.status()).as_dict()
        )
        return {
            "default": RESEARCH_ENGINE_DEFAULT
            if RESEARCH_ENGINE_DEFAULT in {"auto", "codex", "api"}
            else "auto",
            "codex": codex,
            "api": {
                "available": bool(self.api.api_key),
                "model": self.api.model,
                "detail": "OpenAI API Key 已配置" if self.api.api_key else "未配置 API Key",
            },
            "demo": DEMO_MODE,
        }

    async def run(
        self,
        instructions: str,
        prompt: str,
        *,
        depth: str = "balanced",
        engine: EngineName = "auto",
        use_web: bool = True,
    ) -> ResearchResult:
        if self.api.demo_mode:
            return await self.api.run(instructions, prompt, depth=depth)
        selected = self._normalize(engine)
        if selected == "api":
            return await self.api.run(instructions, prompt, depth=depth)
        if selected == "codex":
            return await self.codex.run(
                instructions,
                prompt,
                depth=depth,
                use_web=use_web,
            )
        codex_error: Exception | None = None
        status = await self.codex.status()
        if status.available and status.logged_in and status.auth_type == "chatgpt":
            try:
                return await self.codex.run(
                    instructions,
                    prompt,
                    depth=depth,
                    use_web=use_web,
                )
            except (CodexUnavailable, OSError) as exc:
                codex_error = exc
        if self.api.api_key:
            return await self.api.run(instructions, prompt, depth=depth)
        if codex_error:
            raise ResearchUnavailable(
                f"Codex 订阅引擎失败，且没有配置 API 备用引擎：{codex_error}"
            ) from codex_error
        raise ResearchUnavailable(
            "两个研究引擎都不可用：请先登录 Codex，或在首次配置中填写 OpenAI API Key。"
        )

    async def chat(
        self,
        instructions: str,
        messages: list[dict[str, str]],
        *,
        engine: EngineName = "auto",
        use_web: bool = True,
    ) -> ResearchResult:
        if self.api.demo_mode:
            return await self.api.chat(instructions, messages, use_web=use_web)
        selected = self._normalize(engine)
        if selected == "api":
            return await self.api.chat(instructions, messages, use_web=use_web)
        if selected == "codex":
            return await self.codex.chat(instructions, messages, use_web=use_web)
        codex_error: Exception | None = None
        status = await self.codex.status()
        if status.available and status.logged_in and status.auth_type == "chatgpt":
            try:
                return await self.codex.chat(
                    instructions,
                    messages,
                    use_web=use_web,
                )
            except (CodexUnavailable, OSError) as exc:
                codex_error = exc
        if self.api.api_key:
            return await self.api.chat(instructions, messages, use_web=use_web)
        if codex_error:
            raise ResearchUnavailable(
                f"Codex 订阅引擎失败，且没有配置 API 备用引擎：{codex_error}"
            ) from codex_error
        raise ResearchUnavailable(
            "两个研究引擎都不可用：请先登录 Codex，或在首次配置中填写 OpenAI API Key。"
        )

    @staticmethod
    def _normalize(engine: str) -> EngineName:
        value = (engine or "auto").strip().lower()
        return value if value in {"auto", "codex", "api"} else "auto"  # type: ignore[return-value]
