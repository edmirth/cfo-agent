# The database: design and architecture

This is the plan for [[state-database]] (card 4) and the cards that build on it.
It covers what goes in the database, what stays out, how it fits the code that
exists, and the order to build it in. The SQL at the end has been run against
SQLite 3.45.

## In one paragraph

Tripletex already holds the truth about the money, so we do not copy it.
The database holds the things only this product knows: what the CFO forecast,
what it flagged, the cards it prepared and what the CEO decided, the company's
rules, what was said in chat, and every job that ran. Today these live in JSON
files under `state/` and in a dict in `main.py`. They move into one database
behind one module, `backend/db.py`. The modules keep their public functions,
so `memory.add_finding()` and `cards.decide()` work exactly as before and only
their insides change. Start on **SQLite**, which is a single file built into
Python. Move to **Postgres** when the app is hosted for more than one customer.
The schema is written so that move is a data copy, not a redesign.

## Words used below

| Word | Meaning here |
|---|---|
| **Table** | One kind of thing, e.g. `cards`. Like a spreadsheet tab. |
| **Row** | One of those things, e.g. card K014. |
| **Column** | One fact about it, e.g. `status`. Each column has a type: text, integer, date. |
| **Primary key** | The column that identifies a row and is never reused, usually `id`. |
| **Foreign key** | A column pointing at a row in another table, e.g. `decisions.card_id → cards.id`. |
| **Index** | A lookup the database keeps so a search does not read every row. A *unique* index also forbids duplicates. |
| **Transaction** | A group of writes that all happen or none do. This replaces the thread locks. |
| **Migration** | A numbered SQL file that changes the schema. They run in order and each runs once. |
| **Tenant** | One customer company. Today there is one. |

## What goes in, what stays out

The test: **if Tripletex or the bank can tell us again tomorrow, do not store
it yet. If only we know it, store it, and keep its history.**

| Stays out | Why |
|---|---|
| Ledger, invoices, postings | Tripletex is the source of truth, and the agent must re-fetch any figure it states (`verify.py`). A copy means keeping a copy in sync. That is [[data-sync]], a later phase. |
| The 10-minute caches (`freshness.Cached`) | They are caches, not records. Losing them on restart is correct. |
| `state/server.lock` | A process lock (`lock.py`). It has to be a file the OS can lock. |
| `.claude/agents/cfo.md`, `company.md` template | Code and templates, not customer data. |
| The Tripletex refresh token, for now | It stays in `.env` until there is more than one company. It then goes in `connections`, encrypted (step 4). It is never stored in plain text. |

| Goes in | Today | Table(s) |
|---|---|---|
| Findings, the agent's predictions, decisions | `state/memory.json` | `findings`, `predictions`, `decisions` |
| Daily KPI snapshots | `state/memory.json` | `kpi_snapshots` |
| The approval deck | `state/cards.json` | `cards`, `card_events` |
| KPI definitions, versioned | `state/definitions.json` | `kpi_definitions` |
| The company's own text and rulebook | `state/company.md` + `company.<stamp>.md` | `company_texts` |
| Industry profile | `state/profile.json` | `industry_profiles` |
| The front-page summary | `state/summary.json` | `reports` |
| Chat history | `SESSIONS` dict in `main.py` | `conversations`, `messages` |
| 13-week forecasts | *not kept* | `forecast_runs`, `forecast_weeks`, `forecast_flows` |
| The bank balance each day | *not kept* | `bank_balances` |
| Job runs, tokens, cost | *not kept* | `job_runs` |

## Where it sits

```
   Tripletex · bank feed        the truth about the money (live, read-only)
            │
            ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ Engine: overview, preflight, commitments, cashflow, calc     │  computes figures,
 │                                                              │  no model
 └──────────────────────────────────────────────────────────────┘
            │ figures                          ▲ rulebook, definitions
            ▼                                  │
 ┌──────────────────────────────────────────────────────────────┐
 │ Record modules: memory, cards, company, definitions,         │  same public
 │ industry, summary, forecasts, conversations, jobs            │  functions as today
 └──────────────────────────────────────────────────────────────┘
      ▲ routes         ▲ agent tools          ▲ scheduled jobs
      │ (main.py)      │ (agent.py)           │ (card 6)
            │
            │ only through backend/db.py
            ▼
   state/cfo.db   SQLite now · Postgres when hosted        what only we know
```

