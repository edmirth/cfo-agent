# CFO Agent

An AI CFO that reads your Tripletex ledger live and answers in chat. Analysis,
reports and financial models on real numbers — never on memory, never on
invented figures.

```
┌────────────┐   SSE    ┌─────────────┐   MCP connector   ┌───────────┐
│  Chat UI   │ ───────▶ │  FastAPI    │ ────────────────▶ │ Tripletex │
│ (frontend) │ ◀─────── │  + Claude   │ ◀──────────────── │    MCP    │
└────────────┘          └─────────────┘                   └───────────┘
                              │
                              └─▶ Python sandbox (forecasts, scenarios, models)
```

## Quick start

```bash
cp .env.example .env      # add ANTHROPIC_API_KEY and TRIPLETEX_MCP_TOKEN
./run.sh                  # http://localhost:8000
```

Needs Python 3.10+ (`brew install python@3.13` — macOS ships 3.9, which the SDK
does not support). `run.sh` builds the venv on first run.

## How it works

**The agent definition is one file.** `.claude/agents/cfo.md` holds the CFO
persona, the standing analysis framework, report routing, Norwegian accounting
context, and the data traps found the hard way. Claude Code loads it as a
subagent; the web backend loads the same file as its system prompt
(`backend/prompt.py`). Edit it once and both change — it is re-read per request,
so no restart.

**Two paths to Tripletex, on purpose.**

- *Figures* (`backend/mcp_client.py` → `backend/overview.py`) are fetched by
  calling the MCP server directly over JSON-RPC. No model in the loop, so a page
  load is free, fast and exact.
- *Answers* (`backend/agent.py`) go through Claude with the MCP connector, so
  Anthropic runs the tool loop. There is no tool-execution code here to maintain.

**Auth is a self-registered OAuth client.** Tripletex's own company API key is a
refresh token bound to a client we cannot identify, so `scripts/oauth_login.py`
registers our own client and runs the authorization-code flow once. Refresh
tokens do not expire, so it stays headless afterwards.
`backend/tlx_oauth.py` swaps the refresh token for access tokens and persists a
rotated refresh token back to `.env`.

**Read-only.** Every tool the agent can reach is a read.

**Cost.** The system prompt and tool definitions carry a cache breakpoint. A
follow-up turn reads several hundred thousand tokens from cache rather than
paying full input rate, which is the difference between a few cents and a few
dollars per question.

## Layout

| Path | What it is |
|---|---|
| `.claude/agents/cfo.md` | The agent. Behaviour, framework, data traps. Start here. |
| `backend/agent.py` | Claude call, MCP wiring, stream → UI events |
| `backend/mcp_client.py` | Direct JSON-RPC to Tripletex, one reused session |
| `backend/overview.py` | Dashboard figures, computed from reports |
| `backend/tlx_oauth.py` | Access-token refresh |
| `backend/prompt.py` | Builds the system prompt from the agent definition |
| `backend/main.py` | FastAPI: `/api/chat` (SSE), `/api/overview`, `/api/health`, `/api/presets` |
| `frontend/` | Dashboard + chat. No build step. |
| `scripts/oauth_login.py` | One-time browser login |
| `scripts/check_tokens.py` | Verifies the connection on its own |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/overview` | Dashboard figures, cached 10 min |
| `POST` | `/api/chat` | Chat turn, streamed as SSE |
| `POST` | `/api/session/reset?session_id=…` | Clear a conversation |
| `GET` | `/api/health` | Key present, model, Tripletex connected |
| `GET` | `/api/presets` | The suggested questions |

Sending a preset id (`daily`, `cash`, `ar`, `margin`, `forecast`) as the chat
message expands it to the full prompt server-side.

## Before this goes to a customer

- **Sessions are in-memory.** `SESSIONS` in `main.py` is a process-local dict.
  Move to Redis or Postgres before running more than one worker.
- **No auth on the app itself.** Anyone who reaches the port gets the CFO.
- **Read-only is only a prompt rule.** Enforce it at the toolset with
  `default_config: {enabled: false}` plus an allowlist of read tools.
- **The daily brief runs on request.** A cron or a scheduled deployment is what
  makes it arrive unasked.

### Sources

- https://developer.tripletex.no/tripletex-mcp-beta/
- https://developer.tripletex.no/docs/documentation/authentication-and-tokens/
- https://developer.tripletex.no/docs/documentation/faq/getting-started/
- https://developer.tripletex.no/docs/documentation/integration-marketplace/
