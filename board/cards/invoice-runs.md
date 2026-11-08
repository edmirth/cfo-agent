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

## Done when
- [ ] Receipts come from A, B and C, and the revenue in the accounts no
      longer makes receipts
- [ ] Each run is one line in the week table, with its 30- and 45-day parts
- [ ] A sent run replaces the prediction for that month
- [ ] The VAT on sales follows the invoices
- [ ] A test company that invoices at month end on 30 and 45 days, seen from
      mid-October and mid-November
- [ ] Checked against the real books with card 61

## Log
