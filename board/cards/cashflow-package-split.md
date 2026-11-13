---
title: Split cashflow.py into a typed package without changing a single number
owner: @either
milestone: #forecast
created: 2026-11-13
---
## Goal
Card 69, phase 2 of `docs/cashflow-spec.md`: a plug-and-play cash-flow forecast
that works for any company that connects, in a smaller, typed and tested module. Read the
spec first; its principle holds for every phase: the AI chooses the data (the data map),
code fetches and calculates every krone.

Based on `main`, never stacked. The snapshot tests from card 67 stay green, and any number
that changes on purpose is updated in its own commit with the reason.

## Done when
- [x] `backend/cashflow/` package as in §4.6. `import cashflow` and the public API unchanged
      (step 1; `build` lives in `pipeline.py` and `briefing` in `narrative.py`, so the module names
      do not shadow the functions `cashflow.build` and `cashflow.briefing`)
- [ ] `models.py` with `Flow` and `FlowKind`. `texts.py` holds every user sentence
- [x] Shared helpers replace the duplicates listed in §4.7 (step 3)
- [ ] Tests moved off private functions and module patching (`cashflow.mcp`,
      `cashflow.commitments`) onto `sources` fakes and the public functions
- [ ] `ruff` and `mypy` clean on the package. No function over about 60 lines
- [ ] Snapshots byte-identical

## Log
- 2026-11-13 (claude): created from the spec on @edmir's request
- 2026-11-13 (claude): step 1 on `cashflow-package-split`, one PR per step,
  each based on main.
  - backend/cashflow.py cut into 13 modules by exact line ranges, every
    comment with the statement below it. 111 definitions compared by AST
    with the old file: identical, but `mcp` and `_payroll_measured`, which
    `build` now reads through `sources` so tests replace them there.
  - `__init__.py` re-exports every old name, plus bankcat, brreg and
    commitments, which tests reach through the package. Two comment blocks
    moved by hand to the constant they explain.
  - 602 passed on both runners, demo snapshots and Ullensaker unchanged.
  - Left for the next steps: break `build` (657 lines) and `briefing` (383)
    into stages; Flow/FlowKind and texts.py; shared helpers; tests onto the
    public functions; ruff and mypy.
- 2026-11-13 (claude): step 2 on `cashflow-package-split`.
  - `build()` (657 lines) is the list of its stages, 75 lines. Each stage
    is a function beside the code it uses: reading, last year, payment
    habits (sources); opening, bank settlement, the 1500/2400 checks
    (reconcile); receivables; invoicing; fixed bills and costs; statutory
    items and booked VAT (tax); payroll; six months of trading, per month
    as sales, VAT and costs (trading); the assumptions and keeping the
    forecast (declare). Stages hand each other Sources, Runs, Pay (models).
  - `briefing()` (383 lines) is 34: sixteen sections, each its own
    function, cut by line range so the text is unchanged.
  - The snapshots caught one slip on the way: `faste_regninger_mnd` was
    dropped in the move, and Ullensaker's briefing said "Til sammen — kr".
    Put back before the commit.
  - 602 passed; the nine demo snapshots and Ullensaker unchanged.
  - Still over 60 lines, for step 3: `_assemble` 158, `_run_rates` 117,
    `_open_invoices` 111, `_invoice_runs` 105, `_fixed_bills` 96.
- 2026-11-13 (claude): step 3 on `cashflow-package-split`.
  - The five long functions split: `_assemble` (weeks, placing, the walk,
    low points, assumptions), `_run_rates` (nested functions lifted out),
    `_open_invoices` (month notes, one row), `_invoice_runs` (why aside,
    placing, what is said), `_fixed_bills` (by supplier, cadence, placing).
    Longest now: `build` 75, `_open_invoices` 66 (a 35-line docstring),
    `_invoice_runs` 61.
  - Helpers for the duplicates: `_iso` (six date parses), `_next_month`
    (two), `_months_until` (two month loops), `_accrued_this_month` (AGA
    and VAT), and `_fixed_bills` reads supplier rows through `_bill_rows`.
    Tests for the three common helpers.
  - 605 passed; demo snapshots and Ullensaker unchanged.
  - Left: Flow/FlowKind and texts.py (step 4); tests onto the public
    functions, ruff and mypy (step 5).

