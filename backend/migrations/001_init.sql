-- 001_init: the step 1 schema from docs/database.md, minus forecast_scores
-- (card 5). Every table that holds a company's data carries company_id.
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
  job                TEXT NOT NULL,     -- chat | summary | industry | forecast | watch | weekly_brief
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
