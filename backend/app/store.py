import hashlib
import json
import os
import secrets
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
            # 微信登录后会话归属到用户，换设备或清缓存后按 openid 找回报告
            "ALTER TABLE conversations ADD COLUMN openid TEXT",
            # 留资时用户选中的方案方向（JSON 数组）
            "ALTER TABLE leads ADD COLUMN directions TEXT",
            # 用户在历史报告里删掉的会话，只是不再列出，数据保留
            "ALTER TABLE conversations ADD COLUMN history_hidden INTEGER DEFAULT 0",
        ):
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS auth_tokens (
                token_hash TEXT PRIMARY KEY,
                openid TEXT,
                created_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_conversations_openid ON conversations (openid);
            -- 保存报告时手机号验证后建的账号：一个微信用户绑一个手机号
            CREATE TABLE IF NOT EXISTS users (
                openid TEXT PRIMARY KEY,
                phone TEXT,
                created_at INTEGER,
                updated_at INTEGER
            );
            -- 短信验证码只存哈希；attempts 记输错次数，used 后作废
            CREATE TABLE IF NOT EXISTS sms_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                openid TEXT,
                phone TEXT,
                code_hash TEXT,
                attempts INTEGER DEFAULT 0,
                used INTEGER DEFAULT 0,
                created_at INTEGER,
                expires_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_sms_codes_phone ON sms_codes (phone, created_at);
            """
        )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_auth_token(openid: str) -> str:
    """登录成功后发给前端的凭证；库里只存哈希，泄露数据库也拿不到可用的 token。"""
    token = secrets.token_urlsafe(32)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO auth_tokens (token_hash, openid, created_at) VALUES (?, ?, ?)",
            (_hash_token(token), openid, _now_ms()),
        )
    return token


def get_openid_by_token(token: str) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT openid FROM auth_tokens WHERE token_hash = ?", (_hash_token(token),)
        ).fetchone()
    return row["openid"] if row else None


def get_owner(conversation_id: str) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute("SELECT openid FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    return row["openid"] if row else None


def bind_owner(conversation_id: str, openid: str) -> None:
    """会话第一次带着登录态出现时归到这个用户；已有归属的不改。"""
    with _connect() as conn:
        conn.execute(
            "UPDATE conversations SET openid = ? WHERE id = ? AND openid IS NULL",
            (openid, conversation_id),
        )


def get_latest_reported_conversation(openid: str) -> Optional[str]:
    """这个用户最近一次生成过报告的会话。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT b.conversation_id FROM briefs b JOIN conversations c ON c.id = b.conversation_id "
            "WHERE c.openid = ? ORDER BY b.id DESC LIMIT 1",
            (openid,),
        ).fetchone()
    return row["conversation_id"] if row else None


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


def get_report_record(conversation_id: str) -> Optional[dict]:
    """最新一份报告连同生成时间、反馈状态，给"查看我的诊断报告"用。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT b.report_json, b.created_at, c.report_feedback, c.report_correction_count "
            "FROM briefs b JOIN conversations c ON c.id = b.conversation_id "
            "WHERE b.conversation_id = ? ORDER BY b.id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "report": json.loads(row["report_json"]),
        "created_at": row["created_at"],
        "feedback": row["report_feedback"],
        "corrected": bool(row["report_correction_count"]),
    }


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


def mark_ready(conversation_id: str) -> None:
    """问诊信息齐了，等用户点生成；报告这时还没生成。"""
    with _connect() as conn:
        conn.execute(
            "UPDATE conversations SET confirmation_status = 'awaiting' WHERE id = ? "
            "AND COALESCE(confirmation_status, '') NOT IN ('correcting', 'completed')",
            (conversation_id,),
        )


def get_confirmation_status(conversation_id: str) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT confirmation_status FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    return row["confirmation_status"] if row else None


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


def save_lead(conversation_id: str, channel: str, phone: str, directions: Optional[list[str]] = None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO leads (conversation_id, channel, phone, created_at, directions) VALUES (?, ?, ?, ?, ?)",
            (
                conversation_id,
                channel,
                phone,
                _now_ms(),
                json.dumps(directions, ensure_ascii=False) if directions is not None else None,
            ),
        )
        conn.execute(
            "UPDATE conversations SET intent = 1, contact = ? WHERE id = ?",
            (phone, conversation_id),
        )


# ---- 历史报告 ----
# "已保存"指保存报告时留下的那条留资（directions 非空，联系顾问的留资 directions 为空）

def list_saved_reports(openid: str) -> list[dict]:
    """这个用户保存过的报告，每个会话一条，按保存时间倒序；删掉的不列。"""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.report_feedback, c.report_correction_count,
                   (SELECT report_json FROM briefs b WHERE b.conversation_id = c.id
                     ORDER BY b.id DESC LIMIT 1) AS report_json,
                   (SELECT MAX(id) FROM leads l WHERE l.conversation_id = c.id
                     AND l.directions IS NOT NULL) AS save_id,
                   EXISTS(SELECT 1 FROM leads l WHERE l.conversation_id = c.id
                     AND l.directions IS NULL) AS consulted
            FROM conversations c
            WHERE c.openid = ? AND COALESCE(c.history_hidden, 0) = 0
            """,
            (openid,),
        ).fetchall()
        result = []
        for row in rows:
            if not row["save_id"] or not row["report_json"]:
                continue
            lead = conn.execute(
                "SELECT phone, directions, created_at FROM leads WHERE id = ?", (row["save_id"],)
            ).fetchone()
            result.append(
                {
                    "conversation_id": row["id"],
                    "save_id": row["save_id"],
                    "saved_at": lead["created_at"],
                    "phone": lead["phone"],
                    "directions": json.loads(lead["directions"]) if lead["directions"] else [],
                    "consulted": bool(row["consulted"]),
                    "feedback": row["report_feedback"],
                    "corrected": bool(row["report_correction_count"]),
                    "report": json.loads(row["report_json"]),
                }
            )
    result.sort(key=lambda r: r["save_id"], reverse=True)
    return result


