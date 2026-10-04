---
title: Isolate each customer's data and keep a full audit log
owner: @edmir
milestone: #platform
created: 2026-10-04
---
## Goal
Before the second customer: "strict isolation per customer" and "read-only tokens where possible, encryption, full audit log". Today the product is one company per installation.

## Done when
- [ ] Tokens, data, jobs and memory are separated per company
- [ ] Every read and write is in an audit log
- [ ] One customer can never see another's data, with a test proving it

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
