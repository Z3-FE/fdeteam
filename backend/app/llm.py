import json
import re
from typing import Optional

import httpx

from .config import get_settings
from .prompt import SYSTEM_PROMPT


def build_messages(history: list[dict]) -> list[dict]:
    """history: [{role: 'user'|'assistant', content}] -> OpenAI messages."""
    return [{"role": "system", "content": SYSTEM_PROMPT}, *history]


async def complete(history: list[dict]) -> str:
    settings = get_settings()
    if settings.mock:
        return _mock_reply(history)

    payload = {
        "model": settings.model_name,
        "messages": build_messages(history),
        "temperature": 0.4,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }
    url = f"{settings.base_url}/chat/completions"
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def extract_report(text: str) -> Optional[dict]:
    """从模型回复里抽取收尾 JSON；拿到 report 则返回，否则 None。"""
    candidate = None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    elif '"status"' in text and '"report"' in text:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
    if not candidate:
        return None
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and obj.get("status") == "completed" and isinstance(obj.get("report"), dict):
        return obj["report"]
    return None


async def generate_suggestions(history: list[dict], question: str) -> list[str]:
    """兜底：当主回复没带 @@SUGGEST 时，用一次轻量调用专门生成 3 个候选回答。"""
    settings = get_settings()
    if settings.mock:
        return ["说不清", "大概是这样", "没太注意"]
    messages = [
        {
            "role": "system",
            "content": "你在为一个业务问诊助手生成'快捷回答选项'。根据它刚问出的问题，"
            "给 3 个用户可能的简短回答，每个 ≤8 字、口语化。选项是用户站在自己角度的回答，不要写成问句。"
            "只输出这 3 个选项，用 | 分隔，不要任何多余文字。",
        },
        {"role": "user", "content": f"刚问的问题：{question}"},
    ]
    payload = {
        "model": settings.model_name,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 80,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {settings.api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            resp = await client.post(f"{settings.base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001
        return []
    opts = [s.strip().strip("·-• ") for s in re.split(r"[|｜\n、]", text) if s.strip()]
    return opts[:4]


# --------------------------------------------------------------------------- #
# MOCK 模式：没配 API key 时用，走内置脚本，方便先把前后端联调跑通
# --------------------------------------------------------------------------- #

_MOCK_FOLLOWUPS = [
    "嗯，这种事最磨人。它主要卡在哪一步？\n@@SUGGEST: 信息对不上 | 流程太乱 | 全靠我盯着 | 说不清",
    "明白。那这件事，大概每天耗掉你多少时间？\n@@SUGGEST: 半小时内 | 1小时左右 | 2小时以上 | 说不清",
]

_MOCK_SCENES = [
    ("clients", "客户与订单", ["客户", "订单", "销售", "线索", "成交", "报价"],
     "客户线索散在微信和本子上，跟进全靠你一个人记"),
    ("inventory", "库存与采购", ["库存", "采购", "缺货", "压货", "仓库", "进货"],
     "库存数不准，压货和断货同时在发生"),
    ("people", "人手与分工", ["人手", "员工", "招人", "加班", "分工", "离职"],
     "事情都压在少数几个人身上，一请假就停摆"),
    ("finance", "账目与成本", ["账", "成本", "利润", "对账", "欠款", "开销"],
     "钱的事要等到月底才知道，平时看不到真实情况"),
    ("process", "内部流程", ["流程", "乱", "交接", "审批", "开会", "效率"],
     "一件事要转好几个人，转着转着就没人管了"),
]


def _mock_reply(history: list[dict]) -> str:
    user_turns = [m for m in history if m.get("role") == "user"]
    n = len(user_turns)
    if n <= len(_MOCK_FOLLOWUPS):
        return _MOCK_FOLLOWUPS[n - 1]

    text = " ".join(m.get("content", "") for m in user_turns)
    scene = next(
        (s for s in _MOCK_SCENES if any(k in text for k in s[2])),
        _MOCK_SCENES[-1],
    )
    quote = (user_turns[0].get("content", "") or "").strip()[:40]
    report = {
        "status": "completed",
        "report": {
            "sceneLabel": scene[1],
            "painPoint": scene[3],
            "painQuote": quote,
            "costValue": "1",
            "costUnit": "小时 / 天",
            "costNote": "按每周 5 个工作日算，一个月约 20 小时。（MOCK 数据）",
            "directions": [
                {
                    "title": "没有统一入口，全靠人脑记",
                    "confidence": "高",
                    "summary": "同一件事多个人分别在做，信息对不上，重复确认耗掉大量时间。",
                    "causes": ["没有唯一的记录点", "谁在做、做到哪一步只有当事人清楚"],
                    "actions": ["把信息收到一张共享表里，只填最关键的几个字段", "定一个'每步必填'的小规则"],
                },
                {
                    "title": "没有固定节奏，全凭感觉",
                    "confidence": "中",
                    "summary": "该跟的没跟、该补的没补，结果靠运气。",
                    "causes": ["没有约定好的触发动作", "重点对象没被单独标出来"],
                    "actions": ["分三档，各配一个处理间隔", "把重点对象单独打标优先处理"],
                },
            ],
            "openQuestions": ["共享表用现成工具还是要定制，取决于每天多少条记录（MOCK 数据）"],
            "profile": {"industry": "未知", "budget": "未知", "urgency": "未知"},
        },
    }
    return "我把你说的理了一遍，都写进报告了。\n```json\n" + json.dumps(report, ensure_ascii=False) + "\n```"
