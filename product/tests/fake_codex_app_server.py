from __future__ import annotations

import json
import sys


list_cwd = ""


def send(message: dict) -> None:
    sys.stdout.buffer.write(
        (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
    )
    sys.stdout.buffer.flush()


for raw_line in sys.stdin:
    try:
        request = json.loads(raw_line)
    except json.JSONDecodeError:
        continue
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        send({"id": request_id, "result": {"serverInfo": {"name": "fake-codex"}}})
    elif method == "account/read":
        send(
            {
                "id": request_id,
                "result": {
                    "account": {
                        "type": "chatgpt",
                        "email": "owner@example.com",
                        "planType": "plus",
                    }
                },
            }
        )
    elif method == "thread/start":
        send(
            {
                "id": request_id,
                "result": {
                    "thread": {"id": "thread-test"},
                    "model": "gpt-codex-test",
                },
            }
        )
    elif method == "thread/list":
        list_cwd = str((request.get("params") or {}).get("cwd") or "")
        if (request.get("params") or {}).get("archived"):
            send({"id": request_id, "result": {"data": [], "nextCursor": None}})
        else:
            send(
                {
                    "id": request_id,
                    "result": {
                        "data": [
                            {
                                "id": "thread-archive-test",
                                "cwd": list_cwd,
                                "preview": "研究腾讯的长期现金流",
                                "createdAt": 1784851200,
                                "updatedAt": 1784851260,
                                "turns": [],
                            }
                        ],
                        "nextCursor": None,
                    },
                }
            )
    elif method == "thread/read":
        send(
            {
                "id": request_id,
                "result": {
                    "thread": {
                        "id": "thread-archive-test",
                        "cwd": list_cwd,
                        "name": "腾讯长期研究",
                        "preview": "研究腾讯的长期现金流",
                        "createdAt": 1784851200,
                        "updatedAt": 1784851260,
                        "ephemeral": False,
                        "modelProvider": "openai",
                        "status": {"type": "idle"},
                        "turns": [
                            {
                                "id": "turn-archive-test",
                                "startedAt": 1784851200,
                                "completedAt": 1784851260,
                                "status": "completed",
                                "items": [
                                    {
                                        "id": "user-item-test",
                                        "type": "userMessage",
                                        "content": [{"type": "text", "text": "请记住我长期关注腾讯现金流"}],
                                    },
                                    {
                                        "id": "tool-item-test",
                                        "type": "commandExecution",
                                        "command": "ignored",
                                    },
                                    {
                                        "id": "agent-item-test",
                                        "type": "agentMessage",
                                        "text": "已记录。[公司公告](https://example.com/tencent)",
                                    },
                                ],
                            }
                        ],
                    }
                },
            }
        )
    elif method == "turn/start":
        send({"id": request_id, "result": {"turn": {"id": "turn-test"}}})
        send(
            {
                "method": "item/completed",
                "params": {
                    "item": {
                        "type": "agentMessage",
                        "text": "Codex 双引擎测试通过。[官方来源](https://example.com/source)",
                    }
                },
            }
        )
        send(
            {
                "method": "turn/completed",
                "params": {"turn": {"id": "turn-test", "status": "completed"}},
            }
        )
