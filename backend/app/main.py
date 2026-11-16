import logging
import re
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import llm, store
from .config import get_settings
from .schemas import (
    ChatMessageResponse,
    ChatReportResponse,
    ChatRequest,
    LeadRequest,
    OkResponse,
    Report,
)

logger = logging.getLogger("qb")
logging.basicConfig(level=logging.INFO)

OPENING_MESSAGE = (
    "你好，我帮你把公司里最头疼的问题理清楚，免费的。咱们一步步来，你用大白话说就行"
    "——最近有哪件事，让你觉得特别费时间或费钱？"
)

app = FastAPI(title="问题梳理 · 业务问诊 API")

PROFILE_KEYS = ("industry", "teamSize", "budget", "urgency", "decisionMaker", "currentTools")
SUGGEST_FALLBACK_LIMIT = 3
# 用户说到第几句还没出报告，就强制模型这一轮收尾（兜底）
MAX_USER_TURNS = 8

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    store.init_db()
    logger.info("DB ready. MOCK=%s model=%s", settings.mock, settings.model_name)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "mock": settings.mock, "model": settings.model_name}


def _normalize_report(raw: dict) -> dict:
    dirs = []
    for d in (raw.get("directions") or [])[:3]:
        conf = d.get("confidence", "中")
        if conf not in ("高", "中", "低"):
            conf = "中"
        dirs.append(
            {
                "title": (str(d.get("title", "")).strip() or "未命名方向"),
                "confidence": conf,
                "summary": str(d.get("summary", "")).strip(),
                "causes": [str(c) for c in (d.get("causes") or [])],
                "actions": [str(a) for a in (d.get("actions") or [])],
            }
        )
    if not dirs:
        dirs = [{"title": "未命名方向", "confidence": "中", "summary": "", "causes": [], "actions": []}]
    raw_profile = raw.get("profile") if isinstance(raw.get("profile"), dict) else {}
    profile = {k: (str(raw_profile.get(k, "")).strip() or "未知") for k in PROFILE_KEYS}
    cost_value = str(raw.get("costValue", "")).strip()
    cost_unit = str(raw.get("costUnit", "")).strip()
    cost_note = _monthly_cost_note(cost_value, cost_unit) or str(raw.get("costNote", "")).strip()
    return {
        "sceneLabel": str(raw.get("sceneLabel", "")).strip(),
        "painPoint": str(raw.get("painPoint", "")).strip(),
        "painQuote": str(raw.get("painQuote", "")).strip(),
        "costValue": cost_value,
        "costUnit": cost_unit,
        "costNote": cost_note,
        "directions": dirs,
        "openQuestions": [str(q).strip() for q in (raw.get("openQuestions") or []) if str(q).strip()][:3],
        # profile 只入库给 FDE 看，不返回给用户端
        "profile": profile,
    }


# 模型偶尔只吐一行 @@SUGGEST、正文为空：重试一次仍为空时用这句兜底，保证用户看到的是个问题
EMPTY_REPLY_FALLBACK = "嗯，我记下了。这块你能再多说一点吗？"

# 提示词里禁问、但模型仍常问的几类问题。只匹配 AI 最后那个问句，命中就带纠正说明重答一次。
# 注意：没有"格式"这一类——问资料用什么形式维护（PDF/在线文档）是允许的，它决定系统怎么对接。
BANNED_QUESTION_PATTERNS = [
    ("设备", r"电脑|手机|设备"),
    ("东西在哪", r"放在哪|放哪|存在哪|记在哪|在哪里|找得到|找到"),
    ("管理动作", r"培训|更新.{0,6}手册|手册.{0,6}更新|整理成?\s*FAQ|FAQ|定.{0,2}规矩|专人负责"),
    ("预算/急迫/拍板", r"预算|多少钱|多急|着急|谁拍板|谁决定|谁说了算"),
]

BANNED_RETRY_PROMPT = """你刚才准备问"{question}"，这属于「别问的问题」里的「{topic}」，对出方案没用，不要问。
重新回复：先对一遍收尾清单（谁在哪个环节痛 / 量化数字 / 根因 / 现在用的工具），对方提到过任何工具名，工具这一项就算齐。
4 项都齐了就直接输出报告 JSON；没齐就只问缺的那一项，并带上 @@SUGGEST 行。"""


def _last_question(text: str) -> str:
    """取回复里的问句部分，用于告诉模型它刚才问了什么。"""
    return "".join(_questions(text)) or text.strip()


def _questions(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[。！？?!])", text) if p.strip()]
    return [p for p in parts if p.endswith(("？", "?"))]


