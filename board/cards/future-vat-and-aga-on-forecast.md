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
- [x] Future invoicing books its output VAT out on the termin due date
- [x] AGA on future payroll is scheduled on its own term dates
- [x] Both appear in `assumptions`, so the owner can see what is modelled
- [x] The committed and expected lines stay internally consistent: no gross receipt without its liability
- [x] A test pins the Oct-sales/10-Dec-VAT case

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

- 2026-10-02 (agent): this card was moved to Done on 30 September with all five
  boxes unticked, and the behaviour it describes was still live today. What
  shipped then was the board line — booked VAT split across its own term dates —
  not the card. Found during a full inspection of cashflow.py after the owner
  queried the brief; measured 390 003 kr of VAT inside a 1 950 013 kr inflow
  landing in week 50, which was the low point.
- 2026-10-02 (agent): `commitments.term_due(year, month, terms)` answers the
  question `_next_due` cannot — not "what is the next deadline" but "when does
  the term containing this month fall due" — including the November/December
  roll into the new year. Output VAT on each future invoicing month is now
  dated to its own termin, whether or not the receipt itself lands inside the
  window; that is the case that hurts, liability in and cash out.
- 2026-10-02 (agent): the input-VAT deduction is read off the ledger, not
  assumed — 2700 against 2710, which is the one pair that needs no differencing
  because a settlement clears both on the same day. Measured 12,2 % live.
  Capped at 50 %, and when 2700 is too small to read a ratio off the whole
  output VAT is scheduled out and a warning says so: too strict, not too kind.
- 2026-10-02 (agent): AGA rides along with each payroll run onto the term
  covering the month the wages are paid, scaled with the wage so a withheld
  holiday month owes none. No double count with the 2770 balance: that covers
  a-meldinger already filed, a run still ahead of us has not been reported.
  Live effect — 139 549 kr on 16 November, 342 517 kr of VAT on 10 December.
