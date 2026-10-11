-- 005_brreg: card 16 (brreg-flags).

-- Each customer with money owing, as Enhetsregisteret last had it. Keyed by
-- the name the invoices carry, which is all the forecast has; the
-- organisation number is matched from Tripletex's customer list about once a
-- week, the register is read every morning. A lookup that failed keeps the
-- last status it had and says so in `error`: a failed lookup is not a clean
-- one, and not a fresh one either.
CREATE TABLE brreg_checks (
  company_id     INTEGER NOT NULL REFERENCES companies(id),
  name           TEXT NOT NULL,             -- the customer, as invoiced
  org_number     TEXT,                      -- NULL: none in Tripletex
  private        INTEGER NOT NULL DEFAULT 0 CHECK (private IN (0, 1)),
  matched_on     TEXT,                      -- when the customer list was read
  status         TEXT NOT NULL DEFAULT 'unchecked'
                 CHECK (status IN ('unchecked', 'ok', 'bankrupt', 'forced', 'liquidation',
                                   'deleted', 'not_found', 'no_org', 'private')),
  since          TEXT,                      -- the register's date for it, if any
  register_name  TEXT,                      -- the name the register has
  checked_on     TEXT,                      -- the last lookup that answered
  error          TEXT,                      -- the last lookup's failure, if it failed
  PRIMARY KEY (company_id, name)
);
