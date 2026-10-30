"""评测用例集（eval set）：用真实模型跑多场景 + 刁难输入，自动判对错、给通过率。

这是"让其他所有事不翻车的尺子"——改了 prompt 之后跑它，看核心问诊有没有退化、
边界有没有守住。和 eval_real.py 的区别：eval_real 是"看一段对话"，本文件是"批量判分"。

用法（需 .env 里有真实 SILICONFLOW_API_KEY）：
    cd backend
    arch -arm64 ./.venv/bin/python eval_cases.py            # 跑全部用例
    arch -arm64 ./.venv/bin/python eval_cases.py 2>/dev/null # 滤掉日志，只看结果
    arch -arm64 ./.venv/bin/python eval_cases.py flow        # 只跑 flow 类（完整问诊）
    arch -arm64 ./.venv/bin/python eval_cases.py reply       # 只跑 reply 类（边界/刁难）

判分说明：
- flow 用例：跑完一串回答，检查最终报告的结构（痛点/量化/方向/根因行动/置信度）。
- reply 用例：发一句话，检查 AI 当轮回复必须命中/不许命中某些关键词（守边界）。
"""
import json
import os
import re
import sys

os.environ.setdefault("DB_PATH", "./data/eval_cases.db")
# 不设 MOCK，使用 .env 真实 key。

from fastapi.testclient import TestClient  # noqa: E402

from app import store  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

# ---- flow 用例：完整问诊，判最终报告结构 ----
FLOW_CASES = [
    {
        "name": "CRM 重复提问",
        "turns": [
            "我们公司销售每天在微信群里问一堆重复的问题，把产品经理搞得很烦",
            "基本都是 CRM 系统怎么操作的问题，手册里其实都写了",
            "大概每天 10 到 20 个，产品经理要花一两个小时回",
            "他们嫌翻手册麻烦，群里问一句更快",
            "用企业微信群，手册是 PDF 放群公告里",
            "预算几千块，我能拍板，挺急的",
        ],
    },
    {
        "name": "餐饮库存损耗",
        "turns": [
            "我开了家小餐馆，每个月食材总是莫名其妙少一截，对不上账",
            "主要是后厨领料没人记，想拿多少拿多少",
            "一个月下来差不多亏个三四千块的食材",
            "之前想过让厨师长记本子，但他嫌麻烦没坚持",
            "现在就一个微信群报个大概，没有系统",
            "我自己说了算，不太急但想治一治",
        ],
    },
    {
        "name": "量化给不出（测不编造）",
        "turns": [
            "我们店里对账特别乱，月底总要折腾好久",
            "就是各个收银渠道的数对不上，要一笔笔核",
            "具体多久我真说不清，反正每次都很烦",
            "也没统计过，就是感觉很耗时间",
            "就微信、支付宝、现金几个渠道分开记的",
            "我拍板，想尽快弄清楚",
        ],
        # 期望：costValue 应为"说不清"，不能编一个精确数字
        "expect_cost_unknown": True,
    },
]

# ---- reply 用例：发一句话，判 AI 当轮回复守不守边界 ----
# any_of：回复里至少命中一个关键词；none_of：一个都不许出现
REPLY_CASES = [
    {
        "name": "问你是谁/收费吗",
        "turns": ["等下，先说清楚，你是谁啊？用你要钱吗？"],
        "any_of": ["免费", "不收费", "不要钱"],
    },
    {
        "name": "要求直接出方案",
        "turns": [
            "别问了，我们客户信息记在 Excel 太乱。你直接给我做个 CRM 系统方案和报价",
        ],
        "any_of": ["专家", "先", "梳理", "说清楚", "情况"],
        "none_of": ["报价是", "方案如下", "总价"],
    },
    {
        "name": "跑题闲聊",
        "turns": ["今天天气真不错，你平时喜欢干嘛呀？"],
        "any_of": ["经营", "问题", "咱们", "回到", "先", "公司"],
    },
]
# <!-- RUNNER -->

PASS, FAIL = "✅", "❌"


def _chat(client, cid, msg):
    r = client.post("/api/chat", json={"conversationId": cid, "message": msg}).json()
    return r, r["conversationId"]


