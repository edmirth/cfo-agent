---
title: Build the cash coming in from the invoice register
owner: @edmir
milestone: #forecast
created: 2026-11-08
---
## Goal
Card 60, step 2 of the cash-flow plan from 2026-11-07, and the rest of card 17.

@edmir: "when we send out invoices then the sum of those numbers are the sum
we get in our bank account. Right now the 13 week cash looks like we dont
send any invoice anymore, and it dosent take into consideration that we are
going to send a bunch of new invoices from the 30th november as we always do
every end of the month, with some 30 days due and some 45 days due."

Today the money coming in is built three ways at once: the open invoices; the
customers billed every month ("Fast fakturering", at their lowest month, in
the committed line); and the revenue in the accounts × 1.25, less what is
already invoiced and less the contracts, in the expected line. The month-end
invoice run is never one thing anyone can see.

## The design
Three parts, all from the invoice register:

- **A. Sent:** every open invoice, on its due date plus the customer's own
  lateness. As now.
- **B. The next invoice runs:** 30 November, 31 December, … Per customer:
  invoiced every month or not, the usual amount, their own invoice day, their
  own terms (30 or 45 days), their own lateness. The committed line takes the
  lowest of their recent months, the expected line the usual one.
- **C. Other invoicing:** customers not billed every month, from the usual
  monthly amount of it. Expected line only.

- Each run is one line in the week table, "Fakturering 30. november (ikke
  sendt)", with how much on 30 and on 45 days; the week opens to show it per
  customer.
- When a run is sent, B for that month drops out and the invoices in A take
  over, so the forecast follows what is invoiced.
- The VAT on sales follows the same invoices.
- The revenue in the accounts becomes a check: when the invoices for a month
  do not add up to the usual revenue for it, the forecast says so.

Added 2026-11-08, from the plan in `smarter-cashflow.md`: the usual month is
the median, never the average, and a month of other invoicing above 1.5 × the
median is a one-off (the first customer had a big job in August). It is left
out of how the rest is timed, and named.

## Done when
- [x] Receipts come from A, B and C, and the revenue in the accounts no
      longer makes receipts (once the register has three closed months)
- [x] Each run is one line in the week table per term, "Fakturering november
      (ikke sendt), 45 dager", in the committed and the expected line
- [x] A sent run replaces the prediction for that month
- [x] The VAT on sales follows the invoices
- [x] Tests: customers on their own days and terms, invoicing through the
      month, this month's remainder, the median and the floor, a one-off big
      job, a young register, the check against the accounts
- [x] The method backtested on the real books through the Tripletex connector
- [ ] @edmir checks the chart on app.arvaka.no after the deploy
- [ ] A recurring backtest on the server (card 61)

## Log
- 2026-11-08 — Built on `invoice-runs`.
  - `backend/cashflow.py`: `_invoice_runs` replaces `_recurring_sales`. A
    customer invoiced in 5 of the last 6 closed months and each of the last 3
    is regular. Usual = the median of his months; the committed line takes the
    lowest of the last 3, the expected line the rest up to his usual month.
    Each customer on the days and terms of his last 3 months; this month only
    the days still to come, less what he has been invoiced already.
  - `_other_invoicing`: everyone else, as one stream at its median month, in
    the expected line only. Months above `UNUSUAL` × the median are named in
    `annen_fakturering.uvanlige` and left out of the timing.
  - With fewer than `RUN_MIN_MONTHS` closed months in the register, the old
    reading of the accounts stays. Otherwise the accounts are a check:
    `fakturering_per_maned` holds both, and a warning says when next month
    differs by more than 35 %.
  - The VAT on future invoicing and the share of running costs tied to the
    committed line follow the register.
  - The agent's briefing says how the runs and the one-offs are read.
  - Tests: 9 rewritten in `test_cashflow_build.py` (they assumed the revenue
    in the accounts as receipts), 9 new in `test_invoice_runs.py`. Suite: 529
    passed, 0 failed.
  - Backtest of the method on the first customer's real invoices, through the
    Tripletex connector (read only), predicting each month from the six
    before it: the committed line for the regular customers was below what
    was actually invoiced in August, September and October. The median kept
    the August job out: in October an average would have put the other
    invoicing about twice as high as what came, the median about a third
    too high. August itself could not be predicted from history (−40 %); that
    is what card 66 is for. September +15 %, October −23 %.
  - Demo: all three companies read the register. Kvarnheim's project
    invoicing is uneven, and the new check says its invoices and its accounts
    differ for December (card 40, project mode).
