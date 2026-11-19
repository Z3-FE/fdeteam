import json
import logging
import re
import secrets
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import llm, sms, store, wechat
from .config import get_settings
from .schemas import (
    ChatConfirmationResponse,
    ChatMessageResponse,
    ChatReportResponse,
    AccountResponse,
    ChatRequest,
    LatestReportResponse,
    LeadRequest,
    LoginRequest,
    LoginResponse,
    OkResponse,
    Report,
    ReportFeedbackRequest,
    SavedReportItem,
    SavedReportsResponse,
    SaveReportRequest,
    SmsSendRequest,
    SmsSendResponse,
)

logger = logging.getLogger("qb")
logging.basicConfig(level=logging.INFO)

OPENING_MESSAGE = "我们一步步把最卡壳的问题理清楚。最近哪件事最费时间，或最费钱？"

# 信息问齐后返回给前端的提示；报告此时还没生成，用户点"生成诊断报告"后才生成
READY_TEXT = "信息差不多齐了，可以生成诊断报告了。"

# 两次补充写进历史时的前缀；查看报告时按前缀把用户原话取回来
PRE_REPORT_NOTE = "生成报告前的补充："
POST_REPORT_NOTE = "看完报告后的补充："
SUPPLEMENT_PREFIXES = (PRE_REPORT_NOTE, POST_REPORT_NOTE)

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
4 项都齐了就只输出一行 @@READY；没齐就只问缺的那一项，并带上 @@SUGGEST 行。"""

# 收尾时如果还没拿到能算账的数字，退回去逼它先问一句量化
NO_NUMBER_VALUES = {"", "说不清", "未知", "不清楚", "不知道"}
NEED_QUANTIFY_PROMPT = """先别收尾——你还没拿到能算账的数字（量化是空的或"说不清"）。
这一轮不要收尾，改成问一个量化问题：问"多久一次 + 一次多久"，或直接替他估一个让他确认（如"那大概产品经理一天得花一两个小时在这上面？"）。
只输出"一句确认 + 一个量化问题"，紧接着另起一行输出 @@SUGGEST 行（给几个带数字的选项，如"1小时/天 | 2小时以上 | 说不清"）。不要输出 @@READY 或 JSON。"""

# 用户在"诊断完毕了"之后补充了信息，报告还没生成过：带着补充直接生成报告
SUPPLEMENT_REPORT_PROMPT = """问诊已经结束，用户在生成报告前又补充了一段信息（对话最后一条）。
生成报告时以这段补充为准：与之前说法冲突的地方按补充写，没被补充否定的内容照原对话写。
补充里的业务事实只能来自用户原话，不要凭空补充资料格式、培训情况、系统复杂度、人员习惯等事实。
直接输出完整报告 JSON，不再提问、不再确认。"""

CORRECT_REPORT_PROMPT = """用户指出待确认报告有问题。你的任务是修改原报告，不是重新诊断。

严格遵守：
1. 用户最新补充优先，只修改与补充直接相关的字段；用户没有否定的字段原样保留。
   补充推翻了之前的数字、频率或周期时，costValue、costUnit 必须改成补充里的数字和周期。
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
不要输出 @@READY。请严格按系统提示里的「收尾 JSON 结构」重新输出：外层必须包含 status="completed" 和 report，report 内字段必须完整。"""

REPORT_CORRECTION_PROMPT = """用户认为已经生成的报告有一处不准确。你的任务是修改当前报告，不是重新问诊。

严格遵守：
1. 用户最新补充（对话最后一条）优先，只修改与补充直接相关的字段；没有被否定的字段原样保留。
   补充推翻了之前的数字、频率或周期时（如"不是每天，是每周"），costValue、costUnit 必须改成补充里的数字和周期，
   painPoint、summary、actions 里出现的旧数字和旧周期也要一起改掉，不能保留被否定的说法。painQuote 是用户原话，保持不变。
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


def _split_ready(text: str) -> Optional[str]:
    """模型收尾时输出 @@READY: <量化>；返回量化部分（可能为空串），没有收尾标记返回 None。"""
    m = re.search(r"@@READY\s*[:：]?\s*(.*)", text)
    return m.group(1).strip() if m else None


async def _generate_report(history: list[dict], extra: Optional[str] = None) -> Optional[dict]:
    """要求模型输出报告 JSON；解析失败带格式纠正再试一次。返回规整后的报告，失败返回 None。"""
    for attempt in range(2):
        prompt = extra if attempt == 0 else "\n\n".join(p for p in (extra, REPORT_FORMAT_RETRY_PROMPT) if p)
        try:
            reply = await llm.complete(history, force_report=True, extra=prompt)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Report generation failed: %s", exc)
            return None
        report = llm.extract_report(reply)
        if report is not None:
            return _normalize_report(report)
        logger.warning("Report output unparseable (attempt %d)", attempt + 1)
    return None


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