Three things call the record modules: the API routes the React app uses, the
agent's local tools (`remember_finding`, `propose_card`, `score_forecast`…),
and the scheduler (`scheduler.py`, card 6). None of them touch SQL. **`db.py` is
the only file that opens a connection.** That one rule makes the later moves
small: swapping SQLite for Postgres, adding the tenant filter, adding the
audit log. Each one changes `db.py`, not forty call sites.

### How the agent uses it

The user-facing goal is that the agent can actually use the database. It does,
in two ways, and neither is raw SQL.

1. **It reads through the briefing.** `prompt.py` already puts
   `memory.briefing()`, `cards.briefing()` and `company.briefing()` into the
   system prompt. Those functions read from the database instead of JSON, and
   the agent sees the same text it sees today.
2. **It writes and looks things up through named tools.** The tools it has
   today keep working. New ones become cheap to add, because each is a fixed,
   tested query:
   - `forecast_record`: how close the forecasts from 1, 2 and 4 weeks ago came
     (card 5, and the Monday brief in card 7)
   - `kpi_history(kpi, from, to)`: a trend over a period, from `kpi_snapshots`
   - `history_for(customer)`: every finding, card and decision that named a
     customer

The agent is **never** given a "run this SQL" tool. The reason is the same as
the Tripletex allowlist in `toolset.py`: a tool that can do anything can read
another tenant's rows, or rewrite history. A fixed set of queries cannot.
Figures from the database are history. A figure the agent states as current
still comes from Tripletex, which is what `memory.briefing()` already tells it.

## SQLite now, Postgres when hosted

| | SQLite | Postgres |
|---|---|---|
| What it is | A single file (`state/cfo.db`), built into Python | A database server you run or rent |
| To set up | Nothing. `import sqlite3` | Install it, or rent a managed one in an EU region |
| New dependency | None | `psycopg` |
| More than one machine | No | Yes |
| Many writers at once | One at a time, which is fine at this size | Yes |
| Isolation the database enforces | No; `db.py` filters by company | Row-level security |
| Search by meaning (pgvector) | No | Yes, for narrative memory in Phase 2 |
| Backup | Copy the file (`sqlite3 … .backup`) | Provider snapshots |

**Recommendation: SQLite now.** The pilot is one company on one machine,
started with `run.sh`. SQLite adds nothing to install and nothing to keep
running. The tests can use a throwaway file, as `tests/_tmp.py` does today.
Move to Postgres at the same moment as [[tenant-isolation]], which is before
the second customer. Postgres row-level security is the cleanest way to prove
one customer cannot read another's rows.

**If you already know** the app will run on a hosted server within a couple of
months, start on Postgres instead. The tables below are the same. Only the
column types in the right-hand column of the next section change.

## Seven rules for every table

1. **Every row carries `company_id`.** This applies even while there is one
   company, and to child rows too (a forecast's weeks, a card's events). Then
   "everything for company 3" is a filter on any table, with no joins.
   Isolation can also be enforced in one place. The only tables without it
   are `companies` itself, `schema_version`, and `kpi_definitions`, which
   describes the code; the same code serves every company.
2. **History is appended, not overwritten.** Forecasts, snapshots,
   definitions, company texts, card events and job runs are only ever
   inserted. The forecast ledger, the definitions ledger and the audit log
   only work if the past cannot be edited. Where something has a current
   state, as a card has a status, the row holds the current state and an
   `_events` table holds how it got there.
3. **Money is whole øre in an integer column (`amount_ore`).** Floating-point
   kroner drift: 0.1 + 0.2 is not 0.3. Convert in one place, in `db.py`, and
   the rest of the code keeps working in kroner. KPI values mix units (%,
   ratios, kroner), so they stay real numbers.
