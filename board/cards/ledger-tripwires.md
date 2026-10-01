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

## Correction, 2026-10-01 (edmir)

**Do not build the withholding tripwire as written.** The headline example —
"withholding held back but not set aside (1950 went from 331 143 to zero while
2600 stayed at zero with payroll booked)" — described the pre-2026 regime. From
2026 there is no skattetrekkskonto: the tax is paid directly to Skatteetaten the
same day as the salary. 1950 emptying in January and staying empty is the rule
being followed, not a breach, and a tripwire on it would raise a false alarm
every month.

Verified in the ledger: 2600 on 10 September shows −531 765 withheld and
+452 306 transferred out the same day, "Overføring skattetrekk".

The other examples stand — accrual accounts that stop moving (2945 at −986 108
all year), duplicate supplier payments, changed bank accounts, round-number
invoices. One to add, found while checking this: **Lønnsbilag 26-2026 was posted
and reversed the same day**, so a naive reading of 10 September sees two payrolls.
A duplicate-voucher tripwire has to net reversals before it counts anything.
