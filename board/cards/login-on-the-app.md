---
title: Put a login on the app
owner: @either
milestone: #platform
created: 2026-09-29
---
## Goal
There is none. Anyone who reaches the port gets the CFO and the company's complete ledger — bank balance, every customer, every invoice. On a laptop that is a nuisance; anywhere else it is the blocker.

**Note.** Owner is @either: I can implement whatever you choose, but which mechanism — your own accounts, an identity provider, something in front of the app — is your call. This is the gate on connect-own-accounting-system.

## Done when
- [ ] The app requires a login before any `/api/*` route answers
- [ ] Session handling survives a restart, or fails closed
- [ ] The README's "No auth on the app itself" bullet can be deleted honestly

## Log
- 2026-09-29 (agent): created, transferred from TODO.md and the README's customer-readiness list
