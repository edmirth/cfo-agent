---
title: Move sessions out of the process
owner: @either
milestone: #platform
created: 2026-09-29
---
## Goal
`SESSIONS` in `main.py` is a process-local dict, so the app runs one worker and loses every conversation on restart. `state/` is single-tenant for the same reason: no tenant in the path.

**Note.** Owner is @either: Redis or Postgres is an infrastructure decision that depends on where this ends up hosted.

## Done when
- [ ] Conversations survive a restart
- [ ] More than one worker can serve the app
- [ ] The store is keyed per tenant, not per process

## Log
- 2026-09-29 (agent): created, transferred from TODO.md and the README's customer-readiness list
