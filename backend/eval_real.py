"""真实模型评测（eval）：用真实 DeepSeek 跑一遍完整问诊，检查关键属性。

用法（需 .env 里有真实 SILICONFLOW_API_KEY）：
    cd backend && ./.venv/bin/python eval_real.py

它和 pytest（MOCK 回归测试）互补：
- pytest  → 快、确定、测代码有没有改坏（每次改都跑）。
- eval    → 真实模型、按需手动跑、看问诊质量/报告结构到底行不行。
真实模型非确定，所以这里只断言"结构/行为属性"，不断言具体文字。
"""
import json
import os
import sys

os.environ.setdefault("DB_PATH", "./data/eval.db")
# 注意：这里不设 MOCK，使用 .env 里的真实 key。

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

ANSWERS = [
    "我们公司销售每天在微信群里问一堆重复的问题，把产品经理搞得很烦",
    "基本都是 CRM 系统怎么操作的问题，手册里其实都写了",
    "大概每天 10 到 20 个，产品经理要花一两个小时回",
    "他们嫌翻手册麻烦，群里问一句更快",
    "用企业微信群，手册是 PDF 放群公告里",
    "预算几千块，我能拍板，挺急的",
]


def main() -> int:
    if get_settings().mock:
        print("⚠ 当前是 MOCK 模式（.env 没填 key），真实评测需要先在 .env 填 SILICONFLOW_API_KEY。")
        return 2

    report = None
    turns = 0
    with TestClient(app) as c:
        cid = None
        for msg in ANSWERS:
            r = c.post("/api/chat", json={"conversationId": cid, "message": msg}).json()
            cid = r["conversationId"]
            turns += 1
            print(f"\n🧑 {msg}")
            if r["type"] == "report":
                report = r["report"]
                break
            print(f"🩺 {r['text']}")
            if r.get("suggestions"):
                print("   选项:", " | ".join(r["suggestions"]))

    checks: list[tuple[str, bool]] = []

    def chk(name: str, ok: bool) -> None:
        checks.append((name, ok))
        print(("✅" if ok else "❌"), name)

    print("\n" + "=" * 40)
    chk(f"在 {len(ANSWERS)} 轮内出报告（实际 {turns} 轮）", report is not None)
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


if __name__ == "__main__":
    sys.exit(main())
