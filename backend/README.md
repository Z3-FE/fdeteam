# 问题梳理 · 后端（FastAPI）

P0 的后端：驱动 AI 问诊、产出诊断报告、记录会话与留资。

## 技术栈
- Python + FastAPI
- 模型：硅基流动（SiliconFlow）托管 DeepSeek，OpenAI 兼容，非流式
- 存储：SQLite（P0 零配置；将来可换 Postgres）

## 快速开始
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # 填入你的 SILICONFLOW_API_KEY（不填则自动走 MOCK 模式）
uvicorn app.main:app --reload --port 8000
```
打开 http://127.0.0.1:8000/api/health 应返回 `{"ok":true,...}`。

## MOCK 模式
- `.env` 里不填 `SILICONFLOW_API_KEY`（或设 `MOCK=1`）时，后端走**内置脚本**：
  前两轮固定追问，第三轮返回一份示例报告。用于**没 key 也能把前后端联调跑通**。
- 填了 key 后自动切换到真实 DeepSeek。

## 接口
- `POST /api/chat`  body: `{ "conversationId": string|null, "message": string }`
  - 返回 `{ "type":"message", "conversationId", "text" }`（问诊中）
  - 或 `{ "type":"report", "conversationId", "paid":false, "report": {...} }`（收尾）
- `POST /api/lead`  body: `{ "conversationId", "channel":"wechat|sms", "phone" }` → `{ "ok":true }`
- `GET  /api/health`

## 目录
- `app/main.py`    路由与编排
- `app/prompt.py`  问诊系统提示词（收尾 JSON 与前端 report 结构对齐）
- `app/llm.py`     DeepSeek 客户端（OpenAI 兼容，可换模型的唯一入口）+ MOCK
- `app/store.py`   SQLite 存储（conversations/messages/briefs/leads）
- `app/schemas.py` 请求/响应模型
- `app/config.py`  环境变量

## 说明 / 待办
- **付费裁剪**：P0 暂返回完整 report（前端的"锁定区"是转化引导，解锁=留资，免费）。将来真上付费时在 `main.py` 按 `paid` 裁剪字段。
- **DB**：P0 用 SQLite；上线放量后把 `store.py` 换成 Postgres。
- **向量/多模态**：未接入；需要时在 `llm.py` 换模型名即可（OpenAI 兼容）。