def _openid_from(authorization: Optional[str]) -> Optional[str]:
    """没带登录态按匿名处理；带了但无效返回 401，前端据此重新登录。"""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="invalid token")
    openid = store.get_openid_by_token(token)
    if openid is None:
        raise HTTPException(status_code=401, detail="invalid token")
    return openid


def _claim(conv_id: str, openid: Optional[str]) -> None:
    """登录用户第一次用到这个会话时归到他名下；已归属的会话只有本人带登录态才能用。"""
    owner = store.get_owner(conv_id)
    if openid is None:
        if owner is not None:
            raise HTTPException(status_code=401, detail="login required")
        return
    if owner is None:
        store.bind_owner(conv_id, openid)
    elif owner != openid:
        raise HTTPException(status_code=403, detail="conversation belongs to another user")


@app.post("/api/login")
async def login(req: LoginRequest) -> LoginResponse:
    """wx.login 的 code 换 openid，发一个后端自己的 token；openid 和 session_key 不回给前端。"""
    if not wechat.login_configured():
        raise HTTPException(status_code=503, detail="wechat login not configured")
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="code required")
    try:
        openid = await wechat.code2session(code)
    except wechat.WechatLoginError as exc:
        logger.warning("WeChat login failed: %s", exc)
        raise HTTPException(status_code=401, detail="wechat login failed") from exc
    return LoginResponse(token=store.create_auth_token(openid))


@app.post("/api/chat")
async def chat(req: ChatRequest, authorization: Optional[str] = Header(default=None)):
    openid = _openid_from(authorization)
    conv_id = store.get_or_create_conversation(req.conversationId)
    _claim(conv_id, openid)

    if req.action == "confirm_understanding":
        # 模型收尾时偶尔会直接给出报告 JSON，那份已经存成 pending，直接用
        pending = store.get_pending_report(conv_id)
        if pending is not None:
            return _public_report_response(conv_id, pending)
        if store.get_confirmation_status(conv_id) != "awaiting":
            return ChatMessageResponse(conversationId=conv_id, text="这次确认已经处理过了，请查看报告。")
        report = await _generate_report(store.get_history(conv_id))
        if report is None:
            raise HTTPException(status_code=502, detail="report generation failed")
        return _public_report_response(conv_id, report)

    if req.action == "correct_understanding":
        correction = req.message.strip()
        if not correction:
            return ChatMessageResponse(conversationId=conv_id, text="请补充一句哪里理解错了。")
        pending = store.get_pending_report(conv_id)
        if not store.use_understanding_correction(conv_id):
            return ChatMessageResponse(conversationId=conv_id, text="这次补充已经提交过了，请查看报告。")
        note = {"role": "user", "content": f"{PRE_REPORT_NOTE}{correction}"}
        history = [*store.get_history(conv_id), note]
        if pending is not None:
            prompt = CORRECT_REPORT_PROMPT.format(
                pending_report=json.dumps(pending, ensure_ascii=False, indent=2),
                correction=correction,
            )
        else:
            prompt = SUPPLEMENT_REPORT_PROMPT
        report = await _generate_report(history, extra=prompt)
        if report is None:
            # 生成失败归还补充机会，前端重试时再提交一次
            store.release_understanding_correction(conv_id)
            raise HTTPException(status_code=502, detail="report generation failed")
        store.add_message(conv_id, "user", note["content"])
        return _public_report_response(conv_id, report)

    # 新会话：先把开场白补进历史，让模型拿到完整上下文
    if not store.get_history(conv_id):
        store.add_message(conv_id, "assistant", OPENING_MESSAGE)

    store.add_message(conv_id, "user", req.message)
    history = store.get_history(conv_id)
    user_turns = sum(1 for m in history if m["role"] == "user")

    # 聊到上限还没收尾：不再调模型，直接进入"可以生成报告"
    if user_turns >= MAX_USER_TURNS:
        store.mark_ready(conv_id)
        store.add_message(conv_id, "assistant", READY_TEXT)
        return ChatConfirmationResponse(conversationId=conv_id, text=READY_TEXT)

    # 最多请求两次：第一次正文为空、问了禁问的问题、或没拿到数字就收尾，带上纠正说明重试一次
    extra = None
    for attempt in range(2):
        try:
            reply = await llm.complete(history, extra=extra)
        except Exception as exc:  # noqa: BLE001 - 对用户降级，不暴露细节
            logger.exception("LLM call failed: %s", exc)
            return ChatMessageResponse(conversationId=conv_id, text="网络开小差了，麻烦再发一次～")

        # 收尾：只标记"可以生成"，报告等用户点了再生成，这一轮能很快返回
        report = llm.extract_report(reply)
        ready = _split_ready(reply)
        if report is not None or ready is not None:
            quantity = str(report.get("costValue", "")) if report is not None else ready
            if attempt == 0 and quantity.strip() in NO_NUMBER_VALUES:
                logger.warning("Ready without a quantified number, asking to quantify first")
                extra = NEED_QUANTIFY_PROMPT
                continue
            if report is not None:
                store.save_pending_report(conv_id, _normalize_report(report))
            else:
                store.mark_ready(conv_id)
            # 收尾这句也记进历史，生成报告时模型能看出问诊已经结束
            store.add_message(conv_id, "assistant", READY_TEXT)
            return ChatConfirmationResponse(conversationId=conv_id, text=READY_TEXT)

        cleaned, suggestions = _split_suggestions(reply)
        cleaned = re.sub(r"\s*\n+\s*", "", cleaned)
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
def lead(req: LeadRequest, authorization: Optional[str] = Header(default=None)) -> OkResponse:
    _claim(req.conversationId, _openid_from(authorization))
    store.save_lead(req.conversationId, req.channel, req.phone)
    logger.info("Lead captured: conv=%s channel=%s", req.conversationId, req.channel)
    return OkResponse()


