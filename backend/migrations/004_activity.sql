-- 004_activity: card 14 (service-metrics).

-- One row per minute someone had the app open and in focus: the playbook's
-- "CEO time per week". What was looked at is not recorded, only that the app
-- was in use that minute.
CREATE TABLE activity (
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  user_email  TEXT NOT NULL,
  minute      TEXT NOT NULL,              -- '2026-10-10T08:14', UTC
  PRIMARY KEY (company_id, user_email, minute)
);
