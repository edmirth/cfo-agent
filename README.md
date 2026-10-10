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

### Innlogging

Only the CEO gets in. Supabase does the signing in (password, or a login link
by email); the server checks the token on every `/api` call and lets in only
the emails in `CFO_OWNER_EMAIL`. The server will not start without it.

1. Create a project at [supabase.com](https://supabase.com) (any region).
2. **Authentication → Sign In / Providers**: turn **off** "Allow new users to
   sign up". Nobody can then make an account; the app only has the ones you add.
3. **Authentication → Users → Add user**: the CEO's email, with a password
   (or send an invite and let them set one).
4. **Authentication → URL Configuration**: Site URL `http://localhost:8000`
   (the address the app is opened on; add a hosted one later under Redirect URLs).
5. **Project Settings → API**: copy the project URL and the publishable (anon)
   key into `.env` as `SUPABASE_URL` and `SUPABASE_ANON_KEY`, and the CEO's
   email as `CFO_OWNER_EMAIL`.

The publishable key is public by design: the browser needs it. Tokens are
checked against the project's published signing keys, so no secret is needed;
a project still on the legacy shared secret sets `SUPABASE_JWT_SECRET`.
`CFO_AUTH=off` runs the app with no login, open to anyone who reaches the
port. All of it is in `backend/auth.py` and `frontend-react/src/lib/auth.ts`;
moving off Supabase changes those two files.

### E-post

The Monday brief is emailed to the CEO straight after it is written, through
[Resend](https://resend.com). Without a domain of our own it goes from
Resend's test sender, `onboarding@resend.dev`, which only delivers to the
email the Resend account was made with — so make the account with the email
the brief should reach.

1. Sign up at resend.com with that email (the free plan is enough).
2. **API Keys → Create API key**, permission "Sending access".
3. Put it in `.env` as `RESEND_API_KEY`.

Recipients are `brev_mottakere` in the settings at the top of Selskapet,
comma-separated; without it, the brief goes to `CFO_OWNER_EMAIL`. The front
page's brief card has **Send på e-post nå** for a test. A failed send is said
at the top of the front page and retried every half hour, three times; it is
never sent twice in a week unless sent by hand. With a domain later: verify
it in Resend and set `CFO_MAIL_FROM`; nothing else changes.

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
| `backend/scheduler.py` | What runs unasked: the working-day morning at 07:00 and the Monday brief after it, caught up after sleep, retried, and said when it fails |
| `backend/auth.py` | The login gate: every `/api` route checks the Supabase token and the owner list; fail closed |
| `backend/mailer.py` | Sending email: the one module that knows Resend. Idempotency key on every send |
| `backend/brief_email.py` | The Monday brief as a phone-width email, complete on its own; sent once a week to `brev_mottakere` |
| `backend/watch.py` | The morning watch: VAT money in use and unusual costs become candidates; the model raises cards, opens or closes findings, only for those, with every number checked; plain cards when the model cannot run |
| `backend/health.py` | The health check and the clean-up list for the regnskapsfører: facts per section with no model, written by the `helsesjekk` job, kept in `reports`; on a button and the 6th working day of each month |
| `backend/brief.py` | The Monday cash brief: the light, the low point against the floor, what changed, up to three decisions. The engine decides; the model only phrases |
| `backend/job_runs.py` | One row per run of anything: trigger, status, cost, and what each step of a scheduled run did |
| `backend/main.py` | FastAPI routes and the in-memory session store |
| `frontend/brief.js` | The front page: brief, cash chart, signals, KPIs, and the Saker deck |
| `frontend/app.js` | Shell, routing, conversations, chat, the Selskapet editor |
| `scripts/oauth_login.py` | One-time browser login |
| `scripts/check_tokens.py` | Verifies the Tripletex connection on its own |
| `tests/` | `./.venv/bin/python -m tests.run` — plain asserts, no framework, temporary state |

## Endpoints

Every route except `/api/auth/config` needs the CEO signed in: a Supabase
access token as `Authorization: Bearer …`. Everything except `/api/chat` is
computed without a model and works with no Anthropic credits.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/auth/config` | What the browser needs to sign in. The only route that answers without a login |
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

- **The morning runs only while the server does.** On a Mac that means while
  it is awake with `run.sh` going. Hosted, it runs every working day; the
  scheduler moves with the server and needs no cron.

### Sources

- https://developer.tripletex.no/tripletex-mcp-beta/
- https://developer.tripletex.no/docs/documentation/authentication-and-tokens/
- https://developer.tripletex.no/docs/documentation/faq/getting-started/
- https://developer.tripletex.no/docs/documentation/integration-marketplace/
