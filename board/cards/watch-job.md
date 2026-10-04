---
title: Run a morning watch that raises and closes findings and cards unasked
owner: @agent
milestone: #agent
created: 2026-10-04
---
## Goal
The playbook's service is push, not pull: "Act, don't just answer", alerts "only when a threshold is crossed; always with a suggested action", and "quiet when things are fine". Today the derived cards are rebuilt by fixed rules only when someone opens Saker, and nothing compares today with what was flagged before.

`watch` is an agent job on the shared core. Every weekday morning it reads the engine's figures, memory and the rulebook, decides what the CEO needs to see, and prepares the work. The Cash-tier alerts are: cash below the floor, a late or at-risk customer, VAT money being used as operating cash, and an unusual cost. Depends on [[agent-core]], [[scheduler]] and [[rulebook-thresholds]].

## Done when
- [ ] Runs every weekday morning from the scheduler, without anyone asking
- [ ] Raises a card or finding only when a rulebook threshold is crossed, each with a suggested action
- [ ] Closes findings that no longer hold, citing the figure that settles them
- [ ] Never repeats a card that is already on the deck or was dismissed
- [ ] May only write cards and findings; it is given no other tools
- [ ] Every number it writes passes `verify`

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
