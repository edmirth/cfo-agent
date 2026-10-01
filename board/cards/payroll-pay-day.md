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
- [x] `cashflow.py` takes the pay day from `company.setting("lonn_utbetalingsdag")`, the same source `commitments.py` uses
- [x] Month end remains the fallback when the setting is absent, and is declared as an assumption rather than silently assumed
- [x] Three wage runs appear in a 13-week horizon that spans three pay days, not two
- [x] The December run lands on Fri 18 Dec, the 20th being a Sunday
- [x] `commitments` and `cashflow` cannot disagree again — one function, imported, not two implementations
- [x] The low week and its amount are recomputed and reported, since both are expected to change
- [x] A test covers a pay day on a weekend, and a horizon whose last pay day falls between the 20th and month end

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
- 2026-10-01 (agent): built. `commitments.payday(year, month)` is now the single
  implementation, public, and `cashflow` imports it instead of computing month
  end. `_next_payroll` is a thin wrapper over it. The forecast declares which
  source the date came from, since month end is our guess and the 20th is theirs.
- 2026-10-01 (agent): verified live. Three wage runs where there were two:

  | | before | after |
  |---|---|---|
  | October | Uke 44 (30 Oct) | **Uke 43 (20 Oct)** |
  | November | Uke 49 (30 Nov) | **Uke 47 (20 Nov)** |
  | December | missing | **Uke 51 (18 Dec)** |

  **The low point moved: Uke 50 -> Uke 51, now 1 739 632 kr.** The shift is
  smaller than the 758 000 kr that was missing, because moving every run ten
  days earlier also drains the earlier weeks — the whole curve moved, not just
  December. `commitments` now agrees: skyldig_lonn due 2026-10-20.
- 2026-10-01 (agent): six tests, including one asserting both modules reference
  the same function object, so this cannot regress by reimplementation.
- 2026-10-01 (edmir/agent): **the setting itself was wrong.** The pay day is the
  10th, not the 20th. `state/company.md` said 20; the edit to 10 had gone into
  the repo seed `company.md`, which is only copied to `state/` on first run, and
  was commented out there besides. Corrected through /api/company so it
  versioned. The code needed no change — it read the setting correctly — but the
  run dates logged above were gathered on the wrong value. With the 10th the
  runs fall in Uke 41 (Fri 9 Oct, the 10th being a Saturday), Uke 46 and Uke 50,
  and the low week returns to Uke 50 at the same 1 739 632 kr.
  Newly visible: December payroll and the VAT settlement both land on 10
  December — 987 332 kr out in one week, the largest concentration in the
  quarter, invisible while the pay day was wrong.
