"""真实模型评测 / 对话查看（eval）：用真实 DeepSeek 跑问诊并打印完整对话。

用法（需 .env 里有真实 SILICONFLOW_API_KEY）：
    cd backend
    ./.venv/bin/python eval_real.py                 # 用内置 CRM 场景跑，打印对话+报告+结构检查
    ./.venv/bin/python eval_real.py -i              # 交互模式：你自己打字，AI 实时问诊
    ./.venv/bin/python eval_real.py -f 场景.txt      # 从文件读，每行一句用户的话
    ./.venv/bin/python eval_real.py "第一句" "第二句"  # 直接把每句作为参数

想看干净对话，末尾加 2>/dev/null 滤掉日志：
    ./.venv/bin/python eval_real.py -i 2>/dev/null

它和 pytest 互补：pytest 测代码（MOCK、快、确定）；本脚本看真实模型效果（按需手动跑）。
"""
import json
import os
import sys

os.environ.setdefault("DB_PATH", "./data/eval.db")
# 不设 MOCK，使用 .env 真实 key。

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import OPENING_MESSAGE, app  # noqa: E402

DEFAULT_ANSWERS = [
    "我们公司销售每天在微信群里问一堆重复的问题，把产品经理搞得很烦",
    "基本都是 CRM 系统怎么操作的问题，手册里其实都写了",
    "大概每天 10 到 20 个，产品经理要花一两个小时回",
    "他们嫌翻手册麻烦，群里问一句更快",
    "用企业微信群，手册是 PDF 放群公告里",
    "预算几千块，我能拍板，挺急的",
]


def _print_ai(r: dict) -> None:
    print(f"🩺 {r['text']}")
    if r.get("suggestions"):
        print("   选项:", " | ".join(r["suggestions"]))


def run_scripted(answers: list[str]) -> int:
    report = None
    turns = 0
    with TestClient(app) as c:
        cid = None
        for msg in answers:
            r = c.post("/api/chat", json={"conversationId": cid, "message": msg}).json()
            cid = r["conversationId"]
            turns += 1
            print(f"\n🧑 {msg}")
            if r["type"] == "report":
                report = r["report"]
                break
            _print_ai(r)

    checks: list[tuple[str, bool]] = []

    def chk(name: str, ok: bool) -> None:
        checks.append((name, ok))
        print(("✅" if ok else "❌"), name)

    print("\n" + "=" * 40)
    chk(f"在 {len(answers)} 轮内出报告（实际 {turns} 轮）", report is not None)
    if report:
        print("\n报告:\n" + json.dumps(report, ensure_ascii=False, indent=2))
        dirs = report.get("directions", [])
        chk("有核心痛点", bool(report.get("painPoint")))
        chk("有量化代价", bool(report.get("costValue")))
        chk("至少 1 个初诊方向", len(dirs) >= 1)
        chk("每个方向都含根因和可落地行动", all(d.get("causes") and d.get("actions") for d in dirs))
        chk("置信度合法(高/中/低)", all(d.get("confidence") in ("高", "中", "低") for d in dirs))

    failed = [n for n, ok in checks if not ok]
    print("\n结果:", "✅ 全部通过" if not failed else f"❌ {len(failed)} 项未过 → {failed}")
    return 0 if not failed else 1


def run_interactive() -> int:
    print("🩺", OPENING_MESSAGE)
    print("（直接打字回答；输入 /quit 退出）\n")
    with TestClient(app) as c:
        cid = None
        while True:
            try:
                msg = input("🧑 你: ").strip()
            except EOFError:
                break
            if not msg:
                continue
            if msg in ("/quit", "/exit", "q"):
                break
            r = c.post("/api/chat", json={"conversationId": cid, "message": msg}).json()
            cid = r["conversationId"]
            if r["type"] == "report":
                print("\n📋 诊断报告:\n" + json.dumps(r["report"], ensure_ascii=False, indent=2))
                break
            _print_ai(r)
    return 0


def main() -> int:
    if get_settings().mock:
        print("⚠ 当前是 MOCK 模式（.env 没填 key），真实评测需要先在 .env 填 SILICONFLOW_API_KEY。")
        return 2
    args = sys.argv[1:]
    if args and args[0] in ("-i", "--interactive"):
        return run_interactive()
    if args and args[0] in ("-f", "--file"):
        with open(args[1], encoding="utf-8") as fh:
            answers = [ln.strip() for ln in fh if ln.strip()]
    elif args:
        answers = args
    else:
        answers = DEFAULT_ANSWERS
    return run_scripted(answers)


if __name__ == "__main__":
    sys.exit(main())