- 2026-11-08 — Merged as #97. @edmir's chart on app.arvaka.no read lower than
  the forecast built by hand from the same books, by about a million kroner
  from week 46 on. Cause, found on the real books through the connector: the
  bank lines left unmatched in the reconciliation were all taken as unbooked
  and set against the customers' other open invoices, though most of them had
  been booked as payments on their invoices and only not matched. Fixed on
  `settle-booked-payments`: `bankgap.unbooked` sets each line against the
  booked, unmatched payments of the same counterparty first. On the real
  books, what was taken off open invoices fell from about a million kroner to
  two small payments that really were unbooked. Suite: 535 passed.
- 2026-11-08 — #98 merged (booked but unmatched bank lines). @edmir asked
  whether the pay day on the 10th is costed from what earlier pay days paid.
  It was not: the amount came from the wage accounts, which carry accruals
  and holiday pay as they are earned. On `payroll-from-payments`,
  `cashflow.payroll_paid` reads the payroll vouchers instead (the vouchers
  touching 5000–5099): what each pays out of the bank, or leaves owing on the
  trekk and net-pay accounts when the payment is not booked. A pay day is the
  median of the last six months' runs on the pay day; extra runs (the one
  after August's one-off job) and the holiday-pay month are kept out. Fewer
  than three months measured keeps the wage accounts. On the real books the
  measured pay day is about a tenth below the wage accounts' figure. Suite:
  545 passed.
- 2026-11-08 — #99 merged (pay day from the payroll vouchers). A scan of the
  receipts path with simulated invoicing (an invoice sent, above usual, a new
  customer, one paid at once) found the money moved correctly to the due
  date with the total unchanged, and five ways the chart could jump without
  anything happening. Fixed on `forecast-robustness`:
  - One invoice over 30 days late took a regular customer out of both lines;
    a 2 000 kr invoice removed a whole customer. Now more than his usual
    month late takes him out; over 5 000 kr and a quarter of his month takes
    him out of the committed line only; less changes nothing.
  - A month closed without his invoice dropped him from the regular
    customers. Now five of six months keeps him regular; a missed month only
    takes him out of the committed line.
  - His usual invoice days ten days past with nothing sent left him in the
    committed line. Now the expected line only.
  - One month with no invoicing at all sent the whole forecast back to the
    accounts. Now three of the last six months is enough.
  - Money due on a weekend or holiday now lands on the next banking day.
  - The pay day is read once a day, and an unread ledger is said.
  The agent's briefing names the regular customers outside the committed
  line and why. Suite: 551 passed.
- 2026-11-08 — #100 merged. A second scan found three more, fixed on
  `paid-through-bank-date`:
  - The day after a pay day or a tax deadline, both were counted as paid by
    the calendar while the bank figure, a banking day behind, did not have
    them yet. Now `commitments.paid_by` is the first day the bank figure does
    not cover (its last line + 1), and pay days and deadlines from there on
    are still paid in the forecast, dated today.
  - Company tax on 2500 is dated by its two instalments (15 February and
    15 April after it was booked), and a half past its deadline counts as
    paid, as the VAT on 2740 does since card 59.
  - A credited invoice and its credit note both reported the balance between
    them; only the credit note counts now.
  Suite: 562 passed.
