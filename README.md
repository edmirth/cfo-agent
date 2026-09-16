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

**The hosted MCP is not the commercial path.** Researched 9 Sep 2026 against
Tripletex's own developer docs:

`mcp.tripletex.no` is an *end-user feature* of Tripletex, not a developer
platform. An admin activates "Tripletex MCP Beta" on their own subscription and
each user connects over OAuth to their own account. It is free during beta with
a monthly fee announced for general release, and third-party multi-tenant use is
not documented anywhere. Selling a product built on it is not a supported path.

**The commercial path is the REST API**, which uses a two-token model:

| Token | Who holds it | How it is obtained |
|---|---|---|
| Consumer | You, one for the whole product | Application form, 2–3 weeks, no expediting |
| Employee | Each customer | They create it in their own Tripletex GUI and pick your app by name |
| Session | Derived | Consumer + employee exchanged for a short-lived token, sent as HTTP Basic |

Tripletex does not use OAuth 2.0 for this API.

**For this company, no approval is needed at all.** A single-company internal
integration generates a JWT token directly inside Tripletex and works
immediately. Only serving *other* companies requires the consumer token.

### The route

1. **Now** — switch off the hosted MCP onto the REST API with an internal JWT
   token for Ullensaker Renholdsteknikk. Zero approval, real data, today.
2. **In parallel** — apply for a production consumer token. The 2–3 week clock
   runs while you build.
3. **Then** — customers connect by creating an employee token against your
   application name.
4. **Later** — apply for Integration Partner status and a marketplace listing.
   This requires an integration already in production with satisfied Tripletex
   customers, so it is a step three or four, not step one. Its payoff is the
   activation flow: Tripletex POSTs `companyId`, `companyName`, `orgNumber` and
   a fresh employee token to your redirect URL when a customer clicks activate.

### What that means for this code

`backend/agent.py` keeps its shape. What changes is what sits behind the MCP
connector: instead of Anthropic connecting to `mcp.tripletex.no` with a personal
OAuth token, point it at an MCP server you run that wraps the REST API and
authenticates per customer with consumer + employee tokens. Prior art exists —
e.g. `github.com/cwvedvik/tripletex-mcp` takes exactly
`TRIPLETEX_CONSUMER_TOKEN` and `TRIPLETEX_EMPLOYEE_TOKEN`.

Store tokens per customer, never in `.env`, once there is more than one.

### Blocked: the `tlxr_` key is not a v2 credential

Tested against the live API on 16 Sep 2026, with a key created under
**Selskap → API-nøkler**:

- The key is `tlxr_` + a signed JWT. Its payload carries
  `{"ctid":"8357","etid":"2690602","iss":"https://tripletex.no"}` — the consumer
  and employee token ids are embedded, which is why it comes as a single value.
- `PUT /token/session/:create` rejects it as `employeeToken` with
  *"Nøkkelen er ugyldig"*, under every parameter name tried
  (`token`, `jwt`, `apiKey`, `apiToken`, `employeeToken`).
- It fails as `Bearer`, as `X-Api-Key`, and as Basic with username `0`, the
  company id, and itself.
- The v2 OpenAPI spec (re-fetched same day) contains zero occurrences of `jwt`,
  `Bearer` or `tlxr`, and declares exactly one scheme: Basic with username `0`
  and the session token as password.

So the v2 REST API this client targets does not accept this credential. The old
route is also closed: creating a classic employee token under *Min profil →
API-tilgang* requires an application name already registered with Tripletex, and
a custom name is rejected with *"Applikasjonen finnes ikke"*.

Tripletex support has to resolve one of: how the `tlxr_` key authenticates, or
which consumer token an internal integration should pair an employee token with.

### Still outstanding

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
