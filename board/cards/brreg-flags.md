---
title: Flag customers with bankruptcy or dissolution notices from Brønnøysund
owner: @agent
milestone: #warnings
created: 2026-10-04
priority: 16
---
## Goal
Brønnøysundregistrene is one of the playbook's three MVP data sources (free and open), and "late or at-risk customer" is a Cash-tier alert. `lookup_company_in_brreg` is already in the read-only allowlist, but nothing uses it.

## Done when
- [x] Every customer with an open receivable is checked against Enhetsregisteret at least weekly
- [x] Bankruptcy, liquidation or dissolution raises a card with the amount at risk
- [x] Results are cached, and a failed lookup is reported rather than treated as clean

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 16 in Next: useful MVP source, but the smallest gain of the list.
- 2026-10-11 (agent): built. Decisions (owner): bankrupt and forced
  dissolution take the customer's invoices out of the forecast; voluntary
  liquidation gets a card but stays in; cards only for real risk, while deleted
  or not-found customers and those with no organisation number go on the
  regnskapsfører's clean-up list; suppliers are a Backlog card. Checked every
  working morning (free and fast: one request per hundred customers), a new
  step `register` in the morning run between the forecast and the cards.
  `backend/brreg.py` matches the invoices' customer names to organisation
  numbers from Tripletex's customer list (active and archived, re-read weekly;
  a "1254-" customer-number prefix is allowed for; two customers with the same
  name and different numbers count as no number), reads Enhetsregisteret
  directly (data.brreg.no, no key), and keeps each customer in `brreg_checks`
  (migration 005). A failed lookup keeps the last status, records why, and
  makes the step partial; nothing is "ok" unless the register said so. The
  card (key `brreg:<org>`, high urgency) lists the invoices, the amount, the
  date and a link to the register, and says what to do: report the claim
  within the deadline. A newly flagged customer rebuilds the forecast before
  the cards are made. Links in a card's details are now clickable in Saker.
- 2026-10-11 (agent): 350 tests pass (8 new). Live: all 44 customers with
  open invoices matched and checked in 1.7 s; 42 ok, 2 private persons, none
  in trouble, none missing a number.