4. **Typed columns for what code filters, sorts or adds; JSON for the rest.**
   `status`, `urgency`, `amount_ore` and `made_on` are columns. A card's
   buttons, draft and evidence are JSON, because they are only ever shown,
   never searched. This follows the playbook's rule: anything that changes a
   number is a structured setting, never a sentence.
5. **Dates are dates, times are UTC.** Use `YYYY-MM-DD` for a day (`made_on`,
   `due`). Use ISO 8601 in UTC for a moment (`started_at`). Convert to Oslo
   time only for display.
6. **The agent's ids stay short.** The agent and the CEO refer to `F004` and
   `K014`, and decisions already say "Kort K014". Each such table has an
   integer `id` for the database and a `ref` that is unique per company. The
   `ref` comes from `counters`, one row per company and series. Memory's
   F, P and D share one series, as they do today. Migrated rows keep their
   refs.
7. **The database enforces the rules it can.** A `CHECK` limits a column to
   its allowed values. A foreign key stops an orphaned row. A partial unique
   index stops a second live card for the same customer, even if two requests
   race. The code keeps its own checks; these are the safety net.

## The tables

```
 companies ─┬─ company_texts        the rulebook and story, every version
            ├─ industry_profiles    each time the industry was decided
            ├─ kpi_snapshots        one row per KPI per day
            ├─ bank_balances        one row per account per day
            ├─ forecast_runs ─┬─ forecast_weeks    13 rows per run
            │                 ├─ forecast_flows    every line behind them
            │                 └─ forecast_scores   checked against the bank   (step 2)
            ├─ predictions          the agent's own point forecasts (P001)
            ├─ findings             what was flagged (F001)
            ├─ cards ─── card_events                (K001)
            ├─ decisions ─ ─ ─ ▶ cards              what the CEO chose (D001)
            ├─ reports              summary, Monday brief, monthly pack
            ├─ conversations ─── messages
            ├─ job_runs ◀ ─ ─ ─ ─ most rows above say which run wrote them
            └─ counters             the next F/P/D/K number

 kpi_definitions                    product-wide, no company_id
```

### Who: `companies`

One row per customer company: `id`, `name`, `org_number`, `created_at`. The
first migration creates the one company from `COMPANY_NAME`. Until login
exists, `db.company_id()` returns it. After login (card 8), the request sets
the company, and a query that runs without one fails instead of guessing.

### The company's own words: `company_texts`, `kpi_definitions`, `industry_profiles`

- **`company_texts`**: every saved version of `company.md`, with the
  `settings` block already parsed into JSON. The latest row is the current
  one. This replaces the `company.<stamp>.md` copies and keeps every version,
  not ten. The versioned company rulebook the playbook asks for falls out of
  this.
- **`kpi_definitions`**: the append-only ledger from `definitions.py`, one
  row per KPI per version.
- **`industry_profiles`**: each time the industry was decided, with the
  reasoning and evidence as JSON. The newest row is the profile in force.
  Older rows show when and why it changed.

### What the CFO saw: `kpi_snapshots`, `bank_balances`

- **`kpi_snapshots`**: one row per KPI per day, with the definitions hash in
  force. "Bank over the last 90 days" is then one query. Same-day writes
  replace that day's row, as `memory.snapshot()` does now.
- **`bank_balances`**: the actual balance on the account each day, and where
  it came from (`bank_feed`, `ledger`, later `psd2`). A forecast is scored
  against this. Write it daily from the start, because the scoring in card 5
  needs weeks of it.

### What it predicted: `forecast_runs`, `forecast_weeks`, `forecast_flows`, `predictions`

- **`forecast_runs`**: one saved 13-week forecast. It holds the date, the
  opening balance and its source, both low points, the assumptions as JSON,
  the definitions hash, and the job that made it. There is one `weekly` run
  per company per day. Ad-hoc runs are kept apart, so only the Monday one is
  scored.
- **`forecast_weeks`**: the 13 rows the chart draws. Each has the week's
  start, the committed close and the expected close.
