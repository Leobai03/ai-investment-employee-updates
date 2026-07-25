from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from .codex_engine import CodexResearchClient, _extract_markdown_sources
from .config import PRODUCT_DIR
from .database import (
    get_setting,
    save_setting,
    upsert_external_conversation,
    upsert_external_message,
)


class CodexArchiveSync:
    """Mirror visible messages from this product's Codex workspace into the web archive."""

    SETTING_KEY = "codex_archive_sync"

    def __init__(
        self,
        client: CodexResearchClient,
        *,
        workspace: Path = PRODUCT_DIR,
    ) -> None:
        self.client = client
        self.workspace = workspace.resolve()
        self._lock = asyncio.Lock()

    def status(self) -> dict[str, Any]:
        default = {
            "enabled": True,
            "workspace": str(self.workspace),
            "last_sync_at": "",
            "last_threads": 0,
            "last_imported": 0,
            "last_error": "",
        }
        saved = get_setting(self.SETTING_KEY, {})
        if isinstance(saved, dict):
            default.update(saved)
        return default

    async def sync(self) -> dict[str, Any]:
        if self._lock.locked():
            state = self.status()
            state["running"] = True
            return state
        async with self._lock:
            state = self.status()
            try:
                threads = await self.client.read_workspace_threads(self.workspace)
                imported = 0
                for thread in threads:
                    imported += self._import_thread(thread)
                state.update(
                    {
                        "enabled": True,
                        "workspace": str(self.workspace),
                        "last_sync_at": _now(),
                        "last_threads": len(threads),
                        "last_imported": imported,
                        "last_error": "",
                        "running": False,
                    }
                )
            except Exception as exc:
                state.update(
                    {
                        "enabled": True,
                        "workspace": str(self.workspace),
                        "last_sync_at": _now(),
                        "last_error": str(exc)[:500],
                        "running": False,
                    }
                )
            save_setting(self.SETTING_KEY, state)
            return state

    def _import_thread(self, thread: dict[str, Any]) -> int:
        thread_id = str(thread.get("id") or "")
        if not thread_id or thread.get("ephemeral"):
            return 0
        try:
            cwd = Path(str(thread.get("cwd") or "")).resolve()
        except (OSError, ValueError):
            return 0
        if cwd != self.workspace:
            return 0

        visible: list[dict[str, Any]] = []
        for turn_index, turn in enumerate(thread.get("turns") or []):
            started = _timestamp(turn.get("startedAt"), thread.get("createdAt"))
            completed = _timestamp(turn.get("completedAt"), turn.get("startedAt"), thread.get("updatedAt"))
            for item_index, item in enumerate(turn.get("items") or []):
                item_type = item.get("type")
                if item_type == "userMessage":
                    content = _user_message_text(item)
                    role = "user"
                    created_at = started
                elif item_type == "agentMessage":
                    content = str(item.get("text") or "").strip()
                    role = "assistant"
                    created_at = completed
                else:
                    continue
                if not content:
                    continue
                item_id = str(item.get("id") or f"{turn_index}-{item_index}-{role}")
                visible.append(
                    {
                        "external_id": f"codex:{thread_id}:{item_id}",
                        "role": role,
                        "content": content,
                        "created_at": created_at,
                    }
                )
        if not visible:
            return 0

        conversation_id = f"codex-{thread_id}"
        title = (
            str(thread.get("name") or "").strip()
            or str(thread.get("preview") or "").strip()
            or visible[0]["content"]
        )
        created_at = _timestamp(thread.get("createdAt")) or visible[0]["created_at"]
        updated_at = _timestamp(thread.get("updatedAt")) or visible[-1]["created_at"]
        status_value = thread.get("status")
        status = (
            str(status_value.get("type") or "active")
            if isinstance(status_value, dict)
            else str(status_value or "active")
        )
        if thread.get("_archived"):
            status = "archived"
        upsert_external_conversation(
            conversation_id,
            title,
            source="codex",
            created_at=created_at,
            updated_at=updated_at,
            status=status,
        )

        imported = 0
        model = str(thread.get("model") or thread.get("modelProvider") or "codex-subscription")
        for message in visible:
            _, created = upsert_external_message(
                conversation_id,
                message["role"],
                message["content"],
                external_id=message["external_id"],
                created_at=message["created_at"],
                sources=(
                    _extract_markdown_sources(message["content"])
                    if message["role"] == "assistant"
                    else []
                ),
                model=model if message["role"] == "assistant" else "",
                metadata={
                    "engine": "codex",
                    "synced": True,
                    "codex_thread_id": thread_id,
                },
            )
            imported += int(created)
        return imported


def _user_message_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for entry in item.get("content") or []:
        kind = entry.get("type")
        if kind == "text" and entry.get("text"):
            parts.append(str(entry["text"]).strip())
        elif kind in {"image", "localImage"}:
            parts.append("[老板发送了一张图片]")
    return "\n\n".join(part for part in parts if part).strip()


def _timestamp(*values: Any) -> str:
    for value in values:
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")
        text = str(value)
        if text.isdigit():
            return datetime.fromtimestamp(int(text)).astimezone().isoformat(timespec="seconds")
        return text
    return _now()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
