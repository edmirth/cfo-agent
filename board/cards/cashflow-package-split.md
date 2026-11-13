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
- [ ] Shared helpers replace the duplicates listed in §4.7
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

