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
persona, the standing analysis framework, Tripletex report routing, Norwegian
accounting context, and a list of known data traps in the Tripletex reports.
Claude Code loads it as a subagent; the web backend loads the same file as its
system prompt (`backend/prompt.py`). Edit it once and both change — no restart
needed, it is re-read per request.

**Tool calls run server-side.** The Tripletex MCP server is attached through the
Claude API's MCP connector, so Anthropic executes the tool loop. There is no
tool-execution code in this repo to maintain, and no Tripletex API client.

**Python for modelling.** The `code_execution` tool lets the agent build
forecasts, scenarios and sensitivities on figures it pulled from the ledger
rather than describing them in prose.

**The tool feed is the trust feature.** Every Tripletex call is streamed to the
UI as it happens ("Henter rapport fra Tripletex"), so the CEO sees which reports
the answer was built from instead of a spinner.

## Layout

| Path | What it is |
|---|---|
| `.claude/agents/cfo.md` | The agent. Behaviour, framework, data traps. Start here. |
| `backend/agent.py` | Claude call, MCP wiring, stream → UI events |
| `backend/prompt.py` | Builds the system prompt from the agent definition |
| `backend/main.py` | FastAPI: `/api/chat` (SSE), `/api/health`, `/api/presets` |
| `backend/config.py` | Environment settings |
| `frontend/` | Chat SPA — no build step, plain HTML/CSS/JS |
| `reports/` | Generated briefs |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/chat` | Chat turn, streamed as SSE. Body: `{message, session_id?}` |
| `POST` | `/api/session/reset?session_id=…` | Clear a conversation |
| `GET` | `/api/health` | Key present, model, MCP auth status |
| `GET` | `/api/presets` | Quick actions for the sidebar |

Sending a preset id (`daily`, `cash`, `ar`, `margin`, `forecast`) as the message
expands it to the full prompt server-side.

## Before this goes to a customer

1. **Auth.** `TRIPLETEX_MCP_TOKEN` is currently one token for one company. A
   multi-tenant product needs per-customer credentials from Tripletex, stored
   per account and passed as `authorization_token` on the MCP server entry.
   Confirm with Tripletex that service-account credentials exist for the MCP
   beta — this is the gating question for the whole product.
2. **Sessions are in-memory.** `SESSIONS` in `main.py` is a process-local dict.
   Move to Redis or Postgres before running more than one worker.
3. **No auth on the app itself.** Anyone who reaches the port gets the CFO. Put
   a login in front of it.
4. **Read-only is a promise the code should keep.** The prompt forbids writes,
   but the MCP toolset still exposes them. Use the toolset allowlist
   (`default_config: {enabled: false}` plus `configs` naming only read tools) to
   enforce it at the API rather than in the prompt.
5. **Daily brief runs on request, not on a schedule.** The `daily` preset is the
   prompt; a cron or a Managed Agents scheduled deployment is what makes it
   arrive without being asked for.
