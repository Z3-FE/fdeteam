from fastapi.testclient import TestClient

from app.main import app, _normalize_report, _split_suggestions


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
