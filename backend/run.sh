#!/usr/bin/env bash
# 一键启动后端：自动用 backend/.venv，不用手动 source。
# 用法：./run.sh            （默认 8000 端口）
#      ./run.sh 8001       （换端口）
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/uvicorn ]; then
  echo "没找到 .venv，先创建并安装依赖…"
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/uvicorn app.main:app --reload --port "${1:-8000}"
