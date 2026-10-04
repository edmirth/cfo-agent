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
- [ ] Every row carries a company id, even while there is only one company
- [ ] `cards.json` and `memory.json` are migrated once without losing history
- [ ] Concurrent requests cannot corrupt state
- [ ] Tests run against a temporary database

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 4 in Next: the forecast ledger, job runs and the brief all need somewhere to be stored.
