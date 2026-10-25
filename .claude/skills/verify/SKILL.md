---
name: verify
description: How to run the CFO Agent backend and drive its surface for verification.
---

# Verifying the CFO Agent backend

The surface is HTTP on `127.0.0.1:8000`. Every endpoint except `/api/chat` is
computed without a model, so the whole backend is verifiable with no Anthropic
credits.

## Before you start the server

`backend/lock.py` takes an exclusive flock on `state/server.lock`. Two servers
sharing one `.env` rotate the same Tripletex refresh token and lock the account
out until someone logs in through a browser again. So check first:

```bash
pgrep -fl "uvicorn main:app"          # must be empty
lsof -nP -iTCP:8000 -sTCP:LISTEN      # must be free
```

Never start a second one on another port to "work around" a busy 8000.

## Launch

```bash
cd /Users/edmir/cfo-agent
nohup ./run.sh > /tmp/server.log 2>&1 &
```

`run.sh` picks a Python ≥3.10, creates `.venv` on first run, rebuilds
`frontend-react` if the source is newer than `dist/`, then execs uvicorn with
`--reload`. Startup is healthy when the log shows, in order: `Serverlås tatt`,
`Tripletex access token fornyet`, `MCP-sesjon etablert`, `Lesetilgang: 62 av 146
verktøy åpne`, `Application startup complete`. Takes ~3s plus the frontend build.

Stop with `pkill -f "uvicorn main:app"`; the kernel releases the lock.

## Worth driving

```bash
curl -s localhost:8000/api/health      # instant, no MCP call
curl -s localhost:8000/api/overview    # ~6s, slowest endpoint (several reports)
curl -s localhost:8000/api/preflight   # the tie-out checks
curl -s localhost:8000/api/commitments
curl -s localhost:8000/api/cashflow
curl -s localhost:8000/api/cards
curl -s localhost:8000/api/rules      # the floor and thresholds in force, and which are assumed
curl -s "localhost:8000/api/trace?account=1920&date_from=2026-09-01&date_to=2026-09-27"
curl -s localhost:8000/api/dashboard localhost:8000/api/definitions localhost:8000/api/toolset
```

`POST /api/cards/{id}/decide` only writes `state/cards.json` — `cards.py` has no
mail server and never writes to Tripletex, so no card option sends anything
outward. Back up `state/cards.json` and restore it after, or you leave the
owner's deck changed.

`POST /api/chat` streams SSE and needs credits on the key in `.env`. With an
empty balance it still emits a clean `session` event then an `error` event, so
you can tell a billing failure from a code failure without reading the log.

## Cross-checking a computed figure

Don't re-derive it from project code — that's a unit test. The Tripletex MCP
tools available in the Claude Code session read the same ledger independently:
`fetch_report` with `Nøkkeltallsrapport`, `Kundereskontro`, `Leverandørreskontro`
answers whether a figure the backend computed matches its source.

## Gotchas

- The rotated Tripletex refresh token is kept in `state/tripletex.json`, not
  `.env`. Never restore an old copy of that file — the rotated token is the
  valid one. A new login (`scripts/oauth_login.py`) writes `.env`, and a token
  there the file has not seen wins.
- Every route but `/api/auth/config` needs a login. For curl on the Mac, start
  with `CFO_AUTH=off` (refused on a host), or drive a demo company:
  `CFO_DEMO=lindeskar CFO_AUTH=off CFO_SCHEDULER=off ./.venv/bin/uvicorn main:app --app-dir backend --port 8101`.
- Reversed date ranges on `/api/trace` return HTTP 200 with an `{"error": ...}`
  body, not a 4xx. Check the body, not just the status.
- Tripletex returns payables as *negative* in `Leverandørreskontro`, the same
  side as the GL account. Anything comparing the two must not negate one of them.
