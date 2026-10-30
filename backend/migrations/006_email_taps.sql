-- 006_email_taps: card 37 (email-taps).

-- Whether a user lets us measure their use: minutes in the app (`activity`)
-- and taps from the Monday email (`email_taps`). Asked once, changeable on
-- Selskapet. No row is not a yes: nothing is recorded for a user until they
-- have said yes, and nothing after they say no.
CREATE TABLE consents (
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  user_email  TEXT NOT NULL,
  measure     INTEGER NOT NULL CHECK (measure IN (0, 1)),
  at          TEXT NOT NULL,              -- when they last answered, UTC
  PRIMARY KEY (company_id, user_email)
);

-- One row per arrival in the app from a link in the Monday email: which
-- brief, and whether the link was the brief, a card or Saker. What was read
-- after is not recorded.
CREATE TABLE email_taps (
  id          INTEGER PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  user_email  TEXT NOT NULL,
  report_id   INTEGER NOT NULL REFERENCES reports(id),
  link        TEXT NOT NULL CHECK (link IN ('brief', 'card', 'saker')),
  card_id     TEXT,                       -- the card, for link = 'card'
  at          TEXT NOT NULL               -- UTC
);
CREATE INDEX email_taps_report ON email_taps (company_id, report_id);