# 保存报告的短信验证码：60 秒才能重发，5 分钟有效，输错 5 次作废，同一手机号或微信用户一天最多 10 条
SMS_COOLDOWN_SECONDS = 60
SMS_CODE_TTL_SECONDS = 300
SMS_MAX_ATTEMPTS = 5
SMS_DAILY_LIMIT = 10


def _require_login(authorization: Optional[str]) -> str:
    openid = _openid_from(authorization)
    if openid is None:
        raise HTTPException(status_code=401, detail="login required")
    return openid


@app.post("/api/sms/send")
async def sms_send(req: SmsSendRequest, authorization: Optional[str] = Header(default=None)) -> SmsSendResponse:
    openid = _require_login(authorization)
    blocked = store.sms_send_block_reason(req.phone, openid, SMS_COOLDOWN_SECONDS * 1000, SMS_DAILY_LIMIT)
    if blocked:
        raise HTTPException(status_code=429, detail=blocked)
    if not sms.sms_configured():
        # 开发模式：本地生成验证码打印到日志，校验也在本地
        code = f"{secrets.randbelow(10 ** 6):06d}"
        store.create_sms_code(req.phone, openid, code, SMS_CODE_TTL_SECONDS * 1000)
        logger.info("[短信未配置，开发模式] %s 的验证码：%s", sms.mask_phone(req.phone), code)
        return SmsSendResponse(cooldown=SMS_COOLDOWN_SECONDS)
    # 阿里云生成验证码，后端只记一条发送记录
    code_id = store.create_sms_code(req.phone, openid, None, SMS_CODE_TTL_SECONDS * 1000)
    try:
        await sms.send_verify_code(req.phone, SMS_CODE_TTL_SECONDS, SMS_COOLDOWN_SECONDS)
    except sms.SmsLimited as exc:
        store.delete_sms_code(code_id)
        logger.warning("SMS limited by aliyun for %s: %s", sms.mask_phone(req.phone), exc)
        raise HTTPException(status_code=429, detail=exc.reason) from exc
    except sms.SmsError as exc:
        # 没发出去的记录删掉，不占冷却和当日额度
        store.delete_sms_code(code_id)
        logger.warning("SMS send failed to %s: %s", sms.mask_phone(req.phone), exc)
        raise HTTPException(status_code=502, detail="sms send failed") from exc
    return SmsSendResponse(cooldown=SMS_COOLDOWN_SECONDS)


async def _verify_code(phone: str, openid: str, code: str) -> bool:
    """只认这个微信用户自己要的验证码；开发模式本地比对，配了阿里云走 CheckSmsVerifyCode。"""
    if not sms.sms_configured():
        return store.verify_sms_code(phone, openid, code, SMS_MAX_ATTEMPTS)
    record = store.get_active_sms_code(phone, openid, SMS_MAX_ATTEMPTS)
    if record is None:
        return False
    try:
        passed = await sms.check_verify_code(phone, code)
    except sms.SmsError as exc:
        logger.warning("SMS check failed for %s: %s", sms.mask_phone(phone), exc)
        raise HTTPException(status_code=502, detail="sms check failed") from exc
    if not passed:
        store.record_sms_code_failure(record["id"], SMS_MAX_ATTEMPTS)
        return False
    store.mark_sms_code_used(record["id"])
    return True


