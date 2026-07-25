from __future__ import annotations

import asyncio
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import CODEX_BIN, CODEX_MODEL, FIRST_SETUP_ENTRY, PRODUCT_DIR, codex_app_server_command
from .research import ResearchResult


class CodexUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class CodexStatus:
    available: bool
    logged_in: bool
    auth_type: str = ""
    plan_type: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "logged_in": self.logged_in,
            "auth_type": self.auth_type,
            "plan_type": self.plan_type,
            "detail": self.detail,
        }


class CodexResearchClient:
    """Use the local Codex App Server with the user's existing ChatGPT sign-in."""

    def __init__(
        self,
        *,
        command: list[str] | None = None,
        model: str = CODEX_MODEL,
        cwd: Path = PRODUCT_DIR,
        timeout_seconds: float = 240.0,
    ) -> None:
        self.command = command if command is not None else codex_app_server_command(CODEX_BIN)
        self.model = model
        self.cwd = cwd
        self.timeout_seconds = timeout_seconds
        self._status: CodexStatus | None = None
        self._status_at = 0.0

    async def status(self, *, force: bool = False) -> CodexStatus:
        loop = asyncio.get_running_loop()
        if not force and self._status and loop.time() - self._status_at < 60:
            return self._status
        try:
            result, _ = await asyncio.wait_for(
                self._run_session(account_only=True),
                timeout=10,
            )
            account = result.get("account") or {}
            status = CodexStatus(
                available=True,
                logged_in=bool(account),
                auth_type=str(account.get("type") or ""),
                plan_type=str(account.get("planType") or ""),
                detail=(
                    "已使用 ChatGPT 账号登录"
                    if account.get("type") == "chatgpt"
                    else "已使用 API Key 登录 Codex"
                    if account.get("type") == "apiKey"
                    else "Codex 尚未登录"
                ),
            )
        except (FileNotFoundError, PermissionError) as exc:
            status = CodexStatus(False, False, detail=f"没有找到 Codex：{exc}")
        except Exception as exc:
            status = CodexStatus(False, False, detail=f"Codex 检查失败：{str(exc)[:180]}")
        self._status = status
        self._status_at = loop.time()
        return status

    async def run(
        self,
        instructions: str,
        prompt: str,
        *,
        depth: str = "balanced",
        use_web: bool = True,
    ) -> ResearchResult:
        payload, messages = await self._run_session(
            instructions=instructions,
            prompt=prompt,
            depth=depth,
            use_web=use_web,
        )
        account = payload.get("account") or {}
        if account.get("type") != "chatgpt":
            raise CodexUnavailable(
                "Codex 当前不是使用 ChatGPT 订阅登录。请先在 Codex 执行 codex login 并选择 ChatGPT 登录。"
            )
        content = "\n\n".join(part.strip() for part in messages if part.strip()).strip()
        if not content:
            raise CodexUnavailable("Codex 已完成运行，但没有返回可显示的最终答复。")
        sources = _extract_markdown_sources(content)
        model = str(payload.get("model") or self.model or "codex-subscription")
        return ResearchResult(content=content, sources=sources, model=model, engine="codex")

    async def chat(
        self,
        instructions: str,
        messages: list[dict[str, str]],
        *,
        use_web: bool = True,
    ) -> ResearchResult:
        history = messages[-24:]
        rendered = []
        for message in history:
            role = "老板" if message.get("role") == "user" else "AI 投研员工"
            rendered.append(f"{role}：{message.get('content', '').strip()}")
        prompt = (
            "下面是网页投研工作台保存的连续对话。请直接回答最后一条老板消息，"
            "不要复述全部历史。\n\n" + "\n\n".join(rendered)
        )
        return await self.run(
            instructions,
            prompt,
            depth="balanced",
            use_web=use_web,
        )

    async def read_workspace_threads(
        self,
        workspace: Path,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Read only Codex threads whose cwd exactly matches this product workspace."""

        if not self.command:
            raise FileNotFoundError(f"未找到 Codex CLI，请先运行“{FIRST_SETUP_ENTRY}”。")
        proc = await asyncio.create_subprocess_exec(
            *self.command,
            cwd=str(self.cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        threads: list[dict[str, Any]] = []
        request_id = 10
        try:
            await self._send(
                proc,
                {
                    "method": "initialize",
                    "id": 1,
                    "params": {
                        "clientInfo": {
                            "name": "tiance_ai_research_archive",
                            "title": "天策 AI 投研档案同步",
                            "version": "0.11.3",
                        }
                    },
                },
            )
            await self._wait_for_response(proc, 1)
            await self._send(proc, {"method": "initialized", "params": {}})
            await self._send(proc, {"method": "account/read", "id": 2, "params": {}})
            account_response = await self._wait_for_response(proc, 2)
            account = (account_response.get("result") or {}).get("account") or {}
            if account.get("type") != "chatgpt":
                raise CodexUnavailable("Codex 对话同步需要先使用 ChatGPT 账号登录 Codex。")

            for archived in (False, True):
                cursor: str | None = None
                while len(threads) < limit:
                    params: dict[str, Any] = {
                        "cwd": str(workspace.resolve()),
                        "archived": archived,
                        "limit": min(100, limit - len(threads)),
                        "sortKey": "updated_at",
                        "sortDirection": "desc",
                    }
                    if cursor:
                        params["cursor"] = cursor
                    request_id += 1
                    await self._send(
                        proc,
                        {"method": "thread/list", "id": request_id, "params": params},
                    )
                    response = await self._wait_for_response(proc, request_id)
                    page = response.get("result") or {}
                    for summary in page.get("data") or []:
                        thread_id = str(summary.get("id") or "")
                        if not thread_id:
                            continue
                        request_id += 1
                        await self._send(
                            proc,
                            {
                                "method": "thread/read",
                                "id": request_id,
                                "params": {"threadId": thread_id, "includeTurns": True},
                            },
                        )
                        read_response = await self._wait_for_response(proc, request_id)
                        thread = (read_response.get("result") or {}).get("thread") or {}
                        if thread:
                            thread["_archived"] = archived
                            threads.append(thread)
                        if len(threads) >= limit:
                            break
                    cursor = page.get("nextCursor")
                    if not cursor:
                        break
            return threads
        except asyncio.TimeoutError as exc:
            raise CodexUnavailable("Codex 对话档案同步超时，请稍后手动重试。") from exc
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()

    async def _run_session(
        self,
        *,
        account_only: bool = False,
        instructions: str = "",
        prompt: str = "",
        depth: str = "balanced",
        use_web: bool = True,
    ) -> tuple[dict[str, Any], list[str]]:
        if not self.command:
            raise FileNotFoundError(f"未找到 Codex CLI，请先运行“{FIRST_SETUP_ENTRY}”。")
        proc = await asyncio.create_subprocess_exec(
            *self.command,
            cwd=str(self.cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        account: dict[str, Any] = {}
        model = self.model
        agent_messages: list[str] = []
        try:
            await self._send(
                proc,
                {
                    "method": "initialize",
                    "id": 1,
                    "params": {
                        "clientInfo": {
                            "name": "tiance_ai_research_desk",
                            "title": "天策 AI 投研数字员工",
                            "version": "0.11.3",
                        }
                    },
                },
            )
            await self._wait_for_response(proc, 1)
            await self._send(proc, {"method": "initialized", "params": {}})
            await self._send(proc, {"method": "account/read", "id": 2, "params": {}})
            account_response = await self._wait_for_response(proc, 2)
            account = (account_response.get("result") or {}).get("account") or {}
            if account_only:
                return {"account": account}, []
            if account.get("type") != "chatgpt":
                raise CodexUnavailable(
                    "没有检测到 ChatGPT 订阅登录。请打开 Codex 完成 ChatGPT 登录后重试。"
                )

            developer_instructions = (
                instructions.strip()
                + "\n\n你正在为本机网页投研工作台提供研究结果。"
                "只输出给老板看的最终答复，不解释代码，不修改文件，不运行本地命令。"
                "不得给出个性化买入、卖出、加仓、减仓、目标价或收益保证。"
            )
            thread_params: dict[str, Any] = {
                "cwd": str(self.cwd),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "ephemeral": True,
                "developerInstructions": developer_instructions,
                "config": {"web_search": "live" if use_web else "disabled"},
            }
            if self.model:
                thread_params["model"] = self.model
            await self._send(
                proc,
                {"method": "thread/start", "id": 3, "params": thread_params},
            )
            thread_response = await self._wait_for_response(proc, 3)
            thread_result = thread_response.get("result") or {}
            thread = thread_result.get("thread") or {}
            thread_id = str(thread.get("id") or "")
            model = str(thread_result.get("model") or self.model or "codex-subscription")
            if not thread_id:
                raise CodexUnavailable("Codex 没有返回对话线程。")

            turn_params: dict[str, Any] = {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "effort": "medium" if depth == "deep" else "low",
            }
            await self._send(
                proc,
                {"method": "turn/start", "id": 4, "params": turn_params},
            )
            completed = False
            while not completed:
                message = await self._read_message(proc)
                if message.get("id") == 4 and message.get("error"):
                    raise CodexUnavailable(_rpc_error(message))
                method = message.get("method")
                params = message.get("params") or {}
                if method == "item/completed":
                    item = params.get("item") or {}
                    if item.get("type") == "agentMessage" and item.get("text"):
                        agent_messages.append(str(item["text"]))
                elif method == "turn/completed":
                    turn = params.get("turn") or {}
                    status = str(turn.get("status") or "")
                    if status not in {"completed", ""}:
                        error = turn.get("error") or {}
                        raise CodexUnavailable(
                            str(error.get("message") or error or f"Codex 运行状态：{status}")
                        )
                    completed = True
                elif "id" in message and "method" in message:
                    await self._decline_server_request(proc, message)
            return {"account": account, "model": model}, agent_messages
        except asyncio.TimeoutError as exc:
            raise CodexUnavailable("Codex 运行超时，请稍后重试或切换 OpenAI API 引擎。") from exc
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()

    async def _read_message(self, proc: asyncio.subprocess.Process) -> dict[str, Any]:
        assert proc.stdout is not None
        while True:
            line = await asyncio.wait_for(
                proc.stdout.readline(),
                timeout=self.timeout_seconds,
            )
            if not line:
                raise CodexUnavailable("Codex App Server 意外退出。")
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(message, dict):
                return message

    async def _wait_for_response(
        self,
        proc: asyncio.subprocess.Process,
        request_id: int,
    ) -> dict[str, Any]:
        while True:
            message = await self._read_message(proc)
            if message.get("id") != request_id:
                if "id" in message and "method" in message:
                    await self._decline_server_request(proc, message)
                continue
            if message.get("error"):
                raise CodexUnavailable(_rpc_error(message))
            return message

    async def _send(
        self,
        proc: asyncio.subprocess.Process,
        message: dict[str, Any],
    ) -> None:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        await proc.stdin.drain()

    async def _decline_server_request(
        self,
        proc: asyncio.subprocess.Process,
        message: dict[str, Any],
    ) -> None:
        await self._send(
            proc,
            {
                "id": message["id"],
                "error": {
                    "code": -32000,
                    "message": "网页投研工作台以只读模式运行，不批准额外操作。",
                },
            },
        )


def _rpc_error(message: dict[str, Any]) -> str:
    error = message.get("error") or {}
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error)


def _extract_markdown_sources(content: str) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for title, url in re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", content):
        clean_url = html.unescape(url.rstrip(".,;，。；"))
        if clean_url in seen:
            continue
        seen.add(clean_url)
        sources.append(
            {
                "title": html.unescape(re.sub(r"\s+", " ", title).strip()) or clean_url,
                "url": clean_url,
                "kind": "codex-citation",
            }
        )
    return sources
