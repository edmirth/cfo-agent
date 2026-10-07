---
title: Save every weekly forecast and score it against the real balance
owner: @agent
milestone: #forecast
created: 2026-10-04
priority: 5
---
## Goal
The playbook's trust mechanism for the first deliverable is "after 6–8 weeks the CEO can see the forecast held up", and its graduation criterion is "4-week-ahead cash forecast within about ±10% for 8 weeks in a row". Today no forecast is saved, so nobody can tell whether the forecast is right, or whether the precision work on it has made it better. Depends on [[state-database]].

## Done when
- [x] Each Monday's 13-week forecast is stored: both lines, the low point, the assumptions and the definitions version
- [x] Each week, the forecasts made 1, 2 and 4 weeks earlier are compared with the actual bank balance
- [x] The accuracy is available to the Monday brief, e.g. "the forecast from four weeks ago was within 3 %"
- [x] Where possible the miss is attributed to a flow kind (customers paid later, a bill not in the ledger)
- [x] A test pins the scoring against a known history

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 5 in Next: start early: the playbook's trust proof needs 6–8 weeks of saved forecasts before it says anything.
- 2026-10-08 (agent): built on [[state-database]]. Decisions (owner): score
  the **expected** line (committed kept beside it), against the **bank feed
  only** (a week without a bank figure stays unscored), and explain misses at
  **invoice level**. The weekly forecast is the first saved in each ISO week.
  `backend/scoring.py` scores 1, 2 and 4 weeks on, against the bank's balance
  on the last feed day Friday–Sunday of the target week, summed over the bank
  accounts, once each, from `cashflow.build`. Each saved forecast now keeps its
  open invoices and bills with when it expected them (`forecast_runs.items`,
  from the same `_receipt_parts`/`_payment_parts` the schedule uses); the
  forecast saved the week after shows what was still open, so a miss is split
  into customers paying later/earlier, our bills paid later/earlier, and what
  was not in the forecast. `track_record()` gives the latest score per
  horizon, the mean error over 8 weeks and the 4-week streak within ±10 %;
  it is in the system prompt (and says plainly when there is no record yet)
  and at `GET /api/forecast-accuracy`. Migration 002 adds `forecast_scores`
  and `forecast_runs.items`.
- 2026-10-08 (agent): 252 tests pass; a made-up four weeks pins the errors
  (+4.17 %, +1.01 %, 0 %, −3.58 %, +0.77 %), the explanation (Skanska 50 000
  late, Tingstad 20 000 paid late, 10 000 not in the forecast), the streak,
  and the unscored week. Live: today's forecast kept 135 invoices and 3 bills,
  summing to the forecast's 2 250 403 kr open receivables. First score is due
  Monday 12 Oct if the app is opened then; 8 weeks of 4-week scores by early
  January. Days without the app open are gaps until [[scheduler]].

