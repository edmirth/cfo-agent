#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# The SDK needs Python 3.10+; macOS system python is 3.9.
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "! Fant ingen Python 3.10 eller nyere. Installer med: brew install python@3.13"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "→ Lager virtuelt miljø med $PY…"
  "$PY" -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

if [ ! -f .env ]; then
  echo "! Ingen .env funnet. Kopier .env.example til .env og fyll inn nøklene."
  exit 1
fi

exec ./.venv/bin/uvicorn main:app --app-dir backend --reload --port "${PORT:-8000}"
