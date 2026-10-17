#!/usr/bin/env bash
# Demoselskapene, til presentasjoner. Ingen ekte regnskapsdata er med.
#
#   ./demo.sh          start alle tre (http://localhost:8101, 8102, 8103)
#   ./demo.sh reset    gi alle tre en ny start, uten å starte dem
#   ./demo.sh stop     stopp dem
#
# Et selskap som ikke er klargjort i dag, klargjøres før det starter: tom
# tilstand, brevet, sakene og helsesjekken skrevet på nytt fra demobøkene.
# Hver kjører på sin egen port med sin egen mappe under state-demo/, så den
# ekte appen kan kjøre ved siden av.
set -euo pipefail
cd "$(dirname "$0")"

COMPANIES=("lindeskar:8101:Lindeskar Renhold (renhold, gul uke)"
           "kvarnheim:8102:Kvarnheim Bygg (bygg, rød uke)"
           "aslefjord:8103:Aslefjord Byggvare (grossist, rolig uke)")
PY=./.venv/bin/python
DEMO_ENV=(CFO_AUTH=off CFO_SCHEDULER=off)

if [ ! -x "$PY" ]; then
  echo "! Fant ikke .venv. Kjør ./run.sh én gang først, så er alt installert."
  exit 1
fi

pids_file=state-demo/pids

stop() {
  if [ -f "$pids_file" ]; then
    while read -r pid; do kill "$pid" 2>/dev/null || true; done < "$pids_file"
    rm -f "$pids_file"
    echo "→ Demoene er stoppet."
  fi
}

seed() {  # slug
  echo "→ Klargjør $1 …"
  env "${DEMO_ENV[@]}" CFO_DEMO="$1" "$PY" backend/demo/seed.py > "state-demo/$1.seed.log" 2>&1 \
    && tail -1 "state-demo/$1.seed.log" \
    || { echo "! $1 ble ikke helt klargjort — se state-demo/$1.seed.log"; tail -3 "state-demo/$1.seed.log"; }
}

mkdir -p state-demo

case "${1:-start}" in
  stop)
    stop; exit 0 ;;
  reset)
    stop
    for c in "${COMPANIES[@]}"; do seed "${c%%:*}" & done
    wait; exit 0 ;;
  start) ;;
  *)
    echo "Bruk: ./demo.sh [start|reset|stop]"; exit 1 ;;
esac

stop

# Frontenden, hvis den ikke er bygget.
if [ ! -f frontend-react/dist/index.html ] && command -v npm >/dev/null 2>&1; then
  echo "→ Bygger frontenden …"
  (cd frontend-react && { [ -d node_modules ] || npm install --silent; } && npm run build --silent)
fi

today=$(date +%F)
for c in "${COMPANIES[@]}"; do
  slug=${c%%:*}
  stamp="state-demo/$slug/.seeded"
  if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$today" ]; then
    seed "$slug" &
  fi
done
wait

for c in "${COMPANIES[@]}"; do
  slug=${c%%:*}; rest=${c#*:}; port=${rest%%:*}
  env "${DEMO_ENV[@]}" CFO_DEMO="$slug" "$PY" -m uvicorn main:app --app-dir backend \
    --host 127.0.0.1 --port "$port" > "state-demo/$slug.server.log" 2>&1 &
  echo $! >> "$pids_file"
done
trap 'stop' INT TERM

echo "→ Venter på at de starter …"
for c in "${COMPANIES[@]}"; do
  rest=${c#*:}; port=${rest%%:*}
  for _ in $(seq 1 60); do
    curl -s -o /dev/null "http://127.0.0.1:$port/api/health" && break
    sleep 1
  done
done

echo
for c in "${COMPANIES[@]}"; do
  rest=${c#*:}; port=${rest%%:*}; label=${rest#*:}
  printf '  %-45s http://localhost:%s\n' "$label" "$port"
done
echo
echo "Ctrl+C stopper alle tre."
[ -z "${DEMO_NO_OPEN:-}" ] && command -v open >/dev/null 2>&1 && for c in "${COMPANIES[@]}"; do
  rest=${c#*:}; open "http://localhost:${rest%%:*}"; done
wait
