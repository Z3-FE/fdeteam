from fastapi.testclient import TestClient

from app import llm, store
from app.main import MAX_USER_TURNS, app, _banned_topic, _normalize_report, _split_suggestions
from app.prompt import FORCE_REPORT_PROMPT, TURN_REMINDER_PROMPT


# ---- 纯函数单测 ----

def test_split_suggestions_basic():
    text, opts = _split_suggestions("那你们怎么记订单？\n@@SUGGEST: 微信里记 | 纸本子 | Excel")
    assert text == "那你们怎么记订单？"
    assert opts == ["微信里记", "纸本子", "Excel"]


def test_split_suggestions_none():
    text, opts = _split_suggestions("只是一句普通的话")
    assert text == "只是一句普通的话"
    assert opts == []


def test_normalize_report_fixes_bad_confidence():
    r = _normalize_report({"directions": [{"title": "x", "confidence": "超高"}]})
    assert r["directions"][0]["confidence"] == "中"
    assert r["directions"][0]["title"] == "x"
    assert isinstance(r["directions"][0]["causes"], list)


def test_normalize_report_empty_directions():
    r = _normalize_report({})
    assert len(r["directions"]) == 1  # 至少补一个占位
    assert r["openQuestions"] == []
    assert r["profile"]["budget"] == "未知"


def test_normalize_report_profile_and_questions():
    r = _normalize_report({"openQuestions": ["a", "", "b", "c", "d"], "profile": {"budget": "几千块"}})
    assert r["openQuestions"] == ["a", "b", "c"]  # 去空、最多 3 个
    assert r["profile"]["budget"] == "几千块"
    assert r["profile"]["industry"] == "未知"


# ---- 接口集成测（MOCK 模式）----

def test_health():
    with TestClient(app) as c:
        j = c.get("/api/health").json()
        assert j["ok"] is True
        assert j["mock"] is True


def test_first_turn_is_message_with_suggestions():
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"conversationId": None, "message": "客户和订单太乱"}).json()
        assert r["type"] == "message"
        assert r["conversationId"]
        assert len(r["suggestions"]) > 0


def test_flow_reaches_report():
    with TestClient(app) as c:
        cid = None
        last = None
        for msg in ["客户和订单太乱", "信息对不上", "每天1小时左右", "说不清", "用微信记"]:
            last = c.post("/api/chat", json={"conversationId": cid, "message": msg}).json()
            cid = last["conversationId"]
            if last["type"] == "confirmation":
                last = c.post(
                    "/api/chat",
                    json={"conversationId": cid, "message": "", "action": "confirm_understanding"},
                ).json()
                break
            if last["type"] == "report":
                break
        assert last["type"] == "report"
        rep = last["report"]
        assert rep["painPoint"]
        assert len(rep["directions"]) >= 1
        for d in rep["directions"]:
            assert d["confidence"] in ("高", "中", "低")
        assert len(rep["openQuestions"]) >= 1
        assert "profile" not in rep  # profile 只入库，不给用户端


def test_lead():
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"conversationId": None, "message": "随便说点"}).json()
        cid = r["conversationId"]
        j = c.post("/api/lead", json={"conversationId": cid, "channel": "sms", "phone": "13800001234"}).json()
        assert j["ok"] is True


def test_suggest_fallback_limit_counts_uses():
    with TestClient(app):
        cid = store.get_or_create_conversation(None)
        uses = [store.use_suggest_fallback(cid, 3) for _ in range(4)]
        assert uses == [True, True, True, False]


def test_build_messages_appends_force_prompt():
    history = [{"role": "user", "content": "x"}]
    normal = llm.build_messages(history)
    assert normal[-1] == {"role": "system", "content": TURN_REMINDER_PROMPT}
    assert normal[-2] == history[0]
    forced = llm.build_messages(history, force_report=True)
    assert forced[-1] == {"role": "system", "content": FORCE_REPORT_PROMPT}
    assert TURN_REMINDER_PROMPT not in [m["content"] for m in forced]


def test_force_report_at_max_turns(monkeypatch):
    """模型一直不收尾时，第 MAX_USER_TURNS 句强制出报告，之前都不强制。"""
    flags = []

    async def fake_complete(history, force_report=False, extra=None):
        flags.append(force_report)
        if force_report:
            return llm._mock_reply(history, force_report=True)
        return "那再说说？\n@@SUGGEST: 好 | 不好"

    monkeypatch.setattr(llm, "complete", fake_complete)
    with TestClient(app) as c:
        cid, last = None, None
        for i in range(MAX_USER_TURNS):
            last = c.post("/api/chat", json={"conversationId": cid, "message": f"第{i + 1}句"}).json()
            cid = last["conversationId"]
    assert flags == [False] * (MAX_USER_TURNS - 1) + [True]
    assert last["type"] == "confirmation"


def test_monthly_cost_note_is_computed():
    r = _normalize_report({"costValue": "1~2", "costUnit": "小时/天", "costNote": "一个月 40~80 小时"})
    assert r["costNote"] == "按每月 22 个工作日算，一个月大约 22~44 小时"
    r = _normalize_report({"costValue": "3", "costUnit": "小时/周", "costNote": "x"})
    assert r["costNote"] == "按每月 4 周算，一个月大约 12 小时"
    r = _normalize_report({"costValue": "30", "costUnit": "分钟/天", "costNote": "x"})
    assert r["costNote"] == "按每月 22 个工作日算，一个月大约 11 小时"


