import json
import os
import sqlite3
import time
import uuid
from typing import Optional

from .config import get_settings


def _now_ms() -> int:
    return int(time.time() * 1000)


def _connect() -> sqlite3.Connection:
    path = get_settings().db_path
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                created_at INTEGER,
                status TEXT DEFAULT 'open',
                channel TEXT,
                external_id TEXT,
                contact TEXT,
                intent INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT,
                role TEXT,
                content TEXT,
                created_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS briefs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT,
                report_json TEXT,
                created_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT,
                channel TEXT,
                phone TEXT,
                created_at INTEGER
            );
            """
        )


def get_or_create_conversation(conversation_id: Optional[str], channel: str = "h5") -> str:
    with _connect() as conn:
        if conversation_id:
            row = conn.execute(
                "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if row:
                return conversation_id
        new_id = conversation_id or uuid.uuid4().hex
        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, created_at, channel) VALUES (?, ?, ?)",
            (new_id, _now_ms(), channel),
        )
        return new_id


def add_message(conversation_id: str, role: str, content: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, _now_ms()),
        )


def get_history(conversation_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def save_report(conversation_id: str, report: dict) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO briefs (conversation_id, report_json, created_at) VALUES (?, ?, ?)",
            (conversation_id, json.dumps(report, ensure_ascii=False), _now_ms()),
        )
        conn.execute(
            "UPDATE conversations SET status = 'reported' WHERE id = ?", (conversation_id,)
        )


def save_lead(conversation_id: str, channel: str, phone: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO leads (conversation_id, channel, phone, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, channel, phone, _now_ms()),
        )
        conn.execute(
            "UPDATE conversations SET intent = 1, contact = ? WHERE id = ?",
            (phone, conversation_id),
        )
