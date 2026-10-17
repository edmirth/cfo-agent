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

# Pakkene først: når package-lock.json er nyere enn det npm sist installerte
# (node_modules/.package-lock.json), har noen lagt til eller byttet en pakke,
# og bygget feiler til de er installert. Før sjekket vi bare om mappa fantes,
# så en ny pakke fra git ga et bygg som feilet og en app som stille viste
# forrige versjon.
# Så bygget, hvis det mangler, kilden er nyere enn det, eller pakkene er nye.
if command -v npm >/dev/null 2>&1 && [ -d frontend-react ]; then
  fresh_packages=""
  if [ ! -d frontend-react/node_modules ] || \
     [ frontend-react/package-lock.json -nt frontend-react/node_modules/.package-lock.json ]; then
    echo "→ Installerer frontendpakkene …"
    if (cd frontend-react && npm install --silent); then
      fresh_packages=1
    else
      echo "! npm install feilet — prøver å bygge med pakkene som ligger der."
    fi
  fi
  if [ -n "$fresh_packages" ] || [ ! -f frontend-react/dist/index.html ] || \
     [ -n "$(find frontend-react/src frontend-react/index.html -newer frontend-react/dist/index.html 2>/dev/null | head -1)" ]; then
    echo "→ Bygger frontenden …"
    (cd frontend-react && npm run build --silent) || echo "! Bygget feilet — serverer forrige versjon."
  fi
fi

exec ./.venv/bin/uvicorn main:app --app-dir backend --reload --port "${PORT:-8000}"
