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
- [x] Runs every weekday morning from the scheduler, without anyone asking
- [x] Raises a card or finding only when a rulebook threshold is crossed, each with a suggested action
- [x] Closes findings that no longer hold, citing the figure that settles them
- [x] Never repeats a card that is already on the deck or was dismissed
- [x] May only write cards and findings; it is given no other tools
- [x] Every number it writes passes `verify`

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 12 in Next: early warnings that are actually early; builds on the brief, scheduler and rulebook.
- 2026-10-09 (agent): claimed after card 11 was parked until hosting. Planned with @edmir. What exists: cash below the floor and late customers are already raised as cards every morning, with no model (the deck is rebuilt by the morning run since card 6, not only when Saker is opened). What is missing: a VAT warning (the figures are in `commitments.py`), an unusual-cost detector, findings maintained unasked, and stable keys for what the agent raises (agent cards are keyed on their title, so a changed amount could repeat one).
- 2026-10-09 (agent): decided with @edmir. (a) Unusual cost = a cost account last month more than 50 % above its average over the months before it this year (up to six), and at least `varsel_minimum_kr` more; the percentage is a new rulebook setting, `kostnadsavvik_pct`. (b) "At-risk customer" beyond late is left to the Backlog card on repeat late payers. (c) The watch may open findings, only for a crossed threshold, at most two a morning.
- 2026-10-09 (agent): plan. The engine decides what crossed a threshold; the model judges and writes. `watch.py` turns the detectors into candidates with fixed keys (`vat:<due>`, `cost:<account>:<month>`). The `vakt` job on the core gets four tools of its own and nothing else: raise a card for a candidate, open a finding for a candidate (two at most), set a candidate aside with a reason, and close a finding citing the settling figure. Every number in what it writes is checked by `verify` before it is stored; a figure without a source is refused back to it. A candidate it has dealt with is not put to it again (`watch_seen`), and a watch card whose condition is gone is closed by the engine as resolved. With no new candidate and no open finding, no model is called. A step in the morning run, after the deck and before the summary.
- 2026-10-09 (agent): built on branch `watch-job`. `watch.py`: `vat_candidate` (commitments' `free_now` below zero by at least `varsel_minimum_kr`: the bank does not cover what falls due to the state and staff within 30 days), `cost_candidates` (last month against the months before it this year, up to six, needing three; `kostnadsavvik_pct` and `varsel_minimum_kr`; per account, from the monthly report the overview already fetches, so no new Tripletex call). Keys `watch:vat:<first due>` and `watch:cost:<account>:<month>`. The `vakt` job has four tools of its own (`watch_card`, `watch_finding`, `watch_skip`, `watch_close_finding`), kept out of the chat; each acts only on the morning's candidates or open findings, refuses any number `verify` cannot trace to grunnlaget, and records what it did in `watch_seen` (migration 003) so nothing is put to it twice. Findings capped at two a morning. Watch cards are `agent` cards keyed `watch:`, and `cards.resolve_gone` closes them once their condition is gone, only when both detectors could look. No new candidate and no review due (open findings are reviewed at least weekly): no model call. Without the model, the candidates are raised as plain cards written from their figures and the run says partial — the Anthropic credit is too low today, and a warning never raised is worse than a plain one. A step in the morning run, after the deck and before the summary. Suite: 326 passed (16 new in `test_watch.py`).
- 2026-10-09 (agent): the detectors on today's real books: one candidate, VAT — the bank holds 3 140 406 kr against 3 253 460 kr due within 30 days, 113 054 kr short. No unusual cost in September: wages rose 49 %, just under the 50 % rule (July's holiday wages pull the average down), phone 112 % but only 4 798 kr. Not yet seen: a run with the model, which needs Anthropic credit; until then the morning raises the VAT warning as a plain card.
