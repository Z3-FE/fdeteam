import json
import logging
import re
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import llm, store
from .config import get_settings
from .schemas import (
    ChatConfirmationResponse,
    ChatMessageResponse,
    ChatReportResponse,
    ChatRequest,
    LeadRequest,
    OkResponse,
    Report,
    ReportFeedbackRequest,
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

# 报告收尾时如果还没拿到能算账的数字，退回去逼它先问一句量化
NO_NUMBER_VALUES = {"", "说不清", "未知", "不清楚", "不知道"}
NEED_QUANTIFY_PROMPT = """先别收尾——你这份报告的 costValue 是空的或"说不清"，等于没拿到能算账的数。
这一轮不要出报告，改成问一个量化问题：问"多久一次 + 一次多久"，或直接替他估一个让他确认（如"那大概产品经理一天得花一两个小时在这上面？"）。
只输出"一句确认 + 一个量化问题"，紧接着另起一行输出 @@SUGGEST 行（给几个带数字的选项，如"1小时/天 | 2小时以上 | 说不清"）。不要输出 JSON。"""

CORRECT_REPORT_PROMPT = """用户指出待确认报告有问题。你的任务是修改原报告，不是重新诊断。

严格遵守：
1. 用户最新补充优先，只修改与补充直接相关的字段；用户没有否定的字段原样保留。
2. painPoint、painQuote、costValue、costUnit、causes、profile 里的每个业务事实，只能来自原始对话或用户最新补充。
3. 禁止凭空补充资料格式、培训情况、系统复杂度、人员习惯等事实；原对话没说 PDF，就不能写 PDF；没说培训不足，就不能写培训不足。
4. causes 必须以原报告 causes 为底稿：删掉被用户否定的原因，加入用户补充中明确说出的原因；不要为了凑数量新增原因。找不到有原话依据的第二条，就只保留一条。
5. 技术方案可以随纠正调整，但方案假设不能反写成用户现状或根因。summary 和 actions 可以描述要做的系统，但不要把“培训不足”“不符合学习习惯”之类方案假设写成事实。
6. 直接输出完整报告 JSON，不再提问、不再确认。具体实施细节留给 FDE 顾问沟通。

待确认报告：
{pending_report}

用户最新补充：
{correction}"""

REPORT_FORMAT_RETRY_PROMPT = """你上一次回复无法解析成报告 JSON。不要解释、不要使用省略号、不要输出任何 JSON 之外的文字。
请严格按系统提示里的「收尾 JSON 结构」重新输出：外层必须包含 status="completed" 和 report，report 内字段必须完整。"""

REPORT_CORRECTION_PROMPT = """用户认为已经生成的报告有一处不准确。你的任务是修改当前报告，不是重新问诊。

严格遵守：
1. 用户最新补充优先，只修改与补充直接相关的字段；没有被否定的字段原样保留。
2. painPoint、painQuote、costValue、costUnit、causes、profile 中的业务事实，只能来自原始对话、当前报告或用户最新补充。
3. 禁止凭空补充资料格式、培训情况、系统复杂度、人员习惯、接口能力等事实。
4. causes 只保留有明确依据的原因，不要为了凑数量新增原因。
5. 用户可以纠正方案落点（如从微信群改到 CRM 内），允许相应修改 title、summary、actions 和 openQuestions；但不能把方案假设写成用户现状。
6. 未确认能否对接时使用“可考虑对接”，并把可行性写入 openQuestions，不要作确定承诺。
7. 直接输出完整报告 JSON，不再提问、不再确认。只给初步技术方向，细节留给 FDE 顾问沟通。

当前报告：
{current_report}

用户最新补充：
{correction}"""


def _report_missing_number(report: dict) -> bool:
    """报告里没拿到可量化的数字（costValue 空或"说不清"类）。"""
    return str(report.get("costValue", "")).strip() in NO_NUMBER_VALUES


def _confirmation_text(report: dict) -> str:
    """把待生成报告里的已知事实压成一句确认，不让模型再发挥。"""
    pain = report.get("painPoint") or "你刚才说的这个问题"
    cost_value = str(report.get("costValue", "")).strip()
    cost_unit = str(report.get("costUnit", "")).strip()
    tools = str((report.get("profile") or {}).get("currentTools", "")).strip()
    parts = [pain]
    directions = report.get("directions") or []
    causes = directions[0].get("causes") if directions and isinstance(directions[0], dict) else []
    if causes:
        parts.append("主要因为" + "、".join(str(c).strip() for c in causes[:2] if str(c).strip()))
    if cost_value not in NO_NUMBER_VALUES:
        parts.append(f"大约消耗 {cost_value} {cost_unit}".strip())
    if tools and tools != "未知":
        parts.append(f"现在主要用 {tools} 处理")
    return "，".join(parts) + "。"


def _public_report_response(conv_id: str, report: dict) -> ChatReportResponse:
    store.save_report(conv_id, report)
    public = {k: v for k, v in report.items() if k != "profile"}
    return ChatReportResponse(conversationId=conv_id, paid=False, report=Report(**public))


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

    if req.action == "confirm_understanding":
        pending = store.get_pending_report(conv_id)
        if pending is None:
            return ChatMessageResponse(conversationId=conv_id, text="这次确认已经处理过了，请查看报告。")
        return _public_report_response(conv_id, pending)

    if req.action == "correct_understanding":
        correction = req.message.strip()
        pending = store.get_pending_report(conv_id)
        if not correction:
            return ChatMessageResponse(conversationId=conv_id, text="请补充一句哪里理解错了。")
        if pending is None or not store.use_understanding_correction(conv_id):
            return ChatMessageResponse(conversationId=conv_id, text="这次补充已经提交过了，请查看报告。")
        store.add_message(conv_id, "user", f"对刚才理解的纠正：{correction}")
        history = store.get_history(conv_id)
        correction_prompt = CORRECT_REPORT_PROMPT.format(
            pending_report=json.dumps(pending, ensure_ascii=False, indent=2),
            correction=correction,
        )
        try:
            reply = await llm.complete(history, force_report=True, extra=correction_prompt)
            corrected = llm.extract_report(reply)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Corrected report generation failed: %s", exc)
            corrected = None
        if corrected is None:
            store.release_understanding_correction(conv_id)
            return ChatConfirmationResponse(
                conversationId=conv_id,
                text=_confirmation_text(pending),
            )
        normalized = _normalize_report(corrected)
        return _public_report_response(conv_id, normalized)

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
            # 还没拿到能算账的数字就收尾，退回去逼它先问一句量化（非强制收尾时、且只退一次）
            if attempt == 0 and not force and _report_missing_number(report):
                logger.warning("Report has no quantified number, asking to quantify first")
                extra = NEED_QUANTIFY_PROMPT
                continue
            normalized = _normalize_report(report)
            store.save_pending_report(conv_id, normalized)
            return ChatConfirmationResponse(conversationId=conv_id, text=_confirmation_text(normalized))

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


@app.post("/api/report-feedback")
async def report_feedback(req: ReportFeedbackRequest):
    current = store.get_latest_report(req.conversationId)
    if current is None:
        raise HTTPException(status_code=404, detail="report not found")

    if req.action == "accurate":
        store.save_report_feedback(req.conversationId, "accurate")
        return OkResponse()

    correction = req.correction.strip()
    if not correction:
        raise HTTPException(status_code=400, detail="correction required")
    if not store.begin_report_correction(req.conversationId, correction):
        raise HTTPException(status_code=409, detail="report already corrected")

    history = store.get_history(req.conversationId)
    prompt = REPORT_CORRECTION_PROMPT.format(
        current_report=json.dumps(current, ensure_ascii=False, indent=2),
        correction=correction,
    )
    try:
        corrected = None
        for attempt in range(2):
            extra = prompt if attempt == 0 else prompt + "\n\n" + REPORT_FORMAT_RETRY_PROMPT
            reply = await llm.complete(history, force_report=True, extra=extra)
            corrected = llm.extract_report(reply)
            if corrected is not None:
                break
            logger.warning("Report correction returned unparseable output (attempt %d)", attempt + 1)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Report correction failed: %s", exc)
        corrected = None
    if corrected is None:
        store.release_report_correction(req.conversationId)
        raise HTTPException(status_code=502, detail="report correction failed")

    normalized = _normalize_report(corrected)
    return _public_report_response(req.conversationId, normalized)
