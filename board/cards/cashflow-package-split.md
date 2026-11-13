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
- [ ] `backend/cashflow/` package as in §4.6. `import cashflow` and the public API unchanged
- [ ] `models.py` with `Flow` and `FlowKind`. `texts.py` holds every user sentence
- [ ] Shared helpers replace the duplicates listed in §4.7
- [ ] Tests moved off private functions and module patching (`cashflow.mcp`,
      `cashflow.commitments`) onto `sources` fakes and the public functions
- [ ] `ruff` and `mypy` clean on the package. No function over about 60 lines
- [ ] Snapshots byte-identical

## Log
- 2026-11-13 (claude): created from the spec on @edmir's request
