---
title: Sync Tripletex and bank data into the database on a schedule
owner: @edmir
milestone: #platform
created: 2026-10-04
---
## Goal
Phase 2 data platform: "sync jobs (bank daily, ledger several times a day)". Today every figure is a live Tripletex query with a 10-minute cache, which will not hold for many customers.

## Done when
- [ ] Ledger data synced several times a day, bank data daily
- [ ] Figures are computed from the database, not live queries
- [ ] A failed sync is visible and does not blank the figures

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
