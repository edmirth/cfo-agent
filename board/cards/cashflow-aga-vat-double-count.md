---
title: Stop paying AGA and VAT twice in the months a tax payment goes out
owner: @either
milestone: #forecast
created: 2026-11-13
---
## Goal
Card 68, phase 1 of `docs/cashflow-spec.md`: a plug-and-play cash-flow forecast
that works for any company that connects, in a smaller, typed and tested module. Read the
spec first; its principle holds for every phase: the AI chooses the data (the data map),
code fetches and calculates every krone.

Based on `main`, never stacked. The snapshot tests from card 67 stay green, and any number
that changes on purpose is updated in its own commit with the reason.

## Done when
- [ ] AGA and VAT "already this month" read from credits only
- [ ] Regression test for a payment month (e.g. November) after payroll is posted
- [ ] Snapshot updated in a separate commit, with the changed weeks explained

## Log
- 2026-11-13 (claude): created from the spec on @edmir's request
