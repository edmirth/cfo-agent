---
title: The plan for a 13-week cash flow that learns the company's patterns
owner: @edmir
milestone: #forecast
created: 2026-11-08
---
## Why
@edmir, 2026-11-08: "the 13 cash needs to be smarter and understand the
patterns of the company, and not be stiff like it is now, as it could show
that the company could go further down without doing it."

A 13-week forecast built by hand from the first customer's live Tripletex
data (bank lines, invoice register, open invoices, tax accounts) gave a far
calmer and more believable picture than the app. Most of the difference came
from four things: VAT paid twice (card 59), receipts read off the revenue in
the accounts instead of the invoices (card 60), costs read off averages in
the accounts instead of the bank, and a one-off big job in August (with an
extra wage run in September) that would have counted as normal.

## The principle
The engine calculates; the AI explains and asks. The figures come from fixed,
testable rules, so the same input always gives the same answer. The AI reads
the patterns, suggests what looks unusual, and asks the owner what only he
knows. He approves, and it is remembered (card 26).

## The parts
1. **Sources.** The invoice register for money coming in, the bank lines for
   money going out, the books only for debts with a fixed date (checked
   against the bank, card 59).
2. **A pattern per stream.** Every customer, wages, each supplier, loans: how
   often, which day, how much, which terms. Normal is the median, never the
   average. A month above 1.5 × the median is unusual and kept out of normal.
3. **One-offs and the costs that come with them,** paired and asked about
   (card 65).
4. **Known events ahead,** entered by the owner (card 66).
5. **Ranges.** A safe line (the lowest recent month per stream) and a usual
   line (the median), every week explained.
6. **It learns.** A backtest before launch (card 61) and a weekly score per
   stream that adjusts or flags it (card 62).

## Order
| Card | What | Depends on |
|---|---|---|
| 59 | Taxes past their deadline count as paid | none |
| 60 | Money coming in per customer from the invoice register | none |
| 63 | Bank lines get categories | none |
| 64 | Money going out per stream from the bank | 63 |
| 65 | One-offs and linked costs, asked in Saker | 60, 64 |
| 66 | Known events ahead | 60 |
| 61 | Backtest on the real books | 60, 64 |
| 62 | Weekly score per stream | 61 |

Cards 61 and 62 need the real books read regularly. The server on Render has
the Tripletex login, so they run there; the Mac must not use that login.

Cards 23 and 24 (the AI's role in the 13-week forecast) are covered by 63 and
65.
