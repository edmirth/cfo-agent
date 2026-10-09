---
title: Run a morning watch that raises and closes findings and cards unasked
owner: @agent
milestone: #agent
created: 2026-10-04
priority: 12
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
- 2026-10-04 (agent): priority 12 in Next: early warnings that are actually early; builds on the brief, scheduler and rulebook.
- 2026-10-09 (agent): claimed after card 11 was parked until hosting. Planned with @edmir. What exists: cash below the floor and late customers are already raised as cards every morning, with no model (the deck is rebuilt by the morning run since card 6, not only when Saker is opened). What is missing: a VAT warning (the figures are in `commitments.py`), an unusual-cost detector, findings maintained unasked, and stable keys for what the agent raises (agent cards are keyed on their title, so a changed amount could repeat one).
- 2026-10-09 (agent): decided with @edmir. (a) Unusual cost = a cost account last month more than 50 % above its average over the months before it this year (up to six), and at least `varsel_minimum_kr` more; the percentage is a new rulebook setting, `kostnadsavvik_pct`. (b) "At-risk customer" beyond late is left to the Backlog card on repeat late payers. (c) The watch may open findings, only for a crossed threshold, at most two a morning.
- 2026-10-09 (agent): plan. The engine decides what crossed a threshold; the model judges and writes. `watch.py` turns the detectors into candidates with fixed keys (`vat:<due>`, `cost:<account>:<month>`). The `vakt` job on the core gets four tools of its own and nothing else: raise a card for a candidate, open a finding for a candidate (two at most), set a candidate aside with a reason, and close a finding citing the settling figure. Every number in what it writes is checked by `verify` before it is stored; a figure without a source is refused back to it. A candidate it has dealt with is not put to it again (`watch_seen`), and a watch card whose condition is gone is closed by the engine as resolved. With no new candidate and no open finding, no model is called. A step in the morning run, after the deck and before the summary.
