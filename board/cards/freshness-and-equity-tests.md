---
title: Add tests for the single-flight cache and the equity ratio
owner: @agent
milestone: #tests
created: 2026-09-29
---
## Goal
Two pieces of new code have no coverage. `freshness.py` is concurrency code — shared in-flight task, `asyncio.shield` against a caller cancelling a build others await — and concurrency is exactly what regresses silently. The equity ratio is computed from account ranges in `overview.py` and is verified only by arithmetic I did by hand.

**Note.** The debt-free case is a real gap: the guard is `if assets and debts is not None`, so a company with no accounts in 2100-2999 reports no equity ratio instead of 100 %.

## Done when
- [x] A test proves two concurrent cold callers cause one build, not two
- [x] A test proves a caller giving up does not cancel the build others are waiting on
- [x] A test proves a failed build does not leave a permanently poisoned in-flight task
- [x] The equity ratio is pinned against known assets and debt, including the debt-free case that currently returns None
- [x] A test covers the thin-margin rounding so 0.043 % never reads as 0.0 again

## Log
- 2026-09-29 (agent): created
- 2026-10-01 (agent): the three cache boxes were already met — those five tests
  were written while fixing the Tripletex 500s, since the semaphore work touched
  the same code.
- 2026-10-01 (agent): the equity ratio was not testable where it sat: a closure
  inside `build()`, reachable only through a live fetch. Lifted to a module-level
  `equity_ratio(rows)` with `account_number()` and `_side_total()` beside it, and
  `build()` now calls it. Seven tests against a trimmed snapshot of the real
  trial balance.
- 2026-10-01 (agent): **fixed the debt-free case rather than only pinning it.**
  The guard was `if assets and debts is not None`, so a company owing nothing
  reported no equity ratio at all. Owing nothing is a fact about the company, not
  missing data — it is 100 %. Absent assets stays unknown, because every going
  concern has some.
- 2026-10-01 (agent): the live figures are unchanged by the extraction
  (egenkapitalandel 34.2, driftsmargin 3.4, likviditetsgrad 1.6 — all moved from
  earlier in the week because September bookkeeping has progressed, not because
  of this change). 66 tests pass.