- **`forecast_flows`**: every line behind the weeks: kind (`ar`, `ar_late`,
  `ap`, `wages`, `vat_future`, `opex`…), scenario, label and amount. When a
  forecast misses, this is how the miss is put down to a kind ("customers
  paid later"). Card 5 asks for exactly that.
- **`forecast_scores`** (step 2): for each run, what it said 1, 2 and 4 weeks
  ahead, what the bank actually showed, the error, and the miss by flow kind.
- **`predictions`**: the agent's own `remember_forecast` /
  `score_forecast` records (P001…). These are a separate table from
  `forecast_runs` because they are a different thing: one figure for one
  period, made in conversation.

### What it raised and what was decided: `findings`, `cards`, `card_events`, `decisions`

- **`findings`**: F001… as today: topic, severity, statement, the metric and
  value, open or closed, and the outcome.
- **`cards`**: the deck. Each card holds its current state: status, urgency,
  amount, title, body, the snooze and close dates. Buttons, draft, evidence,
  follow-up and the latest decision are JSON. A partial unique index allows
  only one open or snoozed card per `key` per company.
- **`card_events`**: every change to a card, inserted and never updated:
  created, refreshed, decided, woke, resolved, released. A decision records
  who made it, which button was tapped, and whether the draft was edited.
  This is what [[service-metrics]] measures: time to decide, and the share
  approved without edits.
- **`decisions`**: D001…, what the CEO chose, with `card_id` when it came
  from a card.

### What it wrote and said: `reports`, `conversations`, `messages`

- **`reports`**: every piece of writing the product produces on its own:
  `summary` (today's `summary.json`), and later `weekly_brief` (card 7),
  `monthly_pack` and `health_check`. Each has the period it covers, the text,
  and the figures it was written from. Rewrites are new rows. This is the
  archive that lets month three cite month two. A `status` column carries the
  human-review queue (card 15): `draft`, `in_review`, `approved`, `sent`.
- **`conversations`** and **`messages`**: chat, replacing `SESSIONS`. A
  conversation's id is the `session_id` the UI already sends. Each message
  stores the content blocks exactly as the Anthropic API takes them,
  `tool_use` and `tool_result` included, so a conversation reloads as it was.
  **Write a turn's messages in one transaction when the turn finishes.** An
  interrupted turn then writes nothing, which is the rollback `agent.py`
  already does by hand. Trimming to `MAX_HISTORY_MESSAGES` happens when
  reading, so nothing is deleted to make it fit.

### How it ran: `job_runs`

One row per run of anything that does work: a chat turn, the summary, the
industry decision, the forecast save, the scheduler's `morning` run, and later
the watch and the brief. Each
row has the trigger (user, schedule, startup), start and finish times, the
status (`running`, `ok`, `partial`, `failed`), the error, the model, tokens
in, out and from cache, the cost, and how many figures `verify` could not
trace. Card 3 asks for this per job and card 6 asks that a failed run be
visible: a scheduled run keeps what each step did in `details`, the work it
causes (the forecast saved, the summary written) is filed with
`triggered_by = 'schedule'`, and a run the server died in is closed as
`failed` when the next server starts. The rows that jobs write (`findings`, `cards`, `forecast_runs`,
`reports`, `messages`) carry `job_run_id`. "Where did this card come from?"
then has an answer.

## Later steps

These are sketched here so the first schema leaves room for them. They are not
built in step 1.

| Card | Adds |
|---|---|
| 8, [[login-on-the-app]] | `users` (email, name), `memberships` (user, company, role: ceo, reviewer, accountant), `auth_sessions` (token hash, expires). Sessions in the database are what let a login survive a restart. |
| 9, [[email-delivery]] | `deliveries`: which report or card went to whom, sent, opened, link tapped. This is the proxy for CEO time in [[service-metrics]]. |
| 11, [[magic-links]] | `magic_links`: token hash, the card and option it approves, expiry, used at. Store only the hash. |
| 15, [[human-review]] | `companies.review_mode` (onboarding, graduated, mature). The queue itself is the `status` column on `reports` and `cards`, not a new table. |
| [[tenant-isolation]] | Postgres with row-level security on `company_id`. `audit_log`: at, company, actor, read or write, target, details; insert-only. A test that company B sees none of A's rows. |
| [[connect-own-accounting-system]] | `connections`: company, provider (tripletex, fiken, poweroffice, visma, bank), client id, the refresh token **encrypted** with a key from the environment, status, last success. The token rotation in `tlx_oauth.py` writes here instead of `.env`. |
| [[memory-approvals]] | `memory_entries`: type (operating rule, customer behaviour, explanation, goal), the text, a structured JSON part for anything that moves a number, status (suggested, confirmed, outdated), source (a conversation, card or document), valid from/to, who confirmed it. Later an `embedding` column with pgvector for search by meaning. |
| [[data-sync]] | A separate set of synced tables: `sync_runs`, `accounts`, `postings`, `invoices`, `bank_transactions`. Each has `source_system` and `source_id`, and column names that do not belong to Tripletex, so Fiken and Visma land in the same tables. That is the playbook's "one common data model". Only then are figures computed from the database instead of live. |

## Build order

**Step 1 is card 4 ([[state-database]]).** It also closes
[[sessions-out-of-process]].

1. `backend/db.py`: `connect()`, `tx()` (a transaction that commits or rolls
   back), `company_id()`, `next_ref()`, `migrate()`. SQLite connections set
   `foreign_keys=ON`, `journal_mode=WAL` (readers do not block the writer) and
   a `busy_timeout`, so a second writer waits instead of failing.
2. `backend/migrations/001_init.sql`: the SQL in the appendix, minus
   `forecast_scores`. `migrate()` runs at startup and records each file in
   `schema_version`.
3. Move one module at a time, behind its existing functions, with the tests
   green after each: `memory` → `cards` → `definitions` → `company` →
   `industry` → `summary` → chat sessions → `job_runs`.
4. A one-off import from `state/*.json`. It keeps every ref and date and sets
   the counters past the highest one. It renames each file to
   `*.json.migrated` and does not delete it. It runs once: the import
   records itself in `schema_version`.
5. Start writing `forecast_runs` and `bank_balances` daily, so card 5 has
   history to score when it starts.
6. Tests: `tests/_tmp.py` gets a `db()` helper that points `db.py` at a fresh
   temporary file, as `store()` does for the JSON files now.

**Step 2 is card 5 ([[forecast-ledger]]):** `forecast_scores` and the scoring.
After that, each card above adds its own tables.

### What a moved function looks like

The signature, the return value and the callers stay the same. The lock and
the JSON file go.

```python
# before: memory.py
def add_finding(topic, severity, statement, metric=None, value=None) -> dict:
    with _lock:
        data = _load()
        rec = {"id": _next_id(data, "F"), "opened": _today(), ...}
        data["findings"].append(rec)
        _save(data)
    return rec

# after: memory.py
def add_finding(topic, severity, statement, metric=None, value=None) -> dict:
    with db.tx() as conn:
        ref = db.next_ref(conn, "memory", "F")
        conn.execute(
            "INSERT INTO findings (company_id, ref, opened_on, topic, severity,"
            " statement, metric, value) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (db.company_id(), ref, _today(), topic, severity, statement,
             metric, value))
    return {"id": ref, "opened": _today(), "topic": topic, ...}
```

The `?` placeholders matter. Values are never pasted into the SQL string,
which is what keeps a customer name like `O'Brien AS` from breaking the query,
or worse.

## Appendix: step 1 and 2 schema (SQLite)

For Postgres, change these types and nothing else:
`INTEGER PRIMARY KEY` → `BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY`
(*by default*, so the copy from SQLite can keep its ids); other `INTEGER` ids,
references and `*_ore` → `BIGINT`; date `TEXT` → `DATE`; time `TEXT` →
`TIMESTAMPTZ`; JSON `TEXT` → `JSONB`; `REAL` → `DOUBLE PRECISION`. The partial
indexes, `CHECK`s and `UPDATE … RETURNING` (for `counters`) work as written.

```sql
CREATE TABLE schema_version (
  version     TEXT PRIMARY KEY,         -- '001_init', 'import_json'
  applied_at  TEXT NOT NULL
);

-- Who ---------------------------------------------------------------------

CREATE TABLE companies (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  org_number  TEXT UNIQUE,
  created_at  TEXT NOT NULL
);

CREATE TABLE counters (
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  series      TEXT NOT NULL,            -- 'memory' (F, P, D) | 'cards' (K)
  value       INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (company_id, series)
);

-- Ops: first, because most tables point at it ----------------------------

CREATE TABLE job_runs (
  id                 INTEGER PRIMARY KEY,
  company_id         INTEGER NOT NULL REFERENCES companies(id),
  job                TEXT NOT NULL,     -- chat | summary | industry | forecast | morning | watch | weekly_brief
  triggered_by       TEXT NOT NULL,     -- user | schedule | startup
  status             TEXT NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'ok', 'partial', 'failed')),
  started_at         TEXT NOT NULL,
  finished_at        TEXT,
  error              TEXT,
  model              TEXT,
  input_tokens       INTEGER,
  output_tokens      INTEGER,
  cache_read_tokens  INTEGER,
  cost_usd           REAL,
  unverified         INTEGER,           -- figures verify.py could not trace
  details            TEXT               -- JSON
);
CREATE INDEX job_runs_recent ON job_runs (company_id, job, started_at);

-- The company's own words ---------------------------------------------------

CREATE TABLE company_texts (
  id          INTEGER PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  text        TEXT NOT NULL,
  settings    TEXT NOT NULL DEFAULT '{}',   -- JSON: the parsed key: value block
  saved_at    TEXT NOT NULL,
  saved_by    TEXT                          -- a user id once login exists
);
CREATE INDEX company_texts_latest ON company_texts (company_id, saved_at);

CREATE TABLE kpi_definitions (            -- product-wide: no company_id
  kpi_id       TEXT NOT NULL,
  version      INTEGER NOT NULL,
  fingerprint  TEXT NOT NULL,
  source       TEXT NOT NULL,             -- calc | industry
  label        TEXT,
  formula      TEXT NOT NULL,
  inputs       TEXT,
  unit         TEXT,
  code         TEXT NOT NULL,
  recorded_on  TEXT NOT NULL,
  note         TEXT,
  PRIMARY KEY (kpi_id, version)
);

CREATE TABLE industry_profiles (
  id          INTEGER PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  decided_at  TEXT NOT NULL,
  industry    TEXT,
  confidence  TEXT,
  profile     TEXT NOT NULL,              -- JSON: KPIs chosen, reasoning, evidence
  job_run_id  INTEGER REFERENCES job_runs(id)
);
CREATE INDEX industry_profiles_latest ON industry_profiles (company_id, decided_at);

-- What the CFO saw ----------------------------------------------------------

CREATE TABLE kpi_snapshots (
  company_id        INTEGER NOT NULL REFERENCES companies(id),
  on_date           TEXT NOT NULL,
  kpi               TEXT NOT NULL,        -- 'bank', 'omsetning', 'likviditetsgrad', ...
  value             REAL NOT NULL,
  definitions_hash  TEXT,
  PRIMARY KEY (company_id, on_date, kpi)
);

CREATE TABLE bank_balances (
  company_id   INTEGER NOT NULL REFERENCES companies(id),
  on_date      TEXT NOT NULL,
  account      TEXT NOT NULL,             -- ledger account, e.g. '1920'
  source       TEXT NOT NULL CHECK (source IN ('bank_feed', 'ledger', 'psd2')),
  balance_ore  INTEGER NOT NULL,
  PRIMARY KEY (company_id, on_date, account, source)
);

-- What it predicted ---------------------------------------------------------

CREATE TABLE forecast_runs (
  id                  INTEGER PRIMARY KEY,
  company_id          INTEGER NOT NULL REFERENCES companies(id),
  made_on             TEXT NOT NULL,
  purpose             TEXT NOT NULL DEFAULT 'weekly'
                      CHECK (purpose IN ('weekly', 'adhoc')),
  opening_ore         INTEGER NOT NULL,
  opening_source      TEXT,               -- bank_feed | ledger
  low_committed_ore   INTEGER,
  low_committed_week  TEXT,               -- week start date
  low_expected_ore    INTEGER,
  low_expected_week   TEXT,
  assumptions         TEXT NOT NULL DEFAULT '{}',   -- JSON
  definitions_hash    TEXT,
  job_run_id          INTEGER REFERENCES job_runs(id)
);
-- One scored forecast per company per day; ad-hoc runs are not limited.
CREATE UNIQUE INDEX forecast_runs_one_weekly
  ON forecast_runs (company_id, made_on) WHERE purpose = 'weekly';

CREATE TABLE forecast_weeks (
  company_id           INTEGER NOT NULL REFERENCES companies(id),
  run_id               INTEGER NOT NULL REFERENCES forecast_runs(id),
  week_no              INTEGER NOT NULL CHECK (week_no BETWEEN 0 AND 12),
  week_start           TEXT NOT NULL,
  committed_close_ore  INTEGER NOT NULL,
  expected_close_ore   INTEGER NOT NULL,
  PRIMARY KEY (run_id, week_no)
);

CREATE TABLE forecast_flows (
  id          INTEGER PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  run_id      INTEGER NOT NULL REFERENCES forecast_runs(id),
  week_no     INTEGER NOT NULL,
  scenario    TEXT NOT NULL CHECK (scenario IN ('committed', 'expected')),
  kind        TEXT NOT NULL,              -- ar | ar_late | ap | wages | vat_future | opex | ...
  label       TEXT,
  amount_ore  INTEGER NOT NULL            -- money in is positive, out is negative
);
CREATE INDEX forecast_flows_run ON forecast_flows (run_id, week_no);

-- Step 2, card 5
CREATE TABLE forecast_scores (
  company_id     INTEGER NOT NULL REFERENCES companies(id),
  run_id         INTEGER NOT NULL REFERENCES forecast_runs(id),
  horizon_weeks  INTEGER NOT NULL CHECK (horizon_weeks BETWEEN 1 AND 12),
  target_date    TEXT NOT NULL,
  forecast_ore   INTEGER NOT NULL,        -- the expected line for that week
  actual_ore     INTEGER NOT NULL,        -- bank_balances on that day
  error_pct      REAL,
  attribution    TEXT,                    -- JSON: the miss by flow kind
  scored_on      TEXT NOT NULL,
  PRIMARY KEY (run_id, horizon_weeks)
);

CREATE TABLE predictions (
  id          INTEGER PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  ref         TEXT NOT NULL,              -- 'P001'
  made_on     TEXT NOT NULL,
  period      TEXT NOT NULL,
  metric      TEXT NOT NULL,
  expected    REAL NOT NULL,
  low         REAL,
  high        REAL,
  basis       TEXT,
  actual      REAL,
  scored_on   TEXT,
  error_pct   REAL,
  note        TEXT,
  job_run_id  INTEGER REFERENCES job_runs(id),
  UNIQUE (company_id, ref)
);

-- What it raised and what was decided ---------------------------------------

CREATE TABLE findings (
  id          INTEGER PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  ref         TEXT NOT NULL,              -- 'F001'
  opened_on   TEXT NOT NULL,
  topic       TEXT NOT NULL,
  severity    TEXT NOT NULL,
  statement   TEXT NOT NULL,
  metric      TEXT,
  value       REAL,
  status      TEXT NOT NULL DEFAULT 'open',   -- open | resolved | ...
  closed_on   TEXT,
  outcome     TEXT,
  job_run_id  INTEGER REFERENCES job_runs(id),
  UNIQUE (company_id, ref)
);
CREATE INDEX findings_by_status ON findings (company_id, status);

CREATE TABLE cards (
  id            INTEGER PRIMARY KEY,
  company_id    INTEGER NOT NULL REFERENCES companies(id),
  ref           TEXT NOT NULL,            -- 'K001'
  key           TEXT,                     -- dedup key, e.g. 'collections:Skanska'
  source        TEXT NOT NULL CHECK (source IN ('auto', 'agent')),
  kind          TEXT,
  urgency       TEXT NOT NULL DEFAULT 'medium'
                CHECK (urgency IN ('high', 'medium', 'low')),
  amount_ore    INTEGER,
  title         TEXT NOT NULL,
  body          TEXT,
  status        TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'snoozed', 'done', 'dismissed', 'resolved')),
  created_on    TEXT NOT NULL,
  refreshed_on  TEXT,
  snooze_until  TEXT,
  woke_on       TEXT,
  closed_on     TEXT,
  released_on   TEXT,
  options       TEXT NOT NULL DEFAULT '[]',   -- JSON: the buttons
  draft         TEXT,                         -- JSON: the prepared e-mail
  evidence      TEXT NOT NULL DEFAULT '[]',   -- JSON
  follow_up     TEXT,                         -- JSON: the card this one follows up
  decided       TEXT,                         -- JSON: the latest decision
  job_run_id    INTEGER REFERENCES job_runs(id),
  UNIQUE (company_id, ref)
);
-- The database itself refuses a second live card for the same thing.
CREATE UNIQUE INDEX cards_one_live_per_key
  ON cards (company_id, key) WHERE status IN ('open', 'snoozed');
CREATE INDEX cards_by_status ON cards (company_id, status);

CREATE TABLE card_events (
  id            INTEGER PRIMARY KEY,
  company_id    INTEGER NOT NULL REFERENCES companies(id),
  card_id       INTEGER NOT NULL REFERENCES cards(id),
  at            TEXT NOT NULL,
  event         TEXT NOT NULL
                CHECK (event IN ('created', 'refreshed', 'decided', 'woke',
                                 'resolved', 'released')),
  option_id     TEXT,
  effect        TEXT,                     -- approve | snooze | delegate | dismiss
  label         TEXT,
  note          TEXT,
  actor         TEXT,                     -- 'system', 'ceo', a user id once login exists
  draft_edited  INTEGER CHECK (draft_edited IN (0, 1))
);
CREATE INDEX card_events_by_card ON card_events (card_id, at);

CREATE TABLE decisions (
  id          INTEGER PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  ref         TEXT NOT NULL,              -- 'D001'
  decided_on  TEXT NOT NULL,
  decision    TEXT NOT NULL,
  context     TEXT,
  card_id     INTEGER REFERENCES cards(id),
  UNIQUE (company_id, ref)
);

-- What it wrote and said ----------------------------------------------------

CREATE TABLE reports (
  id          INTEGER PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  kind        TEXT NOT NULL,              -- summary | weekly_brief | monthly_pack | health_check
  period      TEXT NOT NULL,              -- '2026-10-06', '2026-W41', '2026-09'
  written_at  TEXT NOT NULL,
  verdict     TEXT,
  body        TEXT NOT NULL,
  facts       TEXT,                       -- JSON: the figures it was written from
  status      TEXT NOT NULL DEFAULT 'final'
              CHECK (status IN ('final', 'draft', 'in_review', 'approved', 'sent')),
  job_run_id  INTEGER REFERENCES job_runs(id)
);
CREATE INDEX reports_latest ON reports (company_id, kind, period, written_at);

CREATE TABLE conversations (
  id          TEXT PRIMARY KEY,           -- the session_id the UI already sends
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  title       TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX conversations_recent ON conversations (company_id, updated_at);

CREATE TABLE messages (
  id               INTEGER PRIMARY KEY,
  company_id       INTEGER NOT NULL REFERENCES companies(id),
  conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  seq              INTEGER NOT NULL,
  role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content          TEXT NOT NULL,         -- JSON: content blocks as the API takes them
  created_at       TEXT NOT NULL,
  job_run_id       INTEGER REFERENCES job_runs(id),
  UNIQUE (conversation_id, seq)
);
```
