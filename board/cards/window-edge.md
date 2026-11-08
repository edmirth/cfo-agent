---
title: See past week 13, so the last weeks do not read as a fall
owner: @edmir
milestone: #forecast
created: 2026-11-08
---
## Goal
Card 17 on the board. Most of what card 17 asked for is done: the invoicing
not yet sent is in the forecast (#58, #60, #61, #94, #97–#101). What is left
is the edge of the window.

The forecast stops after 13 weeks (`WEEKS` in `backend/cashflow.py`), and the
`bucket` in `build` drops every flow that lands after that. Wages, VAT and
withheld tax are paid on fixed dates, so they land inside the window. The
invoicing that pays for those weeks is sent at month end on 30 or 45 days,
so it lands up to six and a half weeks later, often after week 13. The last
weeks of the chart then carry the money going out without the money coming
in that follows it, and the low point can land in the last week only because
the window ends there.

That low point is used everywhere: `low_committed` in `build`, `low_point` in
`brief.py` (front page and Monday email), `_from_cashflow` in `cards.py` (the
"Under gulvet" card in Saker), and the agent's briefing. An edge week can
make all four say the company goes under the floor when it does not. The
light reads only the first six weeks, so it is mostly spared, except for the
yellow "later in the period" reason.

As of 8 November the window ends in week 6 of 2027, 1–7 February. January's
invoicing on 45 days is paid in mid-February, and the edge falls on the
January VAT and the February wages.

## Plan
1. **Calculate further, show 13.** `build` uses `WEEKS + EDGE_WEEKS` (6
   extra weeks) for the horizon, so every source (invoice runs, other
   invoicing, payroll, VAT and tax, the bills) fills 19 weeks with no change
   of its own. The chart, the table and every reading of the 13 weeks only
   get `weeks[:WEEKS]`. The extra weeks are kept as `after`, not shown as
   weeks.
2. **"Etter uke 13".** `after` is summed into one line, money in and out on
   both lines and the main items, for example: "Etter uke 13: 1,9 mill. inn
   i uke 14–16, fra faktureringen i desember og januar." It goes under the
   chart and as the last row in "Vis uke for uke", which opens like the
   others.
3. **An honest low point.** A low week is an *edge* if it is one of the last
   three weeks (`EDGE_LAST = 3`) and the committed line is back above the
   floor within the extra weeks. Then `low_committed` is the lowest week
   before the edge, and `edge` holds the edge week and what lifts it. The
   front page, the Monday email and the agent's briefing say the low point,
   plus one line about the edge. `_from_cashflow` never makes an "Under
   gulvet" card from an edge week alone. If the line does not come back
   within the extra weeks, it is not an edge, and nothing changes.
4. **The light.** The yellow "Saldoen går under gulvet senere i perioden" is
   not given for an edge week alone.
5. **Tests** with made-up books: a company that invoices at month end on 45
   days, seen from mid-October and mid-November; an edge week that is lifted
   (no card, low point before it); one that is not lifted (card as before);
   a week 13 that is low with nothing after it (not an edge).

Not in this card: how sure the weeks after 13 are. They are estimates, used
only to judge the edge and to write the "Etter uke 13" line, never drawn.

## Done when
- [ ] The forecast is calculated six weeks past the window and shows 13
- [ ] "Etter uke 13" under the chart and as the last row in "Vis uke for uke"
- [ ] An edge week is not the low point, and alone it makes no card in Saker
      and no yellow light; the front page, the Monday email and the briefing
      say what lifts it
- [ ] Tests for the rules above
- [ ] @edmir checks the chart on app.arvaka.no after the deploy, and the
      last weeks no longer look like a fall

## Log
- 2026-11-08 — Planned. Files: `backend/cashflow.py` (`build`, `briefing`),
  `backend/brief.py` (`light`, `low_point`), `backend/cards.py`
  (`_from_cashflow`), `frontend-react/src/pages/brief.tsx` (chart, week
  table, low-point line), `frontend-react/src/lib/api.ts`; tests in
  `tests/test_cashflow.py`, `tests/test_brief.py`, `tests/test_cards.py`.
  Size: small to medium. It does not depend on card 64.
