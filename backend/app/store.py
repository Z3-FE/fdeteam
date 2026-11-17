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
        # 老库补列：已经用了几次"快捷选项兜底"
        try:
            conn.execute("ALTER TABLE conversations ADD COLUMN suggest_fallbacks INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        for sql in (
            "ALTER TABLE conversations ADD COLUMN pending_report_json TEXT",
            "ALTER TABLE conversations ADD COLUMN confirmation_status TEXT",
            "ALTER TABLE conversations ADD COLUMN understanding_corrected INTEGER DEFAULT 0",
            "ALTER TABLE conversations ADD COLUMN report_feedback TEXT",
            "ALTER TABLE conversations ADD COLUMN report_correction_count INTEGER DEFAULT 0",
            "ALTER TABLE conversations ADD COLUMN report_correction_text TEXT",
        ):
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass


def use_suggest_fallback(conversation_id: str, limit: int) -> bool:
    """占用一次兜底额度；该会话已用满 limit 次时返回 False。"""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE conversations SET suggest_fallbacks = COALESCE(suggest_fallbacks, 0) + 1 "
            "WHERE id = ? AND COALESCE(suggest_fallbacks, 0) < ?",
            (conversation_id, limit),
        )
        return cur.rowcount == 1


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
            "UPDATE conversations SET status = 'reported', pending_report_json = NULL, "
            "confirmation_status = 'completed' WHERE id = ?", (conversation_id,)
        )


def get_latest_report(conversation_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT report_json FROM briefs WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
    return json.loads(row["report_json"]) if row else None


def save_report_feedback(conversation_id: str, feedback: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE conversations SET report_feedback = ? WHERE id = ?",
            (feedback, conversation_id),
        )


def begin_report_correction(conversation_id: str, correction: str) -> bool:
    """报告最多纠正一次；先占位，失败时由 release_report_correction 归还。"""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE conversations SET report_feedback = 'inaccurate', report_correction_count = 1, "
            "report_correction_text = ? WHERE id = ? AND COALESCE(report_correction_count, 0) = 0",
            (correction, conversation_id),
        )
        return cur.rowcount == 1


def release_report_correction(conversation_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE conversations SET report_correction_count = 0, report_correction_text = NULL "
            "WHERE id = ? AND report_feedback = 'inaccurate'",
            (conversation_id,),
        )


def save_pending_report(conversation_id: str, report: dict) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE conversations SET pending_report_json = ?, confirmation_status = 'awaiting' WHERE id = ?",
            (json.dumps(report, ensure_ascii=False), conversation_id),
        )


def get_pending_report(conversation_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT pending_report_json FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    if not row or not row["pending_report_json"]:
        return None
    return json.loads(row["pending_report_json"])


def use_understanding_correction(conversation_id: str) -> bool:
    """理解纠正最多提交一次。"""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE conversations SET understanding_corrected = 1, confirmation_status = 'correcting' "
            "WHERE id = ? AND confirmation_status = 'awaiting' "
            "AND COALESCE(understanding_corrected, 0) = 0",
            (conversation_id,),
        )
        return cur.rowcount == 1


def release_understanding_correction(conversation_id: str) -> None:
    """模型生成失败时归还纠正机会，让用户可以重试。"""
    with _connect() as conn:
        conn.execute(
            "UPDATE conversations SET understanding_corrected = 0, confirmation_status = 'awaiting' "
            "WHERE id = ? AND confirmation_status = 'correcting'",
            (conversation_id,),
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
