---
title: Move the cash floor, reminder days and alert minimum into the company rulebook
owner: @agent
milestone: #rulebook
created: 2026-10-04
priority: 2
---
## Goal
`cards.py` hard-codes `CASH_FLOOR = 500_000`, `LATE_DAYS = 14` and `LATE_AMOUNT = 10_000`. The playbook says these are the company's own rules ("2 MNOK floor", "reminders only after 14 days", "no alerts under 20k", "75% payroll target") and that "rules that change numbers must be structured settings the engine reads, never just a sentence the AI might misread". The watch job and the Monday brief both depend on them.

## Done when
- [x] The liquidity floor, reminder days, alert minimum and payroll-ratio target are settings in `company.md`, listed in `company.KNOWN` and shown in Selskapet
- [x] `cards.py`, the cash forecast briefing and the brief read them, and the constants are gone
- [x] When a setting is missing the current default is used, and the brief says it is assumed
- [x] Tests cover a set value and a missing one

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 2 in Next: small, and the brief's traffic light and every alert are measured against these rules.
- 2026-10-05 (agent): claimed. Plan: four settings in `company.KNOWN` (`likviditetsgulv_kr`, `purring_etter_dager`, `varsel_minimum_kr`, `lonnsandel_mal_pct`) resolved by one `company.rules()`; cards, the forecast briefing, the summary and the Brief page all read that. Two floors exist today — `cards.py` 500 000 kr and the Brief page's "én månedslønn" — so the missing-setting default becomes one month's wages (what the CEO already sees), with 500 000 kr only when no wage figure is known.
- 2026-10-05 (agent): done. `likviditetsgulv_kr`, `purring_etter_dager`, `varsel_minimum_kr` and `lonnsandel_mal_pct` are in `company.KNOWN`; amounts are read whole («2 000 000», «2 MNOK», «20k») and anything unclear is refused with a note instead of guessed at. `company.rules()` resolves each to value + assumed + basis; `cashflow.rules()` resolves the floor against the forecast's month of wages on every read (never cached with the forecast). Read by: `cards.py` (constants deleted, cards say which rule raised them), `cashflow.briefing` (floor line, first week under it, "antatt" when ours), `company.briefing` (the rulebook for the agent), `summary.py` (floor, low point and payroll target in the facts), the Brief page and the legacy brief (floor and payroll target from new `/api/rules`), and the dashboard's payroll tile (company target beats the industry guess). Selskapet shows each rule, or "ikke satt · bruker 14 dager (standard)". 17 tests in `tests/test_rulebook.py`; suite 212 passed; frontend builds.
- 2026-10-05 (agent): for @edmir — the floor default is now one month's wages (what the Brief already drew), not the 500 000 kr cards used; 500 000 kr remains only when the forecast has no wage figure. Where a month of wages is above 500 000 kr, the cash card now comes earlier than before — at the same point the Brief already warned. Set the real floor in Selskapet to override.
