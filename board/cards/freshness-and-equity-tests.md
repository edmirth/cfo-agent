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
- [ ] A test proves two concurrent cold callers cause one build, not two
- [ ] A test proves a caller giving up does not cancel the build others are waiting on
- [ ] A test proves a failed build does not leave a permanently poisoned in-flight task
- [ ] The equity ratio is pinned against known assets and debt, including the debt-free case that currently returns None
- [ ] A test covers the thin-margin rounding so 0.043 % never reads as 0.0 again

## Log
- 2026-09-29 (agent): created
