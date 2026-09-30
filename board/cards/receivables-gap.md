---
title: Find why open invoices do not reconcile to account 1500
owner: @agent
milestone: #liquidity
created: 2026-09-29
---
## Goal
Open invoices sum to 940 926 against 1 997 489 on account 1500, and every customer's ledger balance exceeds their invoice total by a different ratio. The residual is currently carried and declared, which is honest but not an answer.

**Note.** Figures quoted are from the original TODO and predate this session — re-measure before trusting them.

## Done when
- [x] The cause of the gap is identified and named, not just carried
- [x] `cashflow.py` either attributes the residual or says precisely why it cannot
- [x] The explanation holds against a second period, not just today

## Log
- 2026-09-29 (agent): created, transferred from TODO.md
- 2026-09-30 (agent): **found it — an off-by-one on an exclusive bound.**

  `search_invoices` documents `invoiceDateTo` as EXCLUSIVE. `_month_bounds`
  returned the *last day* of the month and passed it straight in, so every
  invoice dated on a month end was silently dropped. This company invoices
  monthly at month end, which is why the loss was so large and why each
  customer's ratio differed — it depended purely on how many of their invoices
  happened to fall on the last day.

  Fbb Entreprenør made it visible: subledger 74 276, zero invoices found by the
  app. Their four outstanding invoices are dated 2026-09-30, 2026-08-31,
  2026-05-31 and 2025-10-31 and sum to exactly 74 276. They reconciled all
  along; nothing could see them.

  | | before | after |
  |---|---|---|
  | open invoices found | 1 215 575 (77) | **2 526 405 (170)** |
  | account 1500 | 2 539 600 | 2 539 600 |
  | unexplained residual | 1 324 025 (52 %) | **13 195 (0.5 %)** |

  The residual is no longer material. What is left is of the same order as the
  credit balances in the subledger (four customers, −24 774 together) of which
  the app now carries one (−5 200), so the remainder is most likely payments and
  credit notes that belong to invoices outside the window. It is small enough to
  carry honestly, which is what the card asked for.

  Three tests pin the window: the end is the first of the next month, December
  rolls into January, and consecutive windows meet exactly so no day is counted
  twice or missed.
