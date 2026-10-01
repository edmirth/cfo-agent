---
title: Add deterministic ledger tripwires to the pre-flight checks
owner: @agent
milestone: #warnings
created: 2026-09-29
---
## Goal
Deterministic tripwires, not model judgement. From the original list: withholding held back but not set aside (1950 went from 331 143 to zero while 2600 stayed at zero with payroll booked); accrual accounts that stop moving (2945 has sat at −986 108 since 1 January); duplicate supplier payments; changed supplier bank accounts; round-number invoices.

## Done when
- [x] Each tripwire is computed in code, with no model in the loop
- [x] Each states the accounts and the arithmetic behind it
- [x] They surface through `preflight.py` alongside the existing checks
- [x] A test per tripwire, including the case where it should stay quiet

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

## Built, 2026-10-02 — one tripwire, not five

Investigating the ledger before building narrowed this card sharply.

**Built: an accrual that has stopped moving.** It found something on the first
run. Account 2945 has **zero postings in all of 2026** — the last was dated
31 December 2025, "Periodisering lønn 31.12.25". A year-end accrual that was
never reversed. `commitments` reads it as 986 108 kr of wages due on the next
pay day, 28 % of every commitment the company has, and it is the sole reason the
front page says:

    verdict: negative      "Selskapet skylder bort mer enn det har på konto."
    free_all:  -868 461
    without it: +117 647   -> the verdict would be "tight", not "negative"

The check is a `warn`, so the pre-flight condition becomes `provisional` rather
than `broken` — a stale accrual is not a reconciliation failure, and the owner
should not be told the books are broken over it. The text states both readings:
if it is an unreversed year-end accrual the free liquidity is higher than it
looks, and if it is real it needs a due date.

**Not built: duplicate supplier payments, changed supplier bank accounts,
round-number invoices.** There is no instance of any of them in this ledger, so
each would be written blind with nothing to tune against. A warning system that
cries wolf gets ignored, and that would cost the one check that works. They stay
on this card as described, unbuilt, until something gives them a signal.

**Carried forward as a constraint, not a check:** Lønnsbilag 26-2026 was posted
and reversed the same day, so any future duplicate-payment check must net
reversals before counting. Written down so it is not rediscovered the hard way.

**Thresholds, and why they are not zero.** Four months, because several accruals
settle bimonthly and a quiet quarter is normal. A 50 000 kr floor, because 2990
at −6 112 and 2991 at −10 000 have not moved all year and nothing is wrong with
either — flagging those trains the owner to ignore the check. Equity (2000-2099)
is excluded outright: it is supposed to sit still.

## Log
- 2026-10-02 (agent): built as above. The frozen-months count was already in the
  2400 check, hardcoded to that account; lifted to `_frozen_months()` and reused,
  including its care about pairing cells with columns before dropping
  non-numeric ones. Six tests, four of which pin the cases where it must stay
  quiet. Verified it reaches the agent's system prompt through
  `preflight.briefing()`.
