---
title: Count the invoicing that is still to be sent, so December does not look like a fall
owner: @edmir
milestone: #liquidity
created: 2026-11-07
---
## Goal
Card 17 on the board: "We only invoice with max 45 days, so most of the
invoices go to 6 weeks ahead, so when we look at December we dont get the
fully picture as the invoices has not been sent out yet."

PRs #58, #60 and #61 put the invoicing that is not sent yet into the
forecast: the season, the company's own invoice day and terms, and each
customer's lateness. On 2026-11-07 the 13-week chart on app.arvaka.no still
showed the committed line ("bundet") going below zero and ending there, and
@edmir: "it dosent seem right, because we will still send invoices".

**Why.** The committed line counted only the invoices already sent, plus the
regular customers. A customer was regular only if each of his last three
months was within 25 % of the others. A cleaning customer with an extra job
or a month of more hours fails that, so the committed line held less than
half of the invoicing that goes out every month.
The low point on the front page and in the Monday email comes from that
line, so it read as if the company would stop invoicing.

**The drop in week 50 is real timing.** In 7–13 December the wages and the
VAT and withheld tax due on 10 December go out together. Most of November's
invoicing goes out around the 30th on 30 days, so it is paid around 30
December. Nothing on the page said what was in a week, so the drop could not
be read.

## Done when
- [x] A customer invoiced in each of the last three closed months counts in
      the committed line however much the amounts vary, at his lowest month
- [x] What a customer has been invoiced this month already is taken off his
      month, so an extra job billed early does not stand in for the invoice
      at month end, and a sent invoice replaces the estimate
- [x] Each week in "Vis uke for uke" opens to show what is in it: customers,
      bills, wages, VAT and tax, with the estimates marked "anslag"
- [x] Tests for both rules
- [ ] @edmir checks the chart on app.arvaka.no after the deploy: the
      committed line now carries the regular invoicing, and week 50 shows
      what it pays

## Log
- 2026-11-07 — Built on `invoicing-ahead`.
  - `backend/cashflow.py` `_recurring_sales`: the 25 % rule
    (`RECURRING_TOLERANCE`) is gone; billed in each of the last
    `RECURRING_MONTHS` closed months is enough, counted at the lowest month.
    This month, only what is left of that month after what is already
    invoiced is projected. The briefing text for the agent says the same.
  - `frontend-react/src/pages/brief.tsx`: a row in the week table opens to
    list the week's items, like ones merged ("3 stk"), money in first and
    largest first. The API already sent the items, so no backend change. On a
    phone the list stays inside the screen while the table scrolls sideways.
  - Tests: the uneven customer is now counted at his lowest month, and an
    extra invoice this month leaves the rest of the month to come. Suite:
    508 passed, 1 failed. The failure is
    `test_demo.test_lindeskar_is_a_yellow_week_with_one_late_customer`, which
    fails on `main` too, since the demo books depend on today's date.
  - The demo companies' low points did not change: their customers are
    billed evenly, so the old rule already caught them. Seen on the
    Kvarnheim demo in a headless browser, at desktop and phone width.
  - Not tried on the real books: running the forecast on the Mac would renew
    the Tripletex login and log Render out. Check on app.arvaka.no.
