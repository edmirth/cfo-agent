-- 003_watch: card 12 (watch-job).

-- What the morning watch has dealt with, by the candidate's key, so it is not
-- put to the model again the next morning: raised as a card, opened as a
-- finding, or set aside with a reason. A key carries its period
-- (`watch:cost:6300:2026-09`), so the same thing next month is a new key.
CREATE TABLE watch_seen (
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  key         TEXT NOT NULL,
  outcome     TEXT NOT NULL CHECK (outcome IN ('card', 'finding', 'skipped')),
  ref         TEXT,                       -- K012 or F018, when one was made
  reason      TEXT,                       -- why it was set aside
  seen_on     TEXT NOT NULL,
  job_run_id  INTEGER REFERENCES job_runs(id),
  PRIMARY KEY (company_id, key)
);
