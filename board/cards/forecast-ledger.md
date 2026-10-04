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
- [ ] Each Monday's 13-week forecast is stored: both lines, the low point, the assumptions and the definitions version
- [ ] Each week, the forecasts made 1, 2 and 4 weeks earlier are compared with the actual bank balance
- [ ] The accuracy is available to the Monday brief, e.g. "the forecast from four weeks ago was within 3 %"
- [ ] Where possible the miss is attributed to a flow kind (customers paid later, a bill not in the ledger)
- [ ] A test pins the scoring against a known history

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 5 in Next: start early: the playbook's trust proof needs 6–8 weeks of saved forecasts before it says anything.
