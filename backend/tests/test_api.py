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


def test_max_turns_marks_ready_without_report(monkeypatch):
    """模型一直不收尾时，第 MAX_USER_TURNS 句直接进入"可以生成"，这一轮不调模型、不生成报告。"""
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
        assert flags == [False] * (MAX_USER_TURNS - 1)
        assert last["type"] == "confirmation"
        r = c.post("/api/chat", json={"conversationId": cid, "message": "", "action": "confirm_understanding"}).json()
    assert flags[-1] is True  # 点了生成才出报告
    assert r["type"] == "report"


def test_ready_marker_defers_report_generation(monkeypatch):
    """模型输出 @@READY 时只返回"可以生成"，报告在 confirm_understanding 时才生成，且只生成一次。"""
    flags = []

    async def fake_complete(history, force_report=False, extra=None):
        flags.append(force_report)
        return llm._mock_reply(history, force_report=True) if force_report else "@@READY: 2 小时/天"

    monkeypatch.setattr(llm, "complete", fake_complete)
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"conversationId": None, "message": "你好"}).json()
        assert r["type"] == "confirmation" and flags == [False]
        cid = r["conversationId"]
        r = c.post("/api/chat", json={"conversationId": cid, "message": "", "action": "confirm_understanding"}).json()
        assert r["type"] == "report" and flags == [False, True]
        again = c.post("/api/chat", json={"conversationId": cid, "message": "", "action": "confirm_understanding"}).json()
    assert again["type"] == "message"


def test_supplement_before_report_only_once(monkeypatch):
    """"诊断完毕了"之后补充一次：带着补充生成报告；再补充会被拒。"""
    seen = []

    async def fake_complete(history, force_report=False, extra=None):
        seen.append((force_report, history[-1]["content"]))
        return llm._mock_reply(history, force_report=True) if force_report else "@@READY: 1 小时/天"

    monkeypatch.setattr(llm, "complete", fake_complete)
    with TestClient(app) as c:
        cid = c.post("/api/chat", json={"conversationId": None, "message": "你好"}).json()["conversationId"]
        r = c.post("/api/chat", json={"conversationId": cid, "message": "其实是两个人在做", "action": "correct_understanding"}).json()
        assert r["type"] == "report"
        assert seen[-1] == (True, "生成报告前的补充：其实是两个人在做")
        again = c.post("/api/chat", json={"conversationId": cid, "message": "再改", "action": "correct_understanding"}).json()
    assert again["type"] == "message"


def test_report_correction_puts_note_in_history(monkeypatch):
    """报告生成后的补充要作为最后一条用户消息给模型，并写进历史。"""
    seen = []

    async def fake_complete(history, force_report=False, extra=None):
        seen.append(history[-1]["content"])
        return llm._mock_reply(history, force_report=True) if force_report else "@@READY: 1 小时/天"

    monkeypatch.setattr(llm, "complete", fake_complete)
    with TestClient(app) as c:
        cid = c.post("/api/chat", json={"conversationId": None, "message": "你好"}).json()["conversationId"]
        c.post("/api/chat", json={"conversationId": cid, "message": "", "action": "confirm_understanding"})
        r = c.post("/api/report-feedback", json={"conversationId": cid, "action": "correct", "correction": "是每周不是每天"})
    assert r.status_code == 200
    assert seen[-1] == "看完报告后的补充：是每周不是每天"
    assert store.get_history(cid)[-1]["content"] == "看完报告后的补充：是每周不是每天"


def test_latest_report_endpoint(monkeypatch):
    """首页查看报告：返回最新一份报告、反馈状态和两次补充原话；没报告返回 404。"""
    async def fake_complete(history, force_report=False, extra=None):
        return llm._mock_reply(history, force_report=True) if force_report else "@@READY: 1 小时/天"

    monkeypatch.setattr(llm, "complete", fake_complete)
    with TestClient(app) as c:
        cid = c.post("/api/chat", json={"conversationId": None, "message": "你好"}).json()["conversationId"]
        assert c.get("/api/report", params={"conversationId": cid}).status_code == 404
        c.post("/api/chat", json={"conversationId": cid, "message": "两个人在做", "action": "correct_understanding"})
        first = c.get("/api/report", params={"conversationId": cid}).json()
        assert first["feedback"] is None and first["supplements"] == ["两个人在做"]
        assert "profile" not in first["report"]
        c.post("/api/report-feedback", json={"conversationId": cid, "action": "correct", "correction": "是每周"})
        latest = c.get("/api/report", params={"conversationId": cid}).json()
    assert latest["feedback"] == "corrected"
    assert latest["supplements"] == ["两个人在做", "是每周"]
    assert latest["createdAt"] >= first["createdAt"]


