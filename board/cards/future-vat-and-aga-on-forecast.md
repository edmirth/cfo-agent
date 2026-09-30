---
title: Split booked VAT by term so each lands on its own due date
owner: @agent
milestone: #forecast
created: 2026-09-29
---
## Goal
The expected line credits `rates["revenue"] * 1.25` — VAT-inclusive cash — for invoicing that has not happened yet, 4 072 570 kr across the horizon, but never schedules the VAT back out. The only VAT leaving in the 13 weeks is the 905 542 already standing on 2700/2710 today.

The timing is the point. October's invoicing is collected 22 Dec (31 Oct + 45 credit days + 7 pay lag), while VAT on October's sales falls due 10 Dec, same termin as September. Money leaves before it arrives and the model has neither side, so the expected line overstates comfort in exactly the weeks that are already tightest. AGA accruing on future payroll has the same shape.

**Note.** Came out of the question about the 13-week forecast and the 45-day terms. The 45 days themselves are already handled correctly — credit_days is the measured median of 71 open invoices.

## Done when
- [ ] Future invoicing books its output VAT out on the termin due date
- [ ] AGA on future payroll is scheduled on its own term dates
- [ ] Both appear in `assumptions`, so the owner can see what is modelled
- [ ] The committed and expected lines stay internally consistent: no gross receipt without its liability
- [ ] A test pins the Oct-sales/10-Dec-VAT case

## Log
- 2026-09-29 (agent): created

## Correction, 2026-09-30 (edmir)

The original goal was wrong and would have built the wrong thing. VAT is not to
be estimated from projected sales — it comes from bilagsføring, and the figure
in the accounts already updates itself as vouchers are posted. The job is to
read the *right account onto the right term*, and the forecast then follows the
bookkeeping on its own.

What that exposed, checked against the ledger:

`2700` clears to zero at the end of February, April and June — each completed
term transferred to `2740` and paid. It did **not** clear at the end of August.
The Jul-Aug term is still sitting inside 2700/2710, mixed with September:

| | |
|---|---|
| Jul-Aug term, due 10 Oct (Sat) -> Mon 12 Oct | **797 572 kr** |
| September so far, part of Sep-Oct, due 10 Dec | 214 340 kr |
| total now in 2700/2710 | 1 011 911 kr |

`commitments.py` reads the closing balance of 2700-2739 as one number and dates
all of it to 10 December. So 797 572 kr is forecast to leave nearly two months
late, and week 41 is missing the outflow entirely.

The 10 December figure is not finished and should not be presented as if it
were: October is not booked yet. It will grow as bilagsføring proceeds.

## Done when (revised)
- [x] A completed term still sitting in 2700/2710 is dated to its own due date
- [x] The running term keeps the next due date
- [x] 797 572 kr appears on 12 Oct and 214 340 kr on 10 Dec, not 1 011 911 kr on 10 Dec
- [x] If the term was transferred to 2740 normally, nothing double-counts
- [x] The running term is marked as still accumulating, so nobody reads it as final
- [x] Tests cover the split, the transferred case, and a term with nothing left behind

## Log
- 2026-09-30 (agent): built. `_completed_term()` gives the last VAT term that has
  ended and when it settles; `_at_month()` reads the balance as at that term's
  end off the monthly saldobalanse, which is reliable because a term that was
  transferred shows zero in its own month column. `_split_vat()` then dates the
  completed part to its own deadline and leaves the rest on the next one, marked
  `accruing`. `cashflow` carries the new id, which it would otherwise have
  filtered out.
- 2026-09-30 (agent): verified live. 797 572 kr now falls in Uke 42 (Mon 12 Oct,
  shifted off the Saturday), 214 340 kr in Uke 50 (Thu 10 Dec). Week 42 had no
  VAT outflow at all before. Totals unchanged, so nothing is double-counted.
- 2026-09-30 (agent): AGA was checked and left alone — 2770 holds only
  September's, correctly dated to 15 Nov, so it has no equivalent problem.
