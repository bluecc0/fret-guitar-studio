#!/bin/bash
set -e
cd "$(dirname "$0")/.."
if ! command -v python3 >/dev/null; then
  echo '请先安装 Python 3.11 或更新版本。'; exit 1
fi
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
if [ ! -f .env.local ]; then cp .env.example .env.local; fi
printf '\nFret 启动后请打开 http://127.0.0.1:8765\n'
exec .venv/bin/python -m uvicorn backend.server:app --host 127.0.0.1 --port 8765