def test_login_binds_conversation_and_finds_report(monkeypatch):
    """微信登录：code 换 token；会话归到用户名下，清缓存后不带 conversationId 也能找回报告。"""
    from app import wechat

    async def fake_code2session(code):
        if code == "bad":
            raise wechat.WechatLoginError("errcode=40029")
        return f"openid-{code}"

    async def fake_complete(history, force_report=False, extra=None):
        return llm._mock_reply(history, force_report=True) if force_report else "@@READY: 1 小时/天"

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(wechat, "login_configured", lambda: True)
    monkeypatch.setattr(wechat, "code2session", fake_code2session)
    with TestClient(app) as c:
        assert c.post("/api/login", json={"code": "bad"}).status_code == 401
        login = c.post("/api/login", json={"code": "u1"}).json()
        assert set(login) == {"token"}
        me = {"Authorization": f"Bearer {login['token']}"}
        other = {"Authorization": f"Bearer {c.post('/api/login', json={'code': 'u2'}).json()['token']}"}

        assert c.get("/api/report", headers=me).status_code == 404
        cid = c.post("/api/chat", json={"conversationId": None, "message": "你好"}, headers=me).json()["conversationId"]
        c.post("/api/chat", json={"conversationId": cid, "message": "两个人在做", "action": "correct_understanding"}, headers=me)

        found = c.get("/api/report", headers=me).json()
        assert found["conversationId"] == cid
        # 别人的会话、匿名访问、无效 token 都拿不到
        assert c.get("/api/report", headers=other).status_code == 404
        assert c.get("/api/report", params={"conversationId": cid}, headers=other).status_code == 403
        assert c.get("/api/report", params={"conversationId": cid}).status_code == 401
        assert c.get("/api/report", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_login_not_configured(monkeypatch):
    from app import wechat

    monkeypatch.setattr(wechat, "login_configured", lambda: False)
    with TestClient(app) as c:
        assert c.post("/api/login", json={"code": "x"}).status_code == 503


def test_reply_newlines_are_joined(monkeypatch):
    async def fake_complete(history, force_report=False, extra=None):
        return "明白，是销售在问。  \n\n那一天大概几次？\n@@SUGGEST: 几次 | 十几次"

    monkeypatch.setattr(llm, "complete", fake_complete)
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"conversationId": None, "message": "你好"}).json()
    assert r["text"] == "明白，是销售在问。那一天大概几次？"


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
    """模型想收尾但 costValue 是"说不清"，先退回去逼它问一句量化。"""
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


def test_save_report_with_phone(monkeypatch):
    """保存报告：登录后发验证码，验证通过绑手机号并记一条留资；冷却、输错、别人的会话都被拦住。"""
    from app import main, wechat

    async def fake_code2session(code):
        return f"openid-{code}"

    async def fake_complete(history, force_report=False, extra=None):
        return llm._mock_reply(history, force_report=True) if force_report else "@@READY: 1 小时/天"

    monkeypatch.setattr(llm, "complete", fake_complete)
    # 没配阿里云：走开发模式，本地生成验证码；固定成 123456 方便断言
    monkeypatch.setattr(main.secrets, "randbelow", lambda n: 123456)
    monkeypatch.setattr(wechat, "login_configured", lambda: True)
    monkeypatch.setattr(wechat, "code2session", fake_code2session)
    with TestClient(app) as c:
        me = {"Authorization": f"Bearer {c.post('/api/login', json={'code': 's1'}).json()['token']}"}
        other = {"Authorization": f"Bearer {c.post('/api/login', json={'code': 's2'}).json()['token']}"}
        cid = c.post("/api/chat", json={"conversationId": None, "message": "你好"}, headers=me).json()["conversationId"]
        c.post("/api/chat", json={"conversationId": cid, "message": "", "action": "confirm_understanding"}, headers=me)

        phone = "13800001234"
        assert c.post("/api/sms/send", json={"phone": phone}).status_code == 401
        assert c.post("/api/sms/send", json={"phone": "1234"}, headers=me).status_code == 422
        r = c.post("/api/sms/send", json={"phone": phone}, headers=me)
        assert r.status_code == 200 and r.json()["cooldown"] == main.SMS_COOLDOWN_SECONDS
        assert c.post("/api/sms/send", json={"phone": phone}, headers=me).status_code == 429
        body = {"conversationId": cid, "phone": phone, "code": "123456", "directions": ["方向A"]}
        wrong = "000000"
        assert c.post("/api/report/save", json={**body, "code": wrong}, headers=me).status_code == 400
        assert c.post("/api/report/save", json=body, headers=other).status_code == 403
        assert c.get("/api/account", headers=me).json()["phone"] is None

        saved = c.post("/api/report/save", json=body, headers=me)
        assert saved.status_code == 200 and saved.json()["phone"] == "138****1234"
        assert c.get("/api/account", headers=me).json()["phone"] == "138****1234"
        # 验证码用过即作废
        assert c.post("/api/report/save", json=body, headers=me).status_code == 400


