---
title: Model the two payroll quirks that move cash
owner: @agent
milestone: #forecast
created: 2026-09-29
---
## Goal
The forecast assumes twelve identical months. Two Norwegian payroll facts break that: half tax in December means a larger net payment, and in the holiday month staff draw feriepenger instead of salary.

## Done when
- [ ] December's net payroll reflects half tax
- [ ] The holiday month draws feriepenger rather than ordinary salary
- [ ] Both are declared in `assumptions` so the owner can see them
- [ ] A test pins each against a known month

## Log
- 2026-09-29 (agent): created, transferred from TODO.md
