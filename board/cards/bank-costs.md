---
title: Build the money going out from the bank lines, at the median month
owner: @edmir
milestone: #forecast
created: 2026-11-08
---
## Goal
Card 64, from the plan in `smarter-cashflow.md`. The forecast took its
running costs from the accounts, which are only as current as the
bookkeeping. At the first customer that was about a third less than what left
the bank, and loan instalments were in no line at all, since they are not a
cost in the accounts. Card 63 gave every bank line a category. This builds the
running costs from them.

## Done when
- [x] A usual month from the bank: suppliers, card, rent, loans and leasing,
      insurance, pension, fees and the accountant, gross. Not wages, taxes
      or VAT, which have their own dated lines, and not the unknown ones.
      The median of the closed months (`bankcat.costs`)
- [x] A month above 1.5 × the median is a one-off: named, and left out of
      the shares and of when in the month the money leaves
- [x] Paid on the days the bank shows it leaving (the four periods of the
      month); this month, only what has not left yet
- [x] Nothing counted twice: the open bills, the fixed bills and the bills
      booked without one come off the month they are paid in
- [x] The committed line takes what comes whatever is sold (rent, loans,
      insurance, pension, fees, accountant) plus the contract share of the
      rest; the expected line the remainder
- [x] The accounts carry the costs as before when the bank cannot be read,
      has fewer than three closed months, or more than 10 % of the money
      out has no category, and the forecast says why
- [x] The briefing says where the costs come from, the median, the shares
      and the one-off months
- [x] Tests with made-up figures
- [ ] @edmir checks the chart on app.arvaka.no after the deploy

## Log
- 2026-11-08 — Built on `bank-costs`.
  - `backend/bankcat.py`: `costs`, called from `summary` with today's date.
  - `backend/cashflow.py`: `_bank_costs` decides whether the bank carries
    the costs (`BANK_UNKNOWN_MAX`); in the month loop the bank level, less
    what is already dated in the month (`known_by_month`), spread with
    `_cost_parts` on the bank's own profile (terms 0, the line is the
    payment). Assumptions `kostnader_kilde` and `kostnader_fra_banken`; the
    briefing via `_bank_cost_words`.
  - No season on the bank costs: six months cannot give one. The accounts'
    season stays on the fallback.
  - On the real books through the Tripletex connector (read only, the rules
    run in its sandbox, nothing kept): the usual month is 311 191 kr
    (May–October), September 640 828 kr is held out as a one-off (suppliers
    254 000, accountant 110 000, rent 95 000), 45 % is certain, and 42 076 kr
    had left in November by the last bank line on 5 November. Loans and
    leasing are 9 % of it, which the forecast did not have before.
  - Suite: 582 passed.