def _saved_report(cid):
    with store._connect() as conn:
        row = conn.execute(
            "SELECT report_json FROM briefs WHERE conversation_id = ? ORDER BY id DESC LIMIT 1", (cid,)
        ).fetchone()
    return json.loads(row[0]) if row else None


def run_flow(case) -> list:
    """跑完一串回答，返回 [(检查名, 是否通过)]。"""
    report, turns = None, 0
    with TestClient(app) as c:
        cid = None
        print(f"\n—— [flow] {case['name']} ——")
        for msg in case["turns"]:
            r, cid = _chat(c, cid, msg)
            turns += 1
            print(f"🧑 {msg}")
            if r["type"] == "report":
                report = r["report"]
                break
            print(f"🩺 {r['text']}")
    checks = [("出了报告", report is not None)]
    if report:
        print("报告:", json.dumps(report, ensure_ascii=False))
        # profile 不返回给用户端，从库里取出来给 FDE 看的那份
        profile = (_saved_report(cid) or {}).get("profile") or {}
        print("profile(FDE):", json.dumps(profile, ensure_ascii=False))
        dirs = report.get("directions", [])
        checks += [
            ("有核心痛点", bool(report.get("painPoint"))),
            ("有量化字段", bool(report.get("costValue"))),
            ("至少1个方向", len(dirs) >= 1),
            ("方向含根因+行动", all(d.get("causes") and d.get("actions") for d in dirs)),
            ("置信度合法", all(d.get("confidence") in ("高", "中", "低") for d in dirs)),
            ("有待专家确认的问题", len(report.get("openQuestions") or []) >= 1),
        ]
        if case.get("expect_cost_unknown"):
            cv = str(report.get("costValue", ""))
            # 没问到就该是"说不清"之类，不该冒出一个精确数字
            ok = (not re.search(r"\d", cv)) or ("说不清" in cv)
            checks.append(("未编造量化数字", ok))
        checks.append(("profile 已入库", bool(profile)))
    return checks


def run_reply(case) -> list:
    """发完 turns，取最后一轮 AI 回复，判关键词。"""
    with TestClient(app) as c:
        cid = None
        last = ""
        print(f"\n—— [reply] {case['name']} ——")
        for msg in case["turns"]:
            r, cid = _chat(c, cid, msg)
            print(f"🧑 {msg}")
            if r["type"] == "report":
                # 边界用例不该在第一句就甩报告
                last = "[直接出了报告]"
                print(f"🩺 {last}")
                break
            last = r["text"]
            print(f"🩺 {last}")
    checks = []
    if "any_of" in case:
        hit = any(k in last for k in case["any_of"])
        checks.append((f"命中其一{case['any_of']}", hit))
    if "none_of" in case:
        clean = all(k not in last for k in case["none_of"])
        checks.append((f"未出现{case['none_of']}", clean))
    checks.append(("没秒出报告", last != "[直接出了报告]"))
    return checks


def _report(title, results) -> int:
    total, passed = 0, 0
    print("\n" + "=" * 46 + f"\n{title}")
    for name, checks in results:
        bad = [c for c, ok in checks if not ok]
        total += len(checks)
        passed += sum(ok for _, ok in checks)
        mark = PASS if not bad else FAIL
        print(f"{mark} {name}" + (f" → 未过: {bad}" if bad else ""))
    rate = (passed / total * 100) if total else 0
    print(f"\n通过率: {passed}/{total} = {rate:.0f}%")
    return 0 if passed == total else 1


def main() -> int:
    if get_settings().mock:
        print("⚠ 当前 MOCK 模式（.env 没填 key），真实评测需先在 .env 填 SILICONFLOW_API_KEY。")
        return 2
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    rc = 0
    if which in ("all", "flow"):
        res = [(c["name"], run_flow(c)) for c in FLOW_CASES]
        rc |= _report("flow（完整问诊）结果", res)
    if which in ("all", "reply"):
        res = [(c["name"], run_reply(c)) for c in REPLY_CASES]
        rc |= _report("reply（边界/刁难）结果", res)
    return rc


if __name__ == "__main__":
    sys.exit(main())
