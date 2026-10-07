-- 002_forecast_scores: step 2 of docs/database.md, card 5 (forecast-ledger).

-- The open invoices and bills a forecast expected, and when, so a miss can be
-- put down to who paid later than expected. JSON: {"ar": [...], "ap": [...]}.
ALTER TABLE forecast_runs ADD COLUMN items TEXT;

-- Each weekly forecast against what the bank showed 1, 2 and 4 weeks later.
CREATE TABLE forecast_scores (
  company_id     INTEGER NOT NULL REFERENCES companies(id),
  run_id         INTEGER NOT NULL REFERENCES forecast_runs(id),
  horizon_weeks  INTEGER NOT NULL CHECK (horizon_weeks BETWEEN 1 AND 12),
  target_date    TEXT NOT NULL,           -- the Sunday that week closes
  forecast_ore   INTEGER NOT NULL,        -- the expected line for that week
  committed_ore  INTEGER,                 -- the floor, kept for reference
  actual_ore     INTEGER NOT NULL,        -- bank_balances, bank_feed, summed
  actual_on      TEXT NOT NULL,           -- the day that balance is true of
  error_pct      REAL,                    -- (forecast - actual) / |actual|
  attribution    TEXT,                    -- JSON: the miss by who paid when
  scored_on      TEXT NOT NULL,
  PRIMARY KEY (run_id, horizon_weeks)
);
CREATE INDEX forecast_scores_by_target ON forecast_scores (company_id, target_date);
