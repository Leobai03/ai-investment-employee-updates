#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
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
                external_id TEXT NOT NULL DEFAULT '',
                sources_json TEXT NOT NULL DEFAULT '[]',
                model TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
        if "external_id" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN external_id TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_external
               ON messages(external_id) WHERE external_id != ''"""
        )
        timestamp = now()
        user_external = _external_id(conversation_id, "user", user_text)
        assistant_external = _external_id(conversation_id, "assistant", assistant_text)
        conn.execute(
            """INSERT INTO conversations(id, title, source, status, created_at, updated_at)
               VALUES (?, ?, 'codex', 'active', ?, ?)
               ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at""",
            (conversation_id, title[:100] or "Codex 对话", timestamp, timestamp),
        )
        conn.execute(
            """INSERT INTO messages(
                   conversation_id, role, content, external_id, sources_json, model,
                   metadata_json, created_at
               ) VALUES (?, 'user', ?, ?, '[]', '', '{"source":"codex"}', ?)
               ON CONFLICT(external_id) WHERE external_id != '' DO UPDATE SET
                   content=excluded.content, created_at=excluded.created_at""",
            (conversation_id, user_text, user_external, timestamp),
        )
        conn.execute(
            """INSERT INTO messages(
                   conversation_id, role, content, external_id, sources_json, model,
                   metadata_json, created_at
               ) VALUES (?, 'assistant', ?, ?, ?, 'codex', '{"source":"codex"}', ?)
               ON CONFLICT(external_id) WHERE external_id != '' DO UPDATE SET
                   content=excluded.content, sources_json=excluded.sources_json,
                   created_at=excluded.created_at""",
            (
                conversation_id,
                assistant_text,
                assistant_external,
                json.dumps(sources, ensure_ascii=False),
                timestamp,
            ),
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
            create_conversation,
            init_db,
            sync_memory_files_to_db,
            upsert_external_message,
        )

        init_db()
        sync_memory_files_to_db()
        create_conversation(args.title, source="codex", conversation_id=conversation_id)
        timestamp = now()
        upsert_external_message(
            conversation_id,
            "user",
            user_text,
            external_id=_external_id(conversation_id, "user", user_text),
            created_at=timestamp,
            metadata={"source": "codex", "manual_archive": True},
        )
        upsert_external_message(
            conversation_id,
            "assistant",
            assistant_text,
            external_id=_external_id(conversation_id, "assistant", assistant_text),
            created_at=timestamp,
            sources=sources,
            model="codex",
            metadata={"source": "codex", "manual_archive": True},
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


def _external_id(conversation_id: str, role: str, content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:20]
    return f"manual:{conversation_id}:{role}:{digest}"


if __name__ == "__main__":
    main()
