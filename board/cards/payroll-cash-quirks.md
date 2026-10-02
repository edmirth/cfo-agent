---
title: Model December half-tax and the feriepenger month in the payroll forecast
owner: @agent
milestone: #forecast
created: 2026-09-29
---
## Goal
The forecast assumes twelve identical months. Two Norwegian payroll facts break that: half tax in December means a larger net payment, and in the holiday month staff draw feriepenger instead of salary.

## Done when
- [x] December's net payroll reflects half tax
- [x] The holiday month draws feriepenger rather than ordinary salary
- [x] Both are declared in `assumptions` so the owner can see them
- [x] A test pins each against a known month

## Log
- 2026-09-29 (agent): created, transferred from TODO.md
- 2026-10-02 (agent): the holiday month was the real bug. `cashflow.build` added
  a full salary run every month in the horizon while `commitments` dated the
  whole 2940 feriepenger balance to the same month, so the holiday month paid
  the staff twice. Payroll scheduling moved out of `build` into
  `_payroll_runs(today, horizon, payroll_cash)` — pure, and therefore testable —
  which withholds the holiday month's ordinary salary. Share = holiday weeks ×
  6 / 26 virkedager, capped at 1: five weeks is thirty virkedager against a
  month of twenty-six, so the whole run is withheld and feriepenger is the only
  payment; four weeks leaves 2/26 of the salary going out. A fully withheld
  month appends no flow at all rather than a 0 kr line.
- 2026-10-02 (agent): December's half tax turns out to have **no cash effect**
  under the regime the pay-day card settled on 1 October. Half tax raises the
  employee's net and lowers the trekk by the same krone, and since 2026 both
  leave on pay day, so the gross out of the account is an ordinary month's; the
  unwithheld half is never caught up later. Modelling December as a heavier
  month would have reinstated the pre-2026 regime in disguise. So it is carried
  as a declaration, not a number: `halv_skatt_i_desember` in `assumptions`, and
  a paragraph in `briefing()` that tells the agent to say so when the owner
  expects a heavier December for that reason. A net/trekk split of the pay-day
  flow was considered and dropped — it needs an effective trekk rate, account
  2600–2619 nets to roughly nothing per month under same-day settlement, and
  inventing ~30 % is the black box this module refuses to be.
- 2026-10-02 (agent): the payout month is now one implementation, in
  `commitments.ferie_month()`, read by both the group due date and the
  withholding — the pay day has already drifted between two of them once.
  Incidental fix on the way: `_next_june` rolled the payout to next year for
  the whole of the current June, so a balance still owed on 5 June was dated
  twelve months out. Two new company.md settings, `ferie_utbetalingsmnd` and
  `ferie_uker`, both optional, both declared as assumed when absent;
  `known_settings` surfaces them in the app without any frontend change.
- 2026-10-02 (agent): nine checks in `tests/test_payroll_quirks.py`, pinned to
  known months — June 2026 withheld at five weeks and part-paid at four,
  December 2026 taking the same gross as November, July withheld when the
  company says July. 89 tests pass; `tsc --noEmit` clean.
