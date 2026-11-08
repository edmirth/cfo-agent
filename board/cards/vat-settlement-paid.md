---
title: Statutory amounts past their deadline count as paid, also on the settlement accounts
owner: @edmir
milestone: #forecast
created: 2026-11-08
---
## Goal
Card 59, step 1 of the cash-flow plan from 2026-11-07.

The forecasts saved in October show the July–August VAT on 12 October up to
and including 11 October. From 17 October the same term, moved to the
settlement account 2740 with the return, was forecast to leave again on 10
December. @edmir: the VAT was paid on Monday 12 October (10 October was a
Saturday). The payment had left the bank, so it was out of the bank figure,
but it was not booked against 2740, and `commitments` read the balance as
one amount and dated it to the next settlement. Week 50 carried the term a
second time.

The rule since 2026-10-03 is that a VAT term is paid on its deadline
(`_completed_term`). It covered 2700–2739, not the settlement account.

## Done when
- [x] What is on 2740 (VAT), 2770 (employer's contribution) and 2600
      (withheld tax) is split by the day each part was booked, payments
      settling the oldest first, and each part gets its own term's deadline
- [x] A part past its deadline counts as paid and is left out of the
      forecast; one still ahead keeps its own deadline
- [x] What was counted as paid is kept in `assumed_paid` and told to the
      agent, so a payment that really is missing can be found
- [x] When the postings cannot be read, or do not add up to the balance, the
      amount stays as before
- [x] Tests, among them the October case
- [x] Checked on the real postings through the Tripletex connector (read
      only): 2740, 2770 and 2600 add up to their balances, the July–August
      VAT and the October withheld tax count as paid, and September–October
      employer's contribution keeps 16 November

## Log
- 2026-11-08 — Built on `vat-settlement-paid`.
  - `backend/commitments.py`: `TERM_DUE` says how a booking day becomes a
    deadline. VAT: the latest term ended by the day it was moved to 2740.
    Employer's contribution: the two-month term of the month booked. Withheld
    tax: the salary it was withheld from. `_open_amounts` lets the payments
    settle the oldest amounts first, `_date_by_term` splits the item by
    deadline and leaves out what is past it.
  - Withheld tax is not in the forecast (`cashflow` pays the gross wages on
    pay day), so for 2600 this changes only the commitments page. Before, a
    balance left on 2600 was dated today.
  - Tests: `tests/test_settled_terms.py`, 11 tests. Suite: 519 passed, 1
    failed. The failure is
    `test_demo.test_lindeskar_is_a_yellow_week_with_one_late_customer`, which
    fails on `main` too, since the demo books depend on today's date.
  - Demo companies: the low points are the same as without the change. In
    Aslefjord, 128 278 kr of withheld tax past its pay day now counts as paid.
  - Not run on the real books from the Mac, since that would renew the
    Tripletex login and log Render out.
- 2026-11-08 — Merged as #96. Checked on the first customer's real postings
  this year through the Tripletex connector: the postings on each account add
  up exactly to its balance, so `_date_by_term` applies. The July–August VAT
  (booked to 2740 on 31 August, paid on 12 October in the bank, not booked as
  paid) and the withheld tax from the October pay day count as paid; the bank
  statements show both payments. September–October employer's contribution is
  dated 16 November.
