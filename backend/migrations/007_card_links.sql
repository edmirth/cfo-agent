-- 007_card_links: card 11 (magic-links).

-- One row per decision link in a Monday email: opens that one card without a
-- login, for LIFETIME_DAYS, and decides it once. The token itself is never
-- stored, only its SHA-256: the database holds nothing a link can be rebuilt
-- from, and an altered link matches no row.
CREATE TABLE card_links (
  id          INTEGER PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  token_hash  TEXT NOT NULL UNIQUE,       -- sha256 hex of the token
  card_ref    TEXT NOT NULL,              -- K016: the card it opens, and only that
  report_id   INTEGER REFERENCES reports(id),   -- the brief whose email carried it
  created_at  TEXT NOT NULL,              -- UTC
  expires_at  TEXT NOT NULL,              -- UTC
  used_at     TEXT,                       -- UTC, when it decided the card
  option_id   TEXT                        -- what it decided
);
CREATE INDEX card_links_card ON card_links (company_id, card_ref);
