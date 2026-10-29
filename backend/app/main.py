import logging

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
    return {
        "sceneLabel": str(raw.get("sceneLabel", "")).strip(),
        "painPoint": str(raw.get("painPoint", "")).strip(),
        "painQuote": str(raw.get("painQuote", "")).strip(),
        "costValue": str(raw.get("costValue", "")).strip(),
        "costUnit": str(raw.get("costUnit", "")).strip(),
        "costNote": str(raw.get("costNote", "")).strip(),
        "directions": dirs,
    }


@app.post("/api/chat")
async def chat(req: ChatRequest):
    conv_id = store.get_or_create_conversation(req.conversationId)

    # 新会话：先把开场白补进历史，让模型拿到完整上下文
    if not store.get_history(conv_id):
        store.add_message(conv_id, "assistant", OPENING_MESSAGE)

    store.add_message(conv_id, "user", req.message)
    history = store.get_history(conv_id)

    try:
        reply = await llm.complete(history)
    except Exception as exc:  # noqa: BLE001 - 对用户降级，不暴露细节
        logger.exception("LLM call failed: %s", exc)
        return ChatMessageResponse(conversationId=conv_id, text="网络开小差了，麻烦再发一次～")

    report = llm.extract_report(reply)
    if report is not None:
        normalized = _normalize_report(report)
        store.save_report(conv_id, normalized)
        return ChatReportResponse(conversationId=conv_id, paid=False, report=Report(**normalized))

    store.add_message(conv_id, "assistant", reply)
    return ChatMessageResponse(conversationId=conv_id, text=reply)


@app.post("/api/lead")
def lead(req: LeadRequest) -> OkResponse:
    store.save_lead(req.conversationId, req.channel, req.phone)
    logger.info("Lead captured: conv=%s channel=%s", req.conversationId, req.channel)
    return OkResponse()
