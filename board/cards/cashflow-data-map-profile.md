---
title: Run the forecast on a per-company profile and data map instead of fixed constants
owner: @either
milestone: #forecast
created: 2026-11-13
---
## Goal
Card 70, phase 3 of `docs/cashflow-spec.md`: a plug-and-play cash-flow forecast
that works for any company that connects, in a smaller, typed and tested module. Read the
spec first; its principle holds for every phase: the AI chooses the data (the data map),
code fetches and calculates every krone.

Based on `main`, never stacked. The snapshot tests from card 67 stay green, and any number
that changes on purpose is updated in its own commit with the reason.

## Done when
- [ ] `Resolved` and `profile.py`. Every former constant resolves through it
- [ ] Data map schema defined. `sources.py` fetches by the map, and a missing map gives the NS 4102
      defaults with snapshots unchanged
- [ ] A hand-written data map for the demo company drives the forecast end to end, before any AI
      is involved
- [ ] Measured: effective output VAT rate, uncapped input share, VAT term, pay frequency and day,
      thresholds relative to scale, payment-lag parameters
- [ ] Assumptions block and briefing report each value's source
- [ ] Snapshots differ only where a measured value replaces a default, and each difference is
      explained

## Log
- 2026-11-13 (claude): created from the spec on @edmir's request
