---
title: Say what comes in after week 13, so the last weeks do not read as a fall
owner: @edmir
milestone: #forecast
created: 2026-11-08
---
## Goal
Card 17 on the board. Most of what card 17 asked for is done: the invoicing
not yet sent is in the forecast (#58, #60, #61, #94, #97–#101). What is left
is the edge of the window.

The forecast stops after 13 weeks (`WEEKS` in `backend/cashflow.py`). Wages,
VAT and withheld tax are paid on fixed dates, so they land inside the window.
The invoicing that pays for those weeks is sent at month end on 30 or 45
days, so it is often paid after week 13. The last weeks then carry the money
going out without the money coming in that follows, and the low point can
land in the last week. Nothing on the page said so.

**Not calculated past the window.** A week later the window has moved and
the money is in it, so the forecast is not extended. The balance in the last
weeks is a true balance for those weeks. What was missing was saying what
comes in right after, and the forecast already knew: it dropped the
invoices it had dated after week 13.

## Done when
- [x] Money in after week 13 from invoices sent, or sent, inside the window
      is kept as `after` in the forecast: the committed and the expected
      part, the weeks it lands in, and each invoice. Only money in, never on
      a balance, since what goes out after week 13 is not calculated
- [x] "Etter uke 13" under the chart and as the last row in "Vis uke for
      uke", which opens like the weeks
- [x] A low point in the last three weeks says what comes after it: on the
      front page, in the Monday email, in the "Under gulvet" card in Saker,
      and in the agent's briefing. It stays the low point and the card is
      still made, since that week is under the floor
- [x] Tests
- [ ] @edmir checks the chart on app.arvaka.no after the deploy

## Log
- 2026-11-08 — Planned with six weeks calculated past the window and an
  edge week taken out of the low point. @edmir: the window moves a week at a
  time, so drop the extra weeks. Built without them.
- 2026-11-08 — Built.
  - `backend/cashflow.py`: `_invoice_runs` and `_other_invoicing` keep a run
    sent before the window ends and paid after it (they used to drop it);
    `_assemble` collects what lands after the window into `after`
    (`AFTER_KINDS`: sent invoices and the invoicing still to be sent, not the
    slow and doubtful spreads); `after_text` says it in one sentence;
    `at_edge` tells whether a week is one of the last `EDGE_WEEKS`; the
    briefing adds the sentence after the week table.
  - `backend/brief.py` `low_point` and `backend/cards.py` `_from_cashflow`:
    the sentence after the low point when it is in the last three weeks.
    The light is unchanged.
  - `frontend-react/src/pages/brief.tsx`: the sentence under the chart, the
    "Etter uke 13" row (balances left empty, it is no balance), and the line
    under the low point.
  - Tests: a run sent inside the window and paid after it is kept, one sent
    after it is not, the sum and its sentence, nothing after gives no line,
    the low point and the card at the edge and before it. The test of the
    contract sent before today now reads only the weeks inside the window.
    Suite: 577 passed.
  - Seen on the Lindeskar demo in a headless browser: low point in week 4,
    the last week; "Etter uke 13 kommer 2 447 177 kr inn i uke 5–10".