def test_monthly_cost_note_keeps_model_text_when_unparsable():
    r = _normalize_report({"costValue": "说不清", "costUnit": "未知", "costNote": "建议先记一周"})
    assert r["costNote"] == "建议先记一周"
    r = _normalize_report({"costValue": "3000~4000", "costUnit": "元/月", "costNote": "一年三四万"})
    assert r["costNote"] == "一年三四万"


def test_empty_reply_retries_then_falls_back(monkeypatch):
    """模型只回 @@SUGGEST、正文为空时重试一次；还是空就用兜底话术，不给用户发空气泡。"""
    calls = []

    async def fake_complete(history, force_report=False, extra=None):
        calls.append(1)
        return "@@SUGGEST: a | b"

    monkeypatch.setattr(llm, "complete", fake_complete)
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"conversationId": None, "message": "你好"}).json()
    assert len(calls) == 2
    assert r["type"] == "message"
    assert r["text"].strip()


def test_empty_reply_retry_succeeds(monkeypatch):
    replies = iter(["@@SUGGEST: a | b", "那每天花多久？\n@@SUGGEST: 1小时 | 说不清"])

    async def fake_complete(history, force_report=False, extra=None):
        return next(replies)

    monkeypatch.setattr(llm, "complete", fake_complete)
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"conversationId": None, "message": "你好"}).json()
    assert r["text"] == "那每天花多久？"
    assert r["suggestions"] == ["1小时", "说不清"]


def test_banned_topic_checks_only_the_question():
    assert _banned_topic("好的。那手册放在哪里？销售能随时找到吗？") == "东西在哪"
    assert _banned_topic("明白。新销售入职会培训 CRM 吗？") == "管理动作"
    assert _banned_topic("嗯。销售平时用电脑还是手机？") == "设备"
    # 问资料用什么形式维护是允许的（PDF 不再属于禁问）
    assert _banned_topic("好的。那手册现在是 PDF 还是在线文档？") is None
    # 复述里提到 PDF 不算，问题本身没问放在哪
    assert _banned_topic("好的，手册是 PDF 放群公告里。那每天大概要回多少个？") is None
    assert _banned_topic("那为什么不看手册，非要来问呢？") is None


def test_banned_question_is_retried_with_correction(monkeypatch):
    seen = []
    replies = iter(["好的。那手册放在哪里？\n@@SUGGEST: 群里 | 不知道", "那每天花多久？\n@@SUGGEST: 1小时 | 说不清"])

    async def fake_complete(history, force_report=False, extra=None):
        seen.append(extra)
        return next(replies)

    monkeypatch.setattr(llm, "complete", fake_complete)
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"conversationId": None, "message": "你好"}).json()
    assert seen[0] is None and "东西在哪" in seen[1]
    assert r["text"] == "那每天花多久？"


def test_report_without_number_asks_to_quantify_first(monkeypatch):
    """模型想收尾但 costValue 是"说不清"，先退回去逼它问一句量化，再出报告。"""
    report_json = (
        '```json\n{"status":"completed","report":{"costValue":"说不清","costUnit":"未知",'
        '"directions":[{"title":"x","confidence":"高"}]}}\n```'
    )
    seen = []
    replies = iter([report_json, "那产品经理一天大概花多久？\n@@SUGGEST: 1小时/天 | 2小时以上 | 说不清"])

    async def fake_complete(history, force_report=False, extra=None):
        seen.append(extra)
        return next(replies)

    monkeypatch.setattr(llm, "complete", fake_complete)
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"conversationId": None, "message": "你好"}).json()
    assert seen[0] is None and seen[1] is not None  # 第二次带上了量化纠正
    assert r["type"] == "message"
    assert r["text"] == "那产品经理一天大概花多久？"


def test_report_without_number_is_accepted_if_retry_still_missing(monkeypatch):
    """逼问一次后模型还是出没数字的报告，就照收，不无限退回。"""
    report_json = (
        '```json\n{"status":"completed","report":{"costValue":"说不清","costUnit":"未知",'
        '"painPoint":"p","directions":[{"title":"x","confidence":"高"}]}}\n```'
    )

    async def fake_complete(history, force_report=False, extra=None):
        return report_json

    monkeypatch.setattr(llm, "complete", fake_complete)
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"conversationId": None, "message": "你好"}).json()
    assert r["type"] == "confirmation"
    assert "p" in r["text"]


def test_banned_question_kept_if_retry_also_banned(monkeypatch):
    """重试一次还是禁问，就照发，不无限重试。"""
    calls = []

    async def fake_complete(history, force_report=False, extra=None):
        calls.append(1)
        return "那手册放在哪？\n@@SUGGEST: 群里 | 不知道"

    monkeypatch.setattr(llm, "complete", fake_complete)
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"conversationId": None, "message": "你好"}).json()
    assert len(calls) == 2
    assert r["text"] == "那手册放在哪？"
