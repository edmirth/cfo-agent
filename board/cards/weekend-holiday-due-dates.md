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
- [ ] Due dates roll forward to the next working day, not backward
- [ ] Norwegian public holidays are handled, not just Saturday and Sunday
- [ ] AGA dated Sun 15 Nov lands on Mon 16 Nov, and the reported low week is recomputed
- [ ] `assumptions` declares that the shift is applied
- [ ] A test covers a Saturday, a Sunday and a holiday

## Log
- 2026-09-29 (agent): created
