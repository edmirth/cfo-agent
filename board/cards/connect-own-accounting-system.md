---
title: Build an in-app screen to connect a customer's own accounting system
owner: @either
milestone: #platform
created: 2026-09-29
---
## Goal
Today it is `scripts/oauth_login.py` — a one-time browser login run from a terminal, writing `TRIPLETEX_CLIENT_ID` and `TRIPLETEX_REFRESH_TOKEN` into `.env`. Fine for one company, impossible to sell. It needs to be a screen the customer walks through, and the same screen is where the key goes in.

This is an epic, not a card — it drags in everything below and is the gate on selling this at all.

**Note.** Owner is @either: I can build the flow, but which providers to support first and what the onboarding screen promises are your calls.

## Done when
- [ ] Per-customer credentials: one `.env` is one company, and `tlx_oauth.py` writes the rotated refresh token straight back into it
- [ ] Login on the app (see the auth card — connecting a live ledger to an unauthenticated page is not shippable)
- [ ] State is per-tenant: `state/memory.json`, `state/profile.json` and the `SESSIONS` dict have no tenant in the path
- [ ] Provider is a choice: Fiken, PowerOffice and Visma, not only Tripletex
- [ ] Capabilities detected at connect time, so we stop promising what a given ledger cannot support

## Log
- 2026-09-29 (agent): created, transferred from TODO.md