@app.post("/api/report/save")
async def save_report_with_phone(req: SaveReportRequest, authorization: Optional[str] = Header(default=None)) -> AccountResponse:
    """手机号验证通过后给这个微信用户建账号（绑手机号），并把这份报告记成一条留资。"""
    openid = _require_login(authorization)
    _claim(req.conversationId, openid)
    if store.get_latest_report(req.conversationId) is None:
        raise HTTPException(status_code=404, detail="report not found")
    if not await _verify_code(req.phone, openid, req.code):
        raise HTTPException(status_code=400, detail="invalid code")
    store.bind_phone(openid, req.phone)
    directions = [d.strip() for d in req.directions if d.strip()]
    store.save_lead(req.conversationId, "sms", req.phone, directions)
    store.unhide_saved_report(req.conversationId)
    logger.info("Report saved: conv=%s phone=%s", req.conversationId, sms.mask_phone(req.phone))
    return AccountResponse(phone=sms.mask_phone(req.phone))


@app.get("/api/account")
def account(authorization: Optional[str] = Header(default=None)) -> AccountResponse:
    phone = store.get_user_phone(_require_login(authorization))
    return AccountResponse(phone=sms.mask_phone(phone) if phone else None)


def _feedback_state(feedback: Optional[str], corrected: bool) -> Optional[str]:
    if corrected:
        return "corrected"
    return "accurate" if feedback == "accurate" else None


def _public_report(report: dict) -> Report:
    return Report(**{k: v for k, v in report.items() if k != "profile"})


@app.get("/api/reports")
def saved_reports(authorization: Optional[str] = Header(default=None)) -> SavedReportsResponse:
    """历史报告：登录用户保存过的每份报告，最近保存的在前。"""
    openid = _require_login(authorization)
    phone = store.get_user_phone(openid)
    items = [
        SavedReportItem(
            conversationId=r["conversation_id"],
            savedAt=r["saved_at"],
            savedPhone=sms.mask_phone(r["phone"]),
            status="consulted" if r["consulted"] else "saved",
            directions=r["directions"],
            feedback=_feedback_state(r["feedback"], r["corrected"]),
            report=_public_report(r["report"]),
        )
        for r in store.list_saved_reports(openid)
    ]
    return SavedReportsResponse(items=items, accountPhone=sms.mask_phone(phone) if phone else None)


@app.delete("/api/reports/{conversation_id}")
def delete_saved_report(conversation_id: str, authorization: Optional[str] = Header(default=None)) -> OkResponse:
    """从历史报告里删掉一份。只是不再列出，问诊记录和留资都保留。"""
    openid = _require_login(authorization)
    if store.get_owner(conversation_id) != openid:
        raise HTTPException(status_code=404, detail="report not found")
    store.hide_saved_report(conversation_id)
    return OkResponse()


@app.get("/api/report")
def latest_report(
    conversationId: Optional[str] = None, authorization: Optional[str] = Header(default=None)
) -> LatestReportResponse:
    """首页"查看我的诊断报告"和报告页用：取这次问诊最后生成的那份报告。
    不带 conversationId 时（换设备、清了缓存）按登录用户找他最近一次的报告。"""
    openid = _openid_from(authorization)
    if conversationId:
        _claim(conversationId, openid)
    else:
        if openid is None:
            raise HTTPException(status_code=401, detail="login required")
        conversationId = store.get_latest_reported_conversation(openid)
        if conversationId is None:
            raise HTTPException(status_code=404, detail="report not found")
    record = store.get_report_record(conversationId)
    if record is None:
        raise HTTPException(status_code=404, detail="report not found")
    supplements = []
    for m in store.get_history(conversationId):
        if m["role"] != "user":
            continue
        for prefix in SUPPLEMENT_PREFIXES:
            if m["content"].startswith(prefix):
                supplements.append(m["content"][len(prefix):])
    saved_phone = store.get_saved_phone(conversationId)
    return LatestReportResponse(
        conversationId=conversationId,
        report=_public_report(record["report"]),
        createdAt=record["created_at"],
        feedback=_feedback_state(record["feedback"], record["corrected"]),
        supplements=supplements,
        savedPhone=sms.mask_phone(saved_phone) if saved_phone else None,
    )


@app.post("/api/report-feedback")
async def report_feedback(req: ReportFeedbackRequest, authorization: Optional[str] = Header(default=None)):
    _claim(req.conversationId, _openid_from(authorization))
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

    prompt = REPORT_CORRECTION_PROMPT.format(
        current_report=json.dumps(current, ensure_ascii=False, indent=2),
        correction=correction,
    )
    # 补充作为用户最新一句话放进对话；只放在系统提示里时，模型会更信历史里的旧说法
    note = {"role": "user", "content": f"{POST_REPORT_NOTE}{correction}"}
    history = [*store.get_history(req.conversationId), note]
    normalized = await _generate_report(history, extra=prompt)
    if normalized is None:
        store.release_report_correction(req.conversationId)
        raise HTTPException(status_code=502, detail="report correction failed")

    store.add_message(req.conversationId, "user", note["content"])
    return _public_report_response(req.conversationId, normalized)
