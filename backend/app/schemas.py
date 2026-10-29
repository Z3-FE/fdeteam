from typing import Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversationId: Optional[str] = Field(default=None)
    message: str


class Direction(BaseModel):
    title: str
    confidence: Literal["高", "中", "低"] = "中"
    summary: str = ""
    causes: list[str] = []
    actions: list[str] = []


class Report(BaseModel):
    sceneLabel: str = ""
    painPoint: str = ""
    painQuote: str = ""
    costValue: str = ""
    costUnit: str = ""
    costNote: str = ""
    directions: list[Direction] = []


class ChatMessageResponse(BaseModel):
    type: Literal["message"] = "message"
    conversationId: str
    text: str
    suggestions: list[str] = []


class ChatReportResponse(BaseModel):
    type: Literal["report"] = "report"
    conversationId: str
    paid: bool = False
    report: Report


class LeadRequest(BaseModel):
    conversationId: str
    channel: Literal["wechat", "sms"]
    phone: str


class OkResponse(BaseModel):
    ok: bool = True
