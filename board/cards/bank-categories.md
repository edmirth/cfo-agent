---
title: Give every bank line a category
owner: @edmir
milestone: #forecast
created: 2026-11-08
---
## Goal
Card 63, from the plan in `smarter-cashflow.md`. The forecast reads the money
going out off the accounts, which are only as current as the bookkeeping. At
the first customer the October costs were largely unbooked, the input VAT on
costs read as half a per cent of the output VAT, and the running costs came
out about a quarter below what left the bank. The bank lines are what left.
Card 64 builds the costs from them.

## Done when
- [x] Every bank line in the last six closed months and this one has a
      category, by fixed rules in `backend/bankcat.py`: the authorities,
      lenders, insurance, pension, fees, card, NAV, rent and accountant by
      name; customers from the invoice register; employees from the employee
      register however the bank spells them; private persons on the pay day
      as wages; companies and KID payments as suppliers; the rest unknown
- [x] Read once a day; a failed read is not kept
- [x] Each month's money in and out by category, the unknown lines named, and
      the unknown share, in the forecast (`bank_categories`) and the agent's
      briefing
- [x] Tests with made-up names
- [x] On the real books through the Tripletex connector (read only): 96 % of
      the money going out over six months has a category
- [ ] The owner says what the unknown ones are, once, and it is remembered.
      Proposed to go with card 65, which asks the owner in Saker about the
      one-offs: the same question, the same place.

## Log
- 2026-11-08 — Built on `bank-categories`.
  - First pass of the rules on the real books left 17 % of the money going
    out unknown: employees the bank spells otherwise than the register
    (surname first, a middle initial, a digit added, a nickname), and
    suppliers not in the supplier register. Word-for-word name matching, the
    pay-day rule for private persons and the company-suffix rule brought it
    to 4 %, mostly people paid outside the pay day (extra runs) and a few
    companies the bank names without "AS".
  - The running costs the bank shows (suppliers, card, rent, loans and
    leasing, accountant, insurance, pension, fees) are about a third above
    what the accounts give the forecast today. Card 64.
  - Suite: 570 passed.
