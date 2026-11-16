"""评测用例集（eval set）：用真实模型跑完整问诊，自动判对错、给通过率。

这是"让其他所有事不翻车的尺子"——改了 prompt 之后跑它，看核心问诊有没有退化。
和 eval_real.py 的区别：eval_real 是"看一段对话"，本文件是"批量判分"。

用法（需 .env 里有真实 SILICONFLOW_API_KEY）：
    cd backend
    arch -arm64 ./.venv/bin/python eval_cases.py 2>/dev/null # 列出用例，输入编号选择（回车=全部）
    arch -arm64 ./.venv/bin/python eval_cases.py all         # 不询问，直接跑全部
    arch -arm64 ./.venv/bin/python eval_cases.py flow        # 只跑 flow 类（完整问诊）
    arch -arm64 ./.venv/bin/python eval_cases.py list        # 列出全部用例和编号（不调模型）
    arch -arm64 ./.venv/bin/python eval_cases.py 1           # 按编号跑（可写多个编号）

每个用例的 turns 就是"用户说的话"，也可以直接复制到小程序里手动测。

判分说明：
- flow 用例：跑完一串回答，检查最终报告的结构（痛点/量化/方向/根因行动/置信度）。
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
from app.main import MAX_USER_TURNS, app  # noqa: E402

# ---- flow 用例：完整问诊，判最终报告结构 ----
FLOW_CASES = [
    {
        "name": "CRM 重复提问",
        "turns": [
            "我们公司销售每天在微信群里问一堆重复的问题，把产品经理搞得很烦",
            "基本都是 CRM 系统怎么操作的问题，手册里其实都写了",
            "他们嫌翻手册麻烦，群里问一句更快",
            "大概每天 10 到 20 个，产品经理要花一两个小时回",
            "问得多的是新来的销售，老销售基本不问",
            "之前让大家先搜群聊记录，没人搜",
            "用企业微信群，手册是 PDF 放群公告里",
            "预算几千块，我能拍板，挺急的",
        ],
    },
]

# 对诊断没帮助的发散提问，问诊里出现即算失败
FILLER_WORDS = ["电脑还是手机", "手机还是电脑", "什么设备", "什么格式", "电子版还是纸质", "放在哪里", "放哪"]
# 给模型看的东西漏进了对话：报告字段名、括号旁白
LEAK_WORDS = ["costValue", "costUnit", "costNote", "openQuestions", "profile", "painPoint"]


def _leaks(text):
    return any(k in text for k in LEAK_WORDS) or bool(re.search(r"[（(]\s*先", text))

# <!-- RUNNER -->

PASS, FAIL = "✅", "❌"


def _chat(client, cid, msg):
    r = client.post("/api/chat", json={"conversationId": cid, "message": msg}).json()
    return r, r["conversationId"]


def _print_ai(r):
    print(f"🩺 {r['text']}")
    opts = r.get("suggestions") or []
    print("   选项:", " | ".join(opts) if opts else "（无）")


def _saved_report(cid):
    with store._connect() as conn:
        row = conn.execute(
            "SELECT report_json FROM briefs WHERE conversation_id = ? ORDER BY id DESC LIMIT 1", (cid,)
        ).fetchone()
    return json.loads(row[0]) if row else None


def run_flow(case) -> list:
    """跑完一串回答，返回 [(检查名, 是否通过)]。"""
    report, turns = None, 0
    ai_texts = []
    no_chips = 0
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
            ai_texts.append(r["text"])
            no_chips += 0 if r.get("suggestions") else 1
            _print_ai(r)
    checks = [
        (f"出了报告（第 {turns} 轮）", report is not None),
        (f"不超过 {MAX_USER_TURNS} 轮", turns <= MAX_USER_TURNS),
    ]
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
            checks.append(("costNote 不写估算数字", not re.search(r"\d", str(report.get("costNote", "")))))
        elif re.search(r"\d", str(report.get("costValue", ""))):
            checks.append(("costUnit 带周期", "/" in str(report.get("costUnit", ""))))
        checks.append(("profile 已入库", bool(profile)))
        for k, v in (case.get("expect_profile") or {}).items():
            checks.append((f"profile.{k} 含「{v}」", v in str(profile.get(k, ""))))
    ai_text = " ".join(ai_texts)
    checks.append(("没有空回复", all(t.strip() for t in ai_texts)))
    checks.append((f"每轮都有快捷选项（缺 {no_chips} 轮）", no_chips == 0))
    checks.append(("没问设备/格式类发散问题", not any(k in ai_text for k in FILLER_WORDS)))
    checks.append(("对话里没漏字段名/旁白", not _leaks(ai_text)))
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


def _numbered():
    """全部用例按顺序编号，返回 [(编号, 类型, 用例)]。"""
    items = [("flow", c) for c in FLOW_CASES]
    return [(i, kind, c) for i, (kind, c) in enumerate(items, 1)]


def _print_list() -> None:
    for i, kind, c in _numbered():
        print(f"{i:>3}  [{kind}] {c['name']}")


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "list":
        _print_list()
        return 0
    if get_settings().mock:
        print("⚠ 当前 MOCK 模式（.env 没填 key），真实评测需先在 .env 填 SILICONFLOW_API_KEY。")
        return 2
    if not args:
        # 不带参数：列出用例，让用户输入编号选择
        _print_list()
        try:
            line = input("\n输入要跑的编号（空格分隔；直接回车=全部）：").strip()
        except EOFError:
            return 0
        args = line.split() or ["all"]
    numbered = _numbered()
    if args[0] in ("all", "flow"):
        chosen = [(k, c) for _, k, c in numbered if args[0] in ("all", k)]
    else:
        # 按编号选：eval_cases.py 1
        by_no = {i: (k, c) for i, k, c in numbered}
        bad = [a for a in args if not a.isdigit() or int(a) not in by_no]
        if bad:
            print(f"无效编号：{' '.join(bad)}（编号 1~{len(numbered)}）。可用编号：")
            _print_list()
            return 2
        chosen = [by_no[int(a)] for a in args]
    rc = 0
    flow = [c for k, c in chosen if k == "flow"]
    if flow:
        res = [(c["name"], run_flow(c)) for c in flow]
        rc |= _report("flow（完整问诊）结果", res)
    return rc


if __name__ == "__main__":
    sys.exit(main())