def _banned_topic(text: str) -> Optional[str]:
    """只检查问句（以问号结尾的句子），复述里提到 PDF、手册放群里不算。"""
    for q in _questions(text):
        for topic, pattern in BANNED_QUESTION_PATTERNS:
            if re.search(pattern, q, re.IGNORECASE):
                return topic
    return None

WORKDAYS_PER_MONTH = 22
WEEKS_PER_MONTH = 4


def _fmt_num(x: float) -> str:
    return str(int(round(x))) if x >= 10 or x == int(x) else f"{x:.1f}".rstrip("0").rstrip(".")


def _monthly_cost_note(value: str, unit: str) -> Optional[str]:
    """把"每天/每周"的代价按固定口径换算成每月，算账交给代码，不让模型心算。
    解析不了（如"说不清"、元/月这类本身就是月度的）返回 None，保留模型原文。"""
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", value)][:2]
    m = re.fullmatch(r"(小时|分钟|元|次)\s*/\s*(天|周)", unit.replace(" ", ""))
    if not nums or not m:
        return None
    what, period = m.groups()
    factor, basis = (
        (WORKDAYS_PER_MONTH, f"按每月 {WORKDAYS_PER_MONTH} 个工作日算")
        if period == "天"
        else (WEEKS_PER_MONTH, f"按每月 {WEEKS_PER_MONTH} 周算")
    )
    monthly = [n * factor for n in nums]
    if what == "分钟":
        monthly = [n / 60 for n in monthly]
        what = "小时"
    amount = "~".join(_fmt_num(n) for n in monthly)
    return f"{basis}，一个月大约 {amount} {what}"


def _split_suggestions(text: str) -> tuple[str, list[str]]:
    """从回复里抽出 @@SUGGEST: a | b | c 行，返回(去掉该行的正文, 选项列表)。"""
    m = re.search(r"@@SUGGEST\s*[:：]\s*(.+)", text)
    if not m:
        return text.strip(), []
    options = [s.strip() for s in re.split(r"[|｜]", m.group(1)) if s.strip()][:4]
    cleaned = re.sub(r"\n?\s*@@SUGGEST\s*[:：].*", "", text).strip()
    return cleaned, options


@app.post("/api/chat")
async def chat(req: ChatRequest):
    conv_id = store.get_or_create_conversation(req.conversationId)

    # 新会话：先把开场白补进历史，让模型拿到完整上下文
    if not store.get_history(conv_id):
        store.add_message(conv_id, "assistant", OPENING_MESSAGE)

    store.add_message(conv_id, "user", req.message)
    history = store.get_history(conv_id)
    user_turns = sum(1 for m in history if m["role"] == "user")

    force = user_turns >= MAX_USER_TURNS
    # 最多请求两次：第一次正文为空、或问了禁问的问题，就带上纠正说明重试一次
    extra = None
    for attempt in range(2):
        try:
            reply = await llm.complete(history, force_report=force, extra=extra)
        except Exception as exc:  # noqa: BLE001 - 对用户降级，不暴露细节
            logger.exception("LLM call failed: %s", exc)
            return ChatMessageResponse(conversationId=conv_id, text="网络开小差了，麻烦再发一次～")

        report = llm.extract_report(reply)
        if report is not None:
            normalized = _normalize_report(report)
            store.save_report(conv_id, normalized)
            public = {k: v for k, v in normalized.items() if k != "profile"}
            return ChatReportResponse(conversationId=conv_id, paid=False, report=Report(**public))

        cleaned, suggestions = _split_suggestions(reply)
        if not cleaned:
            logger.warning("Empty reply text (attempt %d): %r", attempt + 1, reply[:200])
            continue
        banned = _banned_topic(cleaned)
        if banned and attempt == 0:
            logger.warning("Banned question (%s), retrying: %r", banned, cleaned)
            extra = BANNED_RETRY_PROMPT.format(question=_last_question(cleaned), topic=banned)
            continue
        break
    if not cleaned:
        cleaned, suggestions = EMPTY_REPLY_FALLBACK, []

    if not suggestions:
        # 兜底：主回复没给选项时，额外生成一次；每个会话最多兜底 3 次（按实际兜底次数算）
        if store.use_suggest_fallback(conv_id, SUGGEST_FALLBACK_LIMIT):
            suggestions = await llm.generate_suggestions(history, cleaned)
    store.add_message(conv_id, "assistant", cleaned)
    return ChatMessageResponse(conversationId=conv_id, text=cleaned, suggestions=suggestions)


@app.post("/api/lead")
def lead(req: LeadRequest) -> OkResponse:
    store.save_lead(req.conversationId, req.channel, req.phone)
    logger.info("Lead captured: conv=%s channel=%s", req.conversationId, req.channel)
    return OkResponse()
