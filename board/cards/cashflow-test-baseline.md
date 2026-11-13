---
title: Give the cash forecast a test baseline: pytest in the venv, and snapshot tests of the full forecast
owner: @either
milestone: #forecast
created: 2026-11-13
---
## Goal
Card 67, phase 0 of `docs/cashflow-spec.md`: a plug-and-play cash-flow forecast
that works for any company that connects, in a smaller, typed and tested module. Read the
spec first; its principle holds for every phase: the AI chooses the data (the data map),
code fetches and calculates every krone.

Based on `main`, never stacked. The snapshot tests from card 67 stay green, and any number
that changes on purpose is updated in its own commit with the reason.

## Done when
- [ ] pytest installed in `.venv` and in `requirements` (dev). The four cashflow test files run
      green (`tests/test_cashflow*.py`, `tests/test_payday_cash.py`)
- [ ] Snapshot tests: the full `build()` output (weeks, flows, assumptions, warnings) and
      `briefing()` text for the demo company and at least two fixture ledgers, saved and compared
      exactly
- [ ] How to run the tests is documented in `README.md`

## Log
- 2026-11-13 (claude): created from the spec on @edmir's request
