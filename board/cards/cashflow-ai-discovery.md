---
title: Let the AI write the data map on connect, checked against the books before it counts
owner: @either
milestone: #forecast
created: 2026-11-13
---
## Goal
Card 71, phase 4 of `docs/cashflow-spec.md`: a plug-and-play cash-flow forecast
that works for any company that connects, in a smaller, typed and tested module. Read the
spec first; its principle holds for every phase: the AI chooses the data (the data map),
code fetches and calculates every krone.

Based on `main`, never stacked. The snapshot tests from card 67 stay green, and any number
that changes on purpose is updated in its own commit with the reason.

## Done when
- [ ] `backend/discovery/` produces the data map: prompt, schema validation, verification checks
      and drift triggers
- [ ] On the demo company, the AI's map matches the hand-written one from phase 3, or each
      difference is explained
- [ ] `bankcat` classification through discovery. `unknown_share_out` compared before and after on
      the demo company
- [ ] Account roles, fixed suppliers, contract customers and one-off months fed into the profile
      as *verified* or as questions
- [ ] The build never calls a model (enforced by a test)

## Log
- 2026-11-13 (claude): created from the spec on @edmir's request
