from typing import Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversationId: Optional[str] = Field(default=None)
    message: str = ""
    action: Optional[Literal["confirm_understanding", "correct_understanding"]] = None


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
    openQuestions: list[str] = []


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


class ChatConfirmationResponse(BaseModel):
    type: Literal["confirmation"] = "confirmation"
    conversationId: str
    text: str
    suggestions: list[str] = ["对，就是这个", "不对，有点问题"]


class LeadRequest(BaseModel):
    conversationId: str
    channel: Literal["wechat", "sms"]
    phone: str


class ReportFeedbackRequest(BaseModel):
    conversationId: str
    action: Literal["accurate", "correct"]
    correction: str = ""


class LatestReportResponse(BaseModel):
    conversationId: str
    report: Report
    createdAt: int
    # accurate：用户点过准确；corrected：看完报告后补充过一次，不能再补充
    feedback: Optional[Literal["accurate", "corrected"]] = None
    # 用户两次补充的原话（生成报告前一次、看完报告后一次）
    supplements: list[str] = []
    # 保存过这份报告时是保存用的手机号（打码后），没保存过为空
    savedPhone: Optional[str] = None


class LoginRequest(BaseModel):
    code: str


class LoginResponse(BaseModel):
    token: str


PHONE_PATTERN = r"^1\d{10}$"


class SmsSendRequest(BaseModel):
    phone: str = Field(pattern=PHONE_PATTERN)


class SmsSendResponse(BaseModel):
    ok: bool = True
    # 多少秒后可以再发
    cooldown: int


class SaveReportRequest(BaseModel):
    conversationId: str
    phone: str = Field(pattern=PHONE_PATTERN)
    code: str = Field(pattern=r"^\d{6}$")
    # 用户在报告里选中的方案方向标题
    directions: list[str] = Field(default=[], max_length=10)


class AccountResponse(BaseModel):
    # 已绑定时返回打码后的手机号，如 138****1234
    phone: Optional[str] = None


class SavedReportItem(BaseModel):
    conversationId: str
    # 保存报告的时间（毫秒）
    savedAt: int
    # 保存时验证的手机号，打码后
    savedPhone: str
    # consulted：这次问诊后还联系过 FDE 顾问
    status: Literal["saved", "consulted"]
    # 保存时选中的方案方向标题
    directions: list[str] = []
    feedback: Optional[Literal["accurate", "corrected"]] = None
    report: Report


class SavedReportsResponse(BaseModel):
    items: list[SavedReportItem]
    # 账号绑定的手机号，打码后
    accountPhone: Optional[str] = None


class OkResponse(BaseModel):
    ok: bool = True
