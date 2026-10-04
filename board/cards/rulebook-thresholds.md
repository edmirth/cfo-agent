---
title: Move the cash floor, reminder days and alert minimum into the company rulebook
owner: @agent
milestone: #rulebook
created: 2026-10-04
---
## Goal
`cards.py` hard-codes `CASH_FLOOR = 500_000`, `LATE_DAYS = 14` and `LATE_AMOUNT = 10_000`. The playbook says these are the company's own rules ("2 MNOK floor", "reminders only after 14 days", "no alerts under 20k", "75% payroll target") and that "rules that change numbers must be structured settings the engine reads, never just a sentence the AI might misread". The watch job and the Monday brief both depend on them.

## Done when
- [ ] The liquidity floor, reminder days, alert minimum and payroll-ratio target are settings in `company.md`, listed in `company.KNOWN` and shown in Selskapet
- [ ] `cards.py`, the cash forecast briefing and the brief read them, and the constants are gone
- [ ] When a setting is missing the current default is used, and the brief says it is assumed
- [ ] Tests cover a set value and a missing one

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
