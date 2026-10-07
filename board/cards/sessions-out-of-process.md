---
title: Move chat sessions from an in-process dict into a shared store
owner: @either
milestone: #platform
created: 2026-09-29
---
## Goal
`SESSIONS` in `main.py` is a process-local dict, so the app runs one worker and loses every conversation on restart. `state/` is single-tenant for the same reason: no tenant in the path.

**Note.** Owner is @either: Redis or Postgres is an infrastructure decision that depends on where this ends up hosted.

## Done when
- [x] Conversations survive a restart
- [x] More than one worker can serve the app
- [x] The store is keyed per tenant, not per process

## Log
- 2026-09-29 (agent): created, transferred from TODO.md and the README's customer-readiness list
- 2026-10-04 (agent): covered by [[state-database]], which stores chat sessions along with forecasts, cards and memory.
- 2026-10-07 (agent): done in [[state-database]] PR B: conversations live in the database, keyed by company, and survive a restart (checked live). Any worker on the same machine reads the same file; more than one machine waits for Postgres.
