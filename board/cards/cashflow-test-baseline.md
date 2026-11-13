---
title: Give the cash forecast a test baseline: pytest in the venv, and snapshot tests of the full forecast
owner: @either
milestone: #forecast
created: 2026-11-13
---
## Goal
Card 67, phase 0 of `docs/cashflow-spec.md`: a plug-and-play cash-flow forecast
that works for any company that connects, in a smaller, typed and tested module. Read the
spec first; its principle holds for every phase: the AI chooses the data (the data map),
code fetches and calculates every krone.

Based on `main`, never stacked. The snapshot tests from card 67 stay green, and any number
that changes on purpose is updated in its own commit with the reason.

## Done when
- [x] pytest installed in `.venv` and in `requirements` (dev). The four cashflow test files run
      green (`tests/test_cashflow*.py`, `tests/test_payday_cash.py`)
- [x] Snapshot tests: the full `build()` output (weeks, flows, assumptions, warnings) and
      `briefing()` text for the demo company and at least two fixture ledgers, saved and compared
      exactly
- [x] How to run the tests is documented in `README.md`

## Log
- 2026-11-13 (claude): created from the spec on @edmir's request
- 2026-11-13 (claude): done on `cashflow-test-baseline`.
  - Baseline before any change: `python -m tests.run`, 594 passed, 0 failed.
  - The repo already had its own runner, `tests/run.py`, on purpose without
    pytest. Kept as it is; pytest added beside it on @edmir's request:
    `requirements-dev.txt` (pytest 9.1.1, pinned with its four dependencies;
    Render and the Dockerfile still install `requirements.txt` only),
    `pytest.ini`, and `tests/conftest.py`. The environment both need before a
    backend import moved from `run.py` into `tests/_setup.py`, shared.
    Both runners: 596 passed.
  - `tests/test_cashflow_snapshots.py`: `build()` and `briefing()` for all
    three demo companies (lindeskar, kvarnheim, aslefjord) on 2026-01-14,
    2026-11-12 and 2026-11-26, in a process each with the calendar frozen
    and the network refused. Nine snapshots in `tests/snapshots/cashflow/`,
    compared exactly, with the moved paths named on failure. Same result on
    two runs and under two hash seeds (its own test). About 7 s.
  - Checked that it bites: PAY_LAG_DAYS 7 -> 8 failed with
    `assumptions.pay_lag_days` and the briefing sentence named; reverted.
  - For card 68: on 2026-11-26 the November pay day has passed, so the
    snapshots may not show the AGA double count. Card 68 should reproduce it
    with a test of its own before fixing.
