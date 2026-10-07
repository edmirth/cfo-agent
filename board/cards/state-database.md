---
title: Store forecasts, cards, memory and job runs in a database
owner: @either
milestone: #platform
created: 2026-10-04
priority: 4
---
## Goal
State is JSON files in `state/`, written under thread locks, and chat sessions live in an in-process dict. The MVP needs more than that: every weekly forecast kept so it can be scored, every job run recorded, and cards and memory that can be queried over time. The playbook's data platform is Postgres with a common data model; SQLite is enough for the pilot and can move to Postgres behind the same functions.

**Note.** Owner is @either: SQLite now or Postgres from day one depends on where you intend to host it. This card also covers [[sessions-out-of-process]].

## Done when
- [ ] A database with tables for forecasts, job runs, cards, memory and chat sessions
- [x] Every row carries a company id, even while there is only one company
- [x] `cards.json` and `memory.json` are migrated once without losing history
- [x] Concurrent requests cannot corrupt state
- [x] Tests run against a temporary database

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 4 in Next: the forecast ledger, job runs and the brief all need somewhere to be stored.
- 2026-10-06 (agent): design written in `docs/database.md`: what goes in and stays out, the tables, seven rules, and the build order. SQLite now, Postgres at [[tenant-isolation]]. The schema in its appendix runs on SQLite 3.45 and its constraints were tested.
- 2026-10-07 (agent): **PR A** of three, following `docs/database.md`.
  `backend/db.py` is the only module that opens a connection: SQLite in
  `state/cfo.db`, WAL, `tx()` takes the write lock up front (BEGIN IMMEDIATE),
  migrations from `backend/migrations/` run once each, and the one company is
  created from `COMPANY_NAME`. `001_init.sql` is the design's step-1 schema
  minus `forecast_scores` — all 20 tables, so every later step only fills them.
  `memory.py` is direct SQL behind unchanged functions; `cards.py` keeps its
  logic on the deck as a list and loads/writes it inside one transaction, with
  `card_events` derived from what changed. Nothing is deleted any more.
- 2026-10-07 (agent): the import runs once at server start, keeps every id
  and date, continues the numbering (F026, K019 next on the real data), and
  renames the files to `*.json.migrated`. Checked on a copy of the real
  `state/`: 12 findings, 2 predictions, 11 decisions, 13 snapshots, 18 cards,
  every field identical, and the memory briefing byte-identical to the one
  built from JSON. 233 tests pass; the runner points everything at a temporary
  database (`CFO_DB`) so no test can reach `state/cfo.db`.
  **Left for PR B:** chat sessions and job runs into their tables. **PR C:**
  forecast runs and bank balances written daily. Then box 1 is ticked.

