#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path


def decode(value: str) -> str:
    return base64.b64decode(value.encode("ascii")).decode("utf-8")


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def fallback_record(
    root: Path,
    conversation_id: str,
    title: str,
    user_text: str,
    assistant_text: str,
    sources: list[dict[str, str]],
) -> None:
    data_dir = root / "投研数字员工" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    database = data_dir / "research.db"
    conn = sqlite3.connect(database, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'web',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources_json TEXT NOT NULL DEFAULT '[]',
                model TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        timestamp = now()
        conn.execute(
            """INSERT INTO conversations(id, title, source, status, created_at, updated_at)
               VALUES (?, ?, 'codex', 'active', ?, ?)
               ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at""",
            (conversation_id, title[:100] or "Codex 对话", timestamp, timestamp),
        )
        conn.execute(
            """INSERT INTO messages(
                   conversation_id, role, content, sources_json, model, metadata_json, created_at
               ) VALUES (?, 'user', ?, '[]', '', '{"source":"codex"}', ?)""",
            (conversation_id, user_text, timestamp),
        )
        conn.execute(
            """INSERT INTO messages(
                   conversation_id, role, content, sources_json, model, metadata_json, created_at
               ) VALUES (?, 'assistant', ?, ?, 'codex', '{"source":"codex"}', ?)""",
            (conversation_id, assistant_text, json.dumps(sources, ensure_ascii=False), timestamp),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="把一次 Codex 投研对话写入本地统一档案")
    parser.add_argument("--path", default=".")
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--title", default="Codex 对话")
    parser.add_argument("--user-base64", required=True)
    parser.add_argument("--assistant-base64", required=True)
    parser.add_argument("--sources-base64", default="")
    args = parser.parse_args()

    root = Path(args.path).expanduser().resolve()
    conversation_id = args.conversation_id.strip() or f"codex-{uuid.uuid4().hex}"
    user_text = decode(args.user_base64)
    assistant_text = decode(args.assistant_base64)
    sources = json.loads(decode(args.sources_base64)) if args.sources_base64 else []

    if (root / "app" / "database.py").exists():
        sys.path.insert(0, str(root))
        from app.database import (
            add_message,
            create_conversation,
            init_db,
            sync_memory_files_to_db,
        )

        init_db()
        sync_memory_files_to_db()
        create_conversation(args.title, source="codex", conversation_id=conversation_id)
        add_message(conversation_id, "user", user_text, metadata={"source": "codex"})
        add_message(
            conversation_id,
            "assistant",
            assistant_text,
            sources=sources,
            model="codex",
            metadata={"source": "codex"},
        )
    else:
        fallback_record(
            root,
            conversation_id,
            args.title,
            user_text,
            assistant_text,
            sources,
        )

    print(conversation_id)


if __name__ == "__main__":
    main()