def test_saved_reports_history(monkeypatch):
    """历史报告：只列保存过的报告，联系过顾问的标 consulted；删掉后不再列出，别人删不了。"""
    from app import main, wechat

    async def fake_code2session(code):
        return f"openid-{code}"

    async def fake_complete(history, force_report=False, extra=None):
        return llm._mock_reply(history, force_report=True) if force_report else "@@READY: 1 小时/天"

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(main.secrets, "randbelow", lambda n: 123456)
    monkeypatch.setattr(wechat, "login_configured", lambda: True)
    monkeypatch.setattr(wechat, "code2session", fake_code2session)
    with TestClient(app) as c:
        me = {"Authorization": f"Bearer {c.post('/api/login', json={'code': 'h1'}).json()['token']}"}
        other = {"Authorization": f"Bearer {c.post('/api/login', json={'code': 'h2'}).json()['token']}"}
        assert c.get("/api/reports").status_code == 401

        def new_report() -> str:
            cid = c.post("/api/chat", json={"conversationId": None, "message": "你好"}, headers=me).json()["conversationId"]
            c.post("/api/chat", json={"conversationId": cid, "message": "", "action": "confirm_understanding"}, headers=me)
            return cid

        def save(cid: str, phone: str) -> None:
            store.create_sms_code(phone, "openid-h1", "123456", 300000)
            body = {"conversationId": cid, "phone": phone, "code": "123456", "directions": ["方向A"]}
            assert c.post("/api/report/save", json=body, headers=me).status_code == 200

        first, second, unsaved = new_report(), new_report(), new_report()
        assert c.get("/api/reports", headers=me).json() == {"items": [], "accountPhone": None}

        save(first, "13800001111")
        save(second, "13800002222")
        c.post("/api/lead", json={"conversationId": first, "channel": "sms", "phone": "13800001111"}, headers=me)

        data = c.get("/api/reports", headers=me).json()
        assert data["accountPhone"] == "138****2222"
        assert [i["conversationId"] for i in data["items"]] == [second, first]
        assert unsaved not in [i["conversationId"] for i in data["items"]]
        latest, older = data["items"]
        assert latest["status"] == "saved" and older["status"] == "consulted"
        assert older["savedPhone"] == "138****1111" and older["directions"] == ["方向A"]
        assert "profile" not in older["report"] and older["report"]["painPoint"]
        assert c.get("/api/reports", headers=other).json()["items"] == []

        assert c.delete(f"/api/reports/{first}", headers=other).status_code == 404
        assert c.delete(f"/api/reports/{first}").status_code == 401
        assert c.delete(f"/api/reports/{first}", headers=me).status_code == 200
        assert [i["conversationId"] for i in c.get("/api/reports", headers=me).json()["items"]] == [second]
        # 报告本身还在，重新保存后回到历史
        kept = c.get("/api/report", params={"conversationId": first}, headers=me)
        assert kept.status_code == 200 and kept.json()["savedPhone"] == "138****1111"
        unsaved_report = c.get("/api/report", params={"conversationId": unsaved}, headers=me).json()
        assert unsaved_report["savedPhone"] is None
        save(first, "13800001111")
        assert len(c.get("/api/reports", headers=me).json()["items"]) == 2


def test_sms_code_locked_after_max_attempts(monkeypatch):
    from app import main

    with TestClient(app):
        store.create_sms_code("13900001111", "o1", "123456", 300_000)
        for _ in range(main.SMS_MAX_ATTEMPTS):
            assert store.verify_sms_code("13900001111", "o1", "654321", main.SMS_MAX_ATTEMPTS) is False
        # 错满次数后正确的也不行
        assert store.verify_sms_code("13900001111", "o1", "123456", main.SMS_MAX_ATTEMPTS) is False
        # 别的微信用户不能用这个手机号的验证码
        store.create_sms_code("13900002222", "o1", "123456", 300_000)
        assert store.verify_sms_code("13900002222", "o2", "123456", main.SMS_MAX_ATTEMPTS) is False
        assert store.verify_sms_code("13900002222", "o1", "123456", main.SMS_MAX_ATTEMPTS) is True


