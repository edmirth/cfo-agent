---
title: Add deterministic ledger tripwires to the pre-flight checks
owner: @agent
milestone: #warnings
created: 2026-09-29
---
## Goal
Deterministic tripwires, not model judgement. From the original list: withholding held back but not set aside (1950 went from 331 143 to zero while 2600 stayed at zero with payroll booked); accrual accounts that stop moving (2945 has sat at −986 108 since 1 January); duplicate supplier payments; changed supplier bank accounts; round-number invoices.

## Done when
- [ ] Each tripwire is computed in code, with no model in the loop
- [ ] Each states the accounts and the arithmetic behind it
- [ ] They surface through `preflight.py` alongside the existing checks
- [ ] A test per tripwire, including the case where it should stay quiet

## Log
- 2026-09-29 (agent): created, transferred from TODO.md
