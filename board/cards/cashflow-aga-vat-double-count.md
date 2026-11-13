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
- [x] AGA and VAT "already this month" no longer count the month's payment or settlement: the
      month's movement less the payment and settlement vouchers found in its postings
      (`_settled`). Plain credits would also drop input VAT and credit notes, so not that
- [x] Regression tests for a payment month: November with the run journalised before its pay
      day, November with it not yet journalised, and October with a VAT settlement
- [x] Snapshots: nothing moved, on the demo companies or Ullensaker. Neither books hits the
      case (see the log), so no snapshot commit was needed

## Log
- 2026-11-13 (claude): created from the spec on @edmir's request
- 2026-11-13 (claude): done on `cashflow-aga-vat-double-count`.
  - Reproduced first. Two tests failed on the old code exactly as the spec
    said: November's AGA (−112 000) forecast again for a run journalised on
    the 17th after the term was paid on the 16th; October's whole VAT
    (−100 000) instead of the −40 000 left, after a settlement on the 2nd.
    A third, the term paid with the run not yet journalised, passed before
    and after: the fix must not take that month's AGA away.
  - Fix in `cashflow.py`: `_tax_postings` reads this month's postings on
    2700-2779 with the rest of the build, and `_settled` finds the VAT
    settlements (a voucher reaching 2740, or debiting 2700-2709 while
    crediting 2710-2719) and the AGA payments (a voucher whose net on 2770
    is a debit). The trial balance stays the source: the movement less
    those is what the month booked. A failed read takes nothing off, as
    before, and is logged. More than 5 000 postings in a month on those
    accounts is the same failure.
  - Suite: 602 passed under pytest and the plain runner.
  - Demo snapshots unchanged: the demo posts each VAT settlement on the
    term's last day and journalises payroll on its pay day, so no payment
    month carries both. Ullensaker unchanged too, checked by replaying
    today's recording with the old code: the September-October AGA is
    paid on the 15th, payroll is journalised and paid the same day (the
    10th), and its invoicing comes from the register. The bug reaches a
    company whose payroll is journalised before its pay day, or a young
    one on the accounts path that posts its settlement in the payment month.