def test_sms_aliyun_mode(monkeypatch):
    """配了阿里云：发送交给 SendSmsVerifyCode，校验交给 CheckSmsVerifyCode；后端仍只认本人要过的码，阿里云频控转成 429。"""
    from app import main, sms, wechat

    sent, checked = [], []
    limited = {"reason": None}

    async def fake_send(phone, valid_seconds, interval_seconds):
        if limited["reason"]:
            raise sms.SmsLimited(limited["reason"], "Code=FREQUENCY_FAIL")
        sent.append((phone, valid_seconds, interval_seconds))

    async def fake_check(phone, code):
        checked.append((phone, code))
        return code == "246810"

    async def fake_code2session(code):
        return f"openid-{code}"

    async def fake_complete(history, force_report=False, extra=None):
        return llm._mock_reply(history, force_report=True) if force_report else "@@READY: 1 小时/天"

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(sms, "sms_configured", lambda: True)
    monkeypatch.setattr(sms, "send_verify_code", fake_send)
    monkeypatch.setattr(sms, "check_verify_code", fake_check)
    monkeypatch.setattr(wechat, "login_configured", lambda: True)
    monkeypatch.setattr(wechat, "code2session", fake_code2session)
    with TestClient(app) as c:
        me = {"Authorization": f"Bearer {c.post('/api/login', json={'code': 'a1'}).json()['token']}"}
        cid = c.post("/api/chat", json={"conversationId": None, "message": "你好"}, headers=me).json()["conversationId"]
        c.post("/api/chat", json={"conversationId": cid, "message": "", "action": "confirm_understanding"}, headers=me)

        phone = "13700005678"
        body = {"conversationId": cid, "phone": phone, "code": "246810", "directions": []}
        # 没要过验证码，不去问阿里云
        assert c.post("/api/report/save", json=body, headers=me).status_code == 400
        assert checked == []

        assert c.post("/api/sms/send", json={"phone": phone}, headers=me).status_code == 200
        assert sent == [(phone, main.SMS_CODE_TTL_SECONDS, main.SMS_COOLDOWN_SECONDS)]
        assert c.post("/api/report/save", json={**body, "code": "111111"}, headers=me).status_code == 400
        saved = c.post("/api/report/save", json=body, headers=me)
        assert saved.status_code == 200 and saved.json()["phone"] == "137****5678"
        assert checked == [(phone, "111111"), (phone, "246810")]

        # 阿里云频控拦住：返回 429，不留发送记录
        limited["reason"] = "daily_limit"
        # 换个微信用户和手机号，避开后端自己的 60 秒冷却
        other = {"Authorization": f"Bearer {c.post('/api/login', json={'code': 'a2'}).json()['token']}"}
        r = c.post("/api/sms/send", json={"phone": "13700009999"}, headers=other)
        assert r.status_code == 429 and r.json()["detail"] == "daily_limit"
        limited["reason"] = None
        assert c.post("/api/sms/send", json={"phone": "13700009999"}, headers=other).status_code == 200


def test_aliyun_check_verify_code_reads_verify_result(monkeypatch):
    """CheckSmsVerifyCode 返回 Code=OK 只说明调用成功，只有 Model.VerifyResult=PASS 才算验证码对。"""
    import asyncio

    from alibabacloud_dypnsapi20170525.client import Client

    from app import sms

    replies = []

    async def fake_call(self, params, req, runtime):
        assert params.action == "CheckSmsVerifyCode"
        assert req.query["PhoneNumber"] == "13800000000" and req.query["VerifyCode"] == "123456"
        return {"body": replies.pop(0)}

    monkeypatch.setattr(Client, "call_api_async", fake_call)
    sms._client.cache_clear()
    try:
        replies.append({"Code": "OK", "Success": True, "Model": {"VerifyResult": "PASS"}})
        assert asyncio.run(sms.check_verify_code("13800000000", "123456")) is True
        replies.append({"Code": "OK", "Success": True, "Model": {"VerifyResult": "UNKNOWN"}})
        assert asyncio.run(sms.check_verify_code("13800000000", "123456")) is False
        replies.append({"Code": "isv.SOME_ERROR", "Message": "boom"})
        try:
            asyncio.run(sms.check_verify_code("13800000000", "123456"))
            assert False, "should raise"
        except sms.SmsError:
            pass
    finally:
        sms._client.cache_clear()
