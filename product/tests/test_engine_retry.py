from __future__ import annotations

import asyncio

from app.codex_engine import CodexUnavailable
from app.engine import DualResearchClient
from app.research import ResearchResult


def test_transient_codex_disconnect_is_retried_once(monkeypatch) -> None:
    attempts = 0

    async def no_sleep(_seconds: float) -> None:
        return None

    async def operation() -> ResearchResult:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise CodexUnavailable(
                "stream disconnected before completion: Transport error"
            )
        return ResearchResult(
            content="恢复成功",
            sources=[],
            model="test",
            engine="codex",
        )

    monkeypatch.setattr("app.engine.asyncio.sleep", no_sleep)
    client = DualResearchClient()
    result = asyncio.run(client._with_codex_retry(operation))

    assert attempts == 2
    assert result.content == "恢复成功"


def test_non_transient_codex_error_is_not_retried(monkeypatch) -> None:
    attempts = 0

    async def no_sleep(_seconds: float) -> None:
        return None

    async def operation() -> ResearchResult:
        nonlocal attempts
        attempts += 1
        raise CodexUnavailable("Codex 尚未登录")

    monkeypatch.setattr("app.engine.asyncio.sleep", no_sleep)
    client = DualResearchClient()

    try:
        asyncio.run(client._with_codex_retry(operation))
    except CodexUnavailable as exc:
        assert "尚未登录" in str(exc)
    else:
        raise AssertionError("Expected CodexUnavailable")

    assert attempts == 1
