---
title: Pay the skattetrekk on pay day, and stop treating feriepenger as cash
owner: @agent
milestone: #forecast
created: 2026-10-01
---
## Goal

From 2026 there is no skattetrekkskonto. The withholding is transferred to
Skatteetaten **the same day as the salary**, not held back and settled on a
bimonthly term. `cashflow.py` still models the old regime:

```python
WITHHOLDING_SHARE = 0.30          # "of gross wages, held back and paid on term dates"
net_wages = rates["wages"] * (1 - WITHHOLDING_SHARE)
```

Confirmed in the ledger. Account 2600 on 10 September: withheld −531 765 and
transferred out +452 306 the same day, described "Overføring skattetrekk".
Account 1950, the restricted skattetrekkskonto, was emptied in January 2026 and
has had nothing since — as the rule change requires.

Two errors meet on the pay day, pulling opposite ways:

- The trekk leaves with the salary and is **not** in the forecast.
- `rates["wages"]` is accounts 5000–5099, which includes **5020 Feriepenger** —
  an accrual that does not leave monthly. It is already modelled separately,
  falling due 2027-06-30, so counting it in the monthly run-rate pays it twice.

Measured against what actually left the bank on 10 September 2026 (Lønnsbilag
28 and 29; voucher 26 was reversed the same day and must not be counted):

| | |
|---|---|
| net to employees | 626 775 |
| skattetrekk to Skatteetaten | 226 285 |
| **actual payroll cash** | **853 060** |
| what the forecast models | 757 991 |
| understated per pay day | **95 069** |

Three pay days sit in the current horizon, and the third shares Uke 50 — the
low week — with the VAT settlement.

## Done when
- [x] Pay-day outflow is gross cash wages: the trekk leaves with the salary
- [x] Feriepenger accrual is out of the monthly run-rate, since it is paid in June and already dated there
- [x] The modelled pay day reconciles against the 853 060 kr that actually left on 10 September, within the run-rate's own tolerance
- [x] `WITHHOLDING_SHARE` and the skattetrekkskonto offset in `commitments.py` are gone, not left as dead regime
- [x] `assumptions` says the trekk leaves with the salary, so the owner can see the rule
- [x] The low week and its amount are recomputed and reported

## Note

From @edmir, 2026-10-01: the government changed this for 2026 — no
skattetrekkskonto, the tax is paid directly to Skatteetaten the same day as
salary. Everything above follows from that, and it also retires the headline
example on the ledger-tripwires card.

## Log
- 2026-10-01 (agent): created
- 2026-10-01 (agent): built. `wages_cash` is a second run-rate over 5000-5019
  plus 5030-5099, so the feriepenger accrual on 5020 is out of it, and the pay
  day takes that figure gross. `WITHHOLDING_SHARE` is gone.
- 2026-10-01 (agent): reconciled. The run-rate gives 979 065 — which is just
  5000 YTD divided by nine (975 162) plus sykepenger. The 853 060 that actually
  left on 10 September is 0.87x that, inside the 0.5x-2x band the run-rate
  itself keeps, so the two agree as well as a monthly average can agree with one
  month.
- 2026-10-01 (agent): **the low week falls from 1 739 632 to 1 076 408 kr.**
  Uke 50 now carries the December payroll and the VAT settlement together —
  1 208 406 kr out in one week.
- 2026-10-01 (agent): `commitments` no longer nets a skattetrekkskonto balance
  off the withholding; 1950 reads 0.0 and there is no such account to net. A
  residual on 2600 is now dated today — under the new rule it is a transfer that
  should already have gone, not one waiting for a term.
- 2026-10-01 (agent): the pay-day item was still labelled "Netto lønn" after it
  stopped being the net. It now reads "Lønn og skattetrekk".
