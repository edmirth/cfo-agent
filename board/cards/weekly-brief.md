---
title: Write the Monday cash brief: traffic light, low point against the floor, what changed, up to three decisions
owner: @agent
milestone: #agent
created: 2026-10-04
---
## Goal
The weekly 13-week cash brief is the playbook's first deliverable: one phone screen, 1–2 minutes of the CEO's time. Today `summary.py` writes a daily text when the first person opens the page. The playbook's example:

```
GREEN - Cash is fine for the next 6 weeks.
Week 7 dips to 1.6 MNOK, below your 2 MNOK floor, unless Customer X pays the 420k invoice due on the 30th.
What changed: Payroll ratio rose to 79% (target 75%) ...
Needs you (2): Approve reminder to Customer X · Decide on overtime policy
```

The brief is an agent job on the shared core, written only from the engine's numbers. Depends on [[agent-core]], [[scheduler]], [[rulebook-thresholds]] and [[watch-job]].

## Done when
- [ ] Written every Monday by the scheduler, from the engine's numbers only
- [ ] Opens with GREEN, YELLOW or RED and one sentence, then the low-point week against the floor from the rulebook
- [ ] Says what changed since last Monday, from the stored figures
- [ ] Lists at most three decisions, each linked to its card
- [ ] Shows how current the books are (preflight), e.g. "12 supplier invoices not yet posted"
- [ ] Shows the forecast accuracy once [[forecast-ledger]] has history
- [ ] Says "nothing needs you this week" when that is true
- [ ] Passes `verify`, and is stored so the web app shows the same text

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
