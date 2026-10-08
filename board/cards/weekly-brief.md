---
title: Write the Monday cash brief: traffic light, low point against the floor, what changed, up to three decisions
owner: @agent
milestone: #agent
created: 2026-10-04
priority: 7
---
## Goal
The weekly 13-week cash brief is the playbook's first deliverable: one phone screen, 1–2 minutes of the CEO's time. Today `summary.py` writes a daily text when the first person opens the page. The playbook's example:

```
GREEN - Cash is fine for the next 6 weeks.
Week 7 dips to 1.6 MNOK, below your 2 MNOK floor, unless Customer X pays the 420k invoice due on the 30th.
What changed: Payroll ratio rose to 79% (target 75%) ...
Needs you (2): Approve reminder to Customer X · Decide on overtime policy
```

The brief is an agent job on the shared core, written only from the engine's numbers. Depends on [[agent-core]], [[scheduler]] and [[rulebook-thresholds]]. Until [[watch-job]] exists, the decisions come from the cards `cards.py` already derives.

## Done when
- [x] Written every Monday by the scheduler, from the engine's numbers only
- [x] Opens with GREEN, YELLOW or RED and one sentence, then the low-point week against the floor from the rulebook
- [x] Says what changed since last Monday, from the stored figures
- [x] Lists at most three decisions, each linked to its card
- [x] Shows how current the books are (preflight), e.g. "12 supplier invoices not yet posted"
- [x] Shows the forecast accuracy once [[forecast-ledger]] has history
- [x] Says "nothing needs you this week" when that is true
- [x] Passes `verify`, and is stored so the web app shows the same text

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 7 in Next: the playbook's first deliverable.
- 2026-10-08 (agent): claimed. Plan: `brief.py` builds the brief's figures with no model: the light (GREEN/YELLOW/RED) from the forecast against the rulebook floor, the low point, what changed since the stored figures a week back, the top three open cards, the books' condition (preflight) and the forecast record (`scoring`). The model writes only the one sentence after the light and phrases the changes, through the core, so `verify` reads it; if it cannot, the brief is still written from the figures and the run says partial. Stored in `reports` as `weekly_brief`, one period per ISO week, rewrites as new rows. A second scheduled job, `weekly_brief`, runs at 07:00 on the first working day of each week, after the morning run (Easter Monday moves it to Tuesday). `/api/brief` serves the latest; the front page shows it on top, each decision linking to its card under Saker.
- 2026-10-08 (agent): built on branch `weekly-brief`. `brief.py` computes the light, the low point, the changes, the decisions, the books and the record with no model; the model writes the sentence after the light and phrases the changes through the core (job `mandagsbrev`, named apart from the scheduler's `weekly_brief` so its runs are not counted as the slot's attempts). The light: RED when the expected line goes under the floor within 6 weeks or the committed line below zero within 4; YELLOW when the committed line goes under the floor within 6, or the expected line later; GREEN otherwise, never on a partial forecast or broken tie-outs. Without the model the brief is still written from the figures, and the run says partial. The whole text, the engine's lines included, is checked by `verify` against the figures it was written from; the first check caught the shortfall under the floor being said without being in them. Kept in `reports` (`weekly_brief`, `2026-W41`), served at `/api/brief`, shown on top of the front page, each decision linking to `#saker/<id>`, which scrolls to and rings the card. Scheduled at 07:00 on the first working day of the week (Tuesday after Easter and Whit Monday), straight after the morning. Suite: 285 passed (265 before, 20 new).
- 2026-10-08 (agent): run once against the live books into a scratch database: YELLOW, low point week 50 at 932 040 kr, 211 773 kr under the assumed floor (one month's wages), three cards, books provisional, no forecast record yet. Nothing in it without a source. The model's sentence was not seen live: the Anthropic credit balance is too low, so this run was the fallback. That also caught card titles saying their amount twice, now fixed.
- 2026-10-08 (agent): for @edmir: the floor is still assumed (one month's wages, 1 143 813 kr); set your own in Selskapet and the light follows it. Top up Anthropic credit to get the CFO's own sentence.