def get_saved_phone(conversation_id: str) -> Optional[str]:
    """这份报告保存时验证的手机号；没保存过返回 None。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT phone FROM leads WHERE conversation_id = ? AND directions IS NOT NULL ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
    return row["phone"] if row else None


def hide_saved_report(conversation_id: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE conversations SET history_hidden = 1 WHERE id = ?", (conversation_id,))


def unhide_saved_report(conversation_id: str) -> None:
    """删掉后又重新保存同一份报告时，让它回到历史里。"""
    with _connect() as conn:
        conn.execute("UPDATE conversations SET history_hidden = 0 WHERE id = ?", (conversation_id,))


# ---- 短信验证码与账号 ----

def _hash_code(phone: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{code}".encode()).hexdigest()


def sms_send_block_reason(phone: str, openid: str, cooldown_ms: int, daily_limit: int) -> Optional[str]:
    """能发返回 None；同一手机号或同一微信用户冷却中返回 "cooldown"，当天发满返回 "daily_limit"。"""
    now = _now_ms()
    with _connect() as conn:
        last = conn.execute(
            "SELECT MAX(created_at) AS t FROM sms_codes WHERE phone = ? OR openid = ?", (phone, openid)
        ).fetchone()["t"]
        if last is not None and now - last < cooldown_ms:
            return "cooldown"
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM sms_codes WHERE (phone = ? OR openid = ?) AND created_at > ?",
            (phone, openid, now - 24 * 3600 * 1000),
        ).fetchone()["n"]
    return "daily_limit" if count >= daily_limit else None


def create_sms_code(phone: str, openid: str, code: Optional[str], ttl_ms: int) -> int:
    """记一条发送记录，同一手机号之前没用掉的作废。返回记录 id，发送失败时用来删掉。
    验证码由阿里云生成时 code 传 None，只记谁给哪个手机号要过码，用于频控和校验时核对是本人要的。"""
    now = _now_ms()
    with _connect() as conn:
        conn.execute("UPDATE sms_codes SET used = 1 WHERE phone = ? AND used = 0", (phone,))
        cur = conn.execute(
            "INSERT INTO sms_codes (openid, phone, code_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (openid, phone, _hash_code(phone, code) if code is not None else None, now, now + ttl_ms),
        )
        return int(cur.lastrowid)


def delete_sms_code(code_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sms_codes WHERE id = ?", (code_id,))


def get_active_sms_code(phone: str, openid: str, max_attempts: int) -> Optional[dict]:
    """这个微信用户给这个手机号要的最新一条、没用过、没过期、没错满次数的记录。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, code_hash, attempts FROM sms_codes WHERE phone = ? AND openid = ? AND used = 0 "
            "AND expires_at > ? ORDER BY id DESC LIMIT 1",
            (phone, openid, _now_ms()),
        ).fetchone()
    if not row or row["attempts"] >= max_attempts:
        return None
    return {"id": row["id"], "code_hash": row["code_hash"]}


def record_sms_code_failure(code_id: int, max_attempts: int) -> None:
    """输错一次；错满 max_attempts 次作废。"""
    with _connect() as conn:
        conn.execute(
            "UPDATE sms_codes SET attempts = attempts + 1, used = CASE WHEN attempts + 1 >= ? THEN 1 ELSE 0 END "
            "WHERE id = ?",
            (max_attempts, code_id),
        )


def mark_sms_code_used(code_id: int) -> None:
    with _connect() as conn:
        conn.execute("UPDATE sms_codes SET used = 1 WHERE id = ?", (code_id,))


def sms_code_matches(record: dict, phone: str, code: str) -> bool:
    """本地生成的验证码（开发模式）按哈希比对。"""
    return bool(record["code_hash"]) and secrets.compare_digest(record["code_hash"], _hash_code(phone, code))


def verify_sms_code(phone: str, openid: str, code: str, max_attempts: int) -> bool:
    """开发模式的本地校验：输错计次，错满 max_attempts 次作废，成功后作废。"""
    record = get_active_sms_code(phone, openid, max_attempts)
    if record is None:
        return False
    if not sms_code_matches(record, phone, code):
        record_sms_code_failure(record["id"], max_attempts)
        return False
    mark_sms_code_used(record["id"])
    return True


def bind_phone(openid: str, phone: str) -> None:
    now = _now_ms()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (openid, phone, created_at, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(openid) DO UPDATE SET phone = excluded.phone, updated_at = excluded.updated_at",
            (openid, phone, now, now),
        )


def get_user_phone(openid: str) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute("SELECT phone FROM users WHERE openid = ?", (openid,)).fetchone()
    return row["phone"] if row else None
