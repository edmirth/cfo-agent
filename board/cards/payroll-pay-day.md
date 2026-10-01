---
title: Pay wages on the day company.md says, not month end
owner: @agent
milestone: #forecast
created: 2026-10-01
---
## Goal

`commitments.py` and `cashflow.py` disagree about when wages leave the account,
and only one of them reads what the company actually told us.

`company.md` says `lonn_utbetalingsdag: 20`. `commitments._next_payroll()` reads
that setting and dates `skyldig_lonn` to 20 October. `cashflow.py` ignores it and
computes its own pay day as month end:

```python
pay_day = workdays.backward(
    date(month.year, month.month, monthrange(month.year, month.month)[1]))
```

Over the current horizon (2026-09-28 → 2026-12-27) that gives:

| run | forecast says | company.md says |
|---|---|---|
| October | 30 Oct (Uke 44) | **20 Oct** (Uke 43) |
| November | 30 Nov (Uke 49) | **20 Nov** (Uke 47) |
| December | — **missing** | **18 Dec** (the 20th is a Sunday) |

Two runs sit roughly ten days late, which makes the weeks between them look
better funded than they are. Worse, the December run — about **758 000 kr** — is
absent from the forecast entirely, because month end (31 Dec) falls outside the
13-week horizon while the 20th falls inside it.

Uke 50 is currently the reported low point at about 1.8 M. An unmodelled
758 000 kr leaving in Uke 51 would move both the week and the figure, so the one
answer the forecast exists to give — which week is tightest, and how much is
left — is wrong today.

## Done when
- [ ] `cashflow.py` takes the pay day from `company.setting("lonn_utbetalingsdag")`, the same source `commitments.py` uses
- [ ] Month end remains the fallback when the setting is absent, and is declared as an assumption rather than silently assumed
- [ ] Three wage runs appear in a 13-week horizon that spans three pay days, not two
- [ ] The December run lands on Fri 18 Dec, the 20th being a Sunday
- [ ] `commitments` and `cashflow` cannot disagree again — one function, imported, not two implementations
- [ ] The low week and its amount are recomputed and reported, since both are expected to change
- [ ] A test covers a pay day on a weekend, and a horizon whose last pay day falls between the 20th and month end

## Note

Found while verifying the backlog on 2026-10-01, not from TODO.md. I noticed the
two modules disagreeing during the weekend-and-holidays card and mentioned it in
passing without carding it; that was the wrong call, since it outranks most of
what is on the board.

Related: "Model December half-tax and the feriepenger month" is the same part of
the model and may be worth doing in the same pass — December's net pay is larger
than an ordinary month, which compounds the missing run above.

## Log
- 2026-10-01 (agent): created
