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

**The morning runs itself while the server does.** Every Norwegian working day
at 07:00 (Oslo time) the server checks the books, keeps today's forecast,
rebuilds the deck and writes the day's summary, so the front page is ready
before anyone asks. It runs inside the server, so on a Mac it runs only while
the Mac is awake with `run.sh` going. A Mac that slept through seven catches up
as soon as it wakes, the same day. A run that failed, or a morning missed
because the server was off, is said at the top of the front page with a
**Kjør nå** button. `CFO_SCHEDULER=off` turns it off; `CFO_MORNING_AT=06:30`
moves it.

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

**Read-only, enforced at the toolset.** The Tripletex toolset is declared
closed (`default_config: {enabled: false}`) and opened tool by tool from the
allowlist in `backend/toolset.py` — 62 reads of the 146 the server offers, so a
write tool cannot be reached even if the prompt asked for one. `/api/toolset`
audits the list against the live server, because Tripletex adds tools and a new
write tool should not slip in unnoticed.

**Cost.** The system prompt and tool definitions carry a cache breakpoint. A
follow-up turn reads several hundred thousand tokens from cache rather than
paying full input rate, which is the difference between a few cents and a few
dollars per question.

## Layout

Everything under `backend/` that computes a figure does so without a model in
the loop. The model decides what to compute and what it means; the arithmetic
is code, and every figure it states is traced back to a source afterwards.

| Path | What it is |
|---|---|
| `.claude/agents/cfo.md` | The agent: scope, voice, standing analysis, data traps. Start here. |
| `company.md` | Starter for what the company says about itself. Copied to `state/` on first run; edited in the app after that. |
| `backend/agent.py` | The turn: Claude call, MCP wiring, local tools, stream → UI events, rollback on interruption |
| `backend/prompt.py` | Assembles the system prompt: persona + company (cached), then the computed blocks |
| `backend/toolset.py` | Read-only, enforced: the 62 Tripletex tools the model may see, and an audit against the server |
| `backend/calc.py` | Arithmetic the model must not do in its head; named metrics carry the finance rules |
| `backend/verify.py` | Traces every figure in an answer to a tool result, a computed block, or the user |
| `backend/trace.py` | A balance opened into its ledger postings |
| `backend/definitions.py` | What each KPI means, fingerprinted over wording *and* code, versioned append-only |
| `backend/preflight.py` | Do the books tie out — unbooked vouchers, subledgers vs accounts, is this month posted |
| `backend/commitments.py` | How much of the bank is actually the company's, dated by when each obligation falls due |
| `backend/cashflow.py` | Thirteen weeks on two lines: committed and expected |
| `backend/industry.py` | Works out the trade from the ledger; the model picks KPIs from a computable catalogue |
| `backend/cards.py` | Work prepared for one-tap approval; derived cards refresh and close with the facts |
| `backend/memory.py` | Snapshots, findings, forecasts, decisions — carried between conversations |
| `backend/company.py` | The company's own account of how it works, and the few settings that move numbers |
| `backend/overview.py` | Headline figures for the front page |
| `backend/mcp_client.py` | Direct JSON-RPC to Tripletex for the computed blocks; raises on rejected calls |
| `backend/tlx_oauth.py` | Access-token refresh; rotated refresh token written back to `.env` atomically |
| `backend/lock.py` | One server per installation — two rotating the same token lock the account out |
| `backend/scheduler.py` | What runs unasked: the working-day morning at 07:00, caught up after sleep, retried, and said when it fails |
| `backend/job_runs.py` | One row per run of anything: trigger, status, cost, and what each step of a scheduled run did |
| `backend/main.py` | FastAPI routes and the in-memory session store |
| `frontend/brief.js` | The front page: brief, cash chart, signals, KPIs, and the Saker deck |
| `frontend/app.js` | Shell, routing, conversations, chat, the Selskapet editor |
| `scripts/oauth_login.py` | One-time browser login |
| `scripts/check_tokens.py` | Verifies the Tripletex connection on its own |
| `tests/` | `./.venv/bin/python -m tests.run` — plain asserts, no framework, temporary state |

## Endpoints

Everything except `/api/chat` is computed without a model and works with no
Anthropic credits.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Key present, PID, read-only, tools allowed |
| `GET` | `/api/overview` | Headline figures, cached 10 min |
| `GET` | `/api/preflight` | Condition of the books |
| `GET` | `/api/commitments` | Free cash and dated obligations |
| `GET` | `/api/cashflow` | 13-week forecast |
| `GET` | `/api/dashboard` | Industry and its KPIs; `?refresh=true` re-decides the industry |
| `GET` | `/api/cards` | The approval deck, rebuilt from the checks |
| `POST` | `/api/cards/{id}/decide` | `{option, note}` — records the choice and does what it means |
| `GET` | `/api/definitions` | Every KPI's definition and version; `?id=dso` for one history |
| `GET` | `/api/trace` | `?account=1920&date_from=&date_to=` — the postings behind a balance |
| `GET` `PUT` | `/api/company` | What the company says about itself; `PUT {text}` saves it |
| `GET` | `/api/toolset` | Allowed tools audited against the server |
| `GET` | `/api/forecast-accuracy` | Each Monday's forecast against the bank 1, 2 and 4 weeks later, and the streak |
| `GET` | `/api/job-runs` | `?job=chat&limit=50` — what ran, how it ended, tokens and cost |
| `GET` | `/api/schedule` | What runs on its own, when next, how the last run went; `attention` when it did not do its job |
| `POST` | `/api/schedule/morning/run` | Run the morning now, by hand; answers when it is done |
| `GET` | `/api/presets` | The suggested questions |
| `POST` | `/api/chat` | Chat turn, streamed as SSE; emits a `check` event tracing the figures |
| `POST` | `/api/session/reset?session_id=…` | Clear a conversation |

Sending a preset id (`daily`, `money`, `ar`, `margin`, `forecast`, `weeks`,
`afford`) as the chat message expands it to the full prompt server-side.

## Before this goes to a customer

- **No auth on the app itself.** Anyone who reaches the port gets the CFO.
- **The morning runs only while the server does.** On a Mac that means while
  it is awake with `run.sh` going. Hosted, it runs every working day; the
  scheduler moves with the server and needs no cron.

### Sources

- https://developer.tripletex.no/tripletex-mcp-beta/
- https://developer.tripletex.no/docs/documentation/authentication-and-tokens/
- https://developer.tripletex.no/docs/documentation/faq/getting-started/
- https://developer.tripletex.no/docs/documentation/integration-marketplace/
