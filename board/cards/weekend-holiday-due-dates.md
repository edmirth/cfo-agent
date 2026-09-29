---
title: Roll due dates forward off weekends and Norwegian holidays
owner: @agent
milestone: #forecast
created: 2026-09-29
---
## Goal
Norwegian due dates landing on a Saturday, Sunday or holiday move to the next working day. `commitments.py` and `cashflow.py` use the literal date, so obligations are placed *earlier* than they are actually paid.

**This is wrong now, not merely missing.** Checked against the current ledger:

- AGA 199 990 is dated **Sun 15 Nov 2026** — confirmed a Sunday, and this one moves the reported low point.
- The original TODO also cited MVA 640 930 on Sat 10 Oct. That has since moved: account 2740 is now zero and the live MVA is 905 542 due **10 Dec**, which is a Thursday. So one of the two original examples still bites and one has aged out.

**Note.** Came from TODO.md lane 1, where it was the one item flagged as actively wrong rather than absent.

## Done when
- [x] Due dates roll forward to the next working day, not backward
- [x] Norwegian public holidays are handled, not just Saturday and Sunday
- [x] AGA dated Sun 15 Nov lands on Mon 16 Nov, and the reported low week is recomputed
- [x] `assumptions` declares that the shift is applied
- [x] A test covers a Saturday, a Sunday and a holiday

## Log
- 2026-09-29 (agent): created
- 2026-09-30 (agent): built `backend/workdays.py` — Easter-anchored Norwegian
  holiday calendar, `forward()` and `backward()`. Applied per obligation in
  `commitments.py` and to the payroll date in `cashflow.py`. 10 tests added.
- 2026-09-30 (agent): **the direction is not uniform, and the card understated
  this.** Statutory dues roll forward, but wages roll *backward* — a pay day on
  a weekend is paid before it, not after, or the forecast shows money still in
  the account on a day it has already gone. Supplier bills are left alone
  entirely: they carry a real due date from the invoice and guessing which way a
  supplier shifts it would be inventing a fact.
- 2026-09-30 (agent): verified on live data. AGA 199 990 moved from Sun 15 Nov
  to Mon 16 Nov, so it now falls in Uke 47 rather than Uke 46. **The low week did
  not change**, contrary to the original TODO's claim — it is Uke 50 either way,
  driven by the December MVA of 914 542, which already fell on a Thursday. The
  claim was true of the figures when it was written and is not true of today's.
