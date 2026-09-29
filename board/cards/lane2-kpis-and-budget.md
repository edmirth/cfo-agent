---
title: Lane 2 epic: budget-vs-actual, rolling reforecast and FTE-based KPIs
owner: @either
milestone: #kpi
created: 2026-09-29
---
## Goal

Lane 2 is half built. The KPI machinery exists but it is measured against the
wrong yardstick, and the company's own budget — which is sitting in Tripletex,
per account and per month — is barely used.

**What exists today**

- `industry.py` picks five to seven KPIs for the trade and sets `mal` and
  `varsel` for each from *industry norms*, decided once by the model and cached
  in `state/profile.json`. Seven are live for Ullensaker, headed by lønnsandel.
- `overview.py` reads exactly three budget figures, all from column 1 of the
  Resultatrapport: revenue, operating result and wages. Nothing else.
- `_status()` in `industry.py` colours a KPI green/amber/red against the
  industry target, never against the company's own plan.

**What the budget actually looks like** (checked against Tripletex, 2026 COMPANY
result budget — do not take this on trust, it decides the design)

Six accounts are budgeted, per month, for the full year:

| Account | Year total |
|---|---|
| 3000 Salgsinntekt | 18 336 324 |
| 5000 Lønn til ansatte | 14 386 525 |
| 7790 Annen kostnad | 1 318 509 |
| 4300 Innkjøp av varer | 851 590 |
| 6010 Avskriving transportmidler | 164 583 |
| 8156 Renter billån | 38 173 |

Three problems fall out of that, and each one changes what should be built.

**1. Half the year's budget is a copy of the actuals.** Revenue budget for
January through June equals actual revenue *to the krone*. Wage budget for
April and May likewise. From September the figures turn round and planned
(1 345 000 / 1 501 000 / 1 387 000 / 1 453 000). So variance for the first six
months is structurally zero and reporting it would be theatre:

```
month   budget rev     actual rev      variance
jan      1 342 308      1 342 308              0
feb      1 559 617      1 559 617              0
...
jul      1 364 288      1 273 455        -90 833
aug      1 919 553      2 392 285       +472 732
sep      1 345 000        445 706       -899 294
```

**2. The budget's taxonomy is not the ledger's, and comparing account to
account inverts the answer.** Payroll is budgeted as one line (5000) while the
ledger splits it across 5000 plus seven on-cost accounts that have no budget
row at all — feriepenger 934 007, arbeidsgiveravgift 1 255 945, AGA on holiday
pay 131 695, pension 243 125, and others, netting 2 514 692 YTD.

```
account 5000 alone:  8 776 461 vs 10 656 525 budget  =  1 880 064 UNDER
true payroll cost:  11 291 153 vs 10 656 525 budget  =    634 628 OVER
```

A naive per-account variance is wrong by 2.5 M and reports the wrong sign. Any
line-by-line variance needs a mapping from budget lines to ledger account
groups before it reports anything at all.

**3. Month phasing is already handled upstream, and must not be double-counted.**
The Resultatrapport prorates the current month's budget by days elapsed —
September's 1 345 000 arrives as 1 255 333 at day 28, which is exactly why
`omsetning_budsjett` reads 13 905 657 rather than 13 995 324. Anything reading
the budget directly through `search_result_budgets` gets the unprorated figure
and has to do this itself.

## Done when

- [ ] A decision is recorded on what the budget *is* for months where it was overwritten with actuals — suppress the variance, flag it as not-a-budget, or freeze a plan version
- [ ] Budget lines are mapped to ledger account groups, so payroll compares against all payroll
- [ ] Line-by-line budget-vs-actual variance, with the cause named rather than the gap merely reported
- [ ] Unbudgeted accounts are shown as unbudgeted, never as 100 % overspend
- [ ] KPI status can be read against the company's own budget as well as the industry norm, and it is always clear which one is being shown
- [ ] Month phasing is applied once, not twice
- [ ] `overview.py` reads more than three budget figures
- [ ] A test pins the payroll case above: account-only comparison says under, grouped comparison says over

## Parts

This epic covers three cards already on the board:

- Add budget-vs-actual variance per line, with the cause named — `budget-variance`
- Build a rolling reforecast that is scored against actuals — `rolling-reforecast`
- Use FTE from Tripletex instead of headcount in per-employee KPIs — `fte-not-headcount`

## Note

Owner is **@either**, and the blocking part is yours: item 1 is a judgement
about what the company means by its budget, and I should not decide it. The
mapping, the variance and the tests are mine once that is settled.

FTE matters more here than it looks: two KPIs divide by 47 people in a trade
full of part-timers and then judge the result against a full-time benchmark, so
those two tiles are wrong in the same direction every day.

## Log
- 2026-09-29 (agent): created from TODO.md lane 2, with the budget read from Tripletex rather than assumed
