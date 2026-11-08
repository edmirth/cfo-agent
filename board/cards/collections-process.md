---
title: Build a daily collections list that flags repeat late payers
owner: @either
milestone: #liquidity
created: 2026-09-29
---
## Goal
`cards.py` already drafts a reminder per late customer. What is missing is the process around it: who is late, who is *habitually* late, what goes out today, with the chase drafted.

**Note.** Owner is @either: sending anything outward is a product and liability decision, and `cards.py` deliberately has no mail server today.

## Done when
- [x] Habitual lateness is distinguished from a one-off: each late customer
      against his own habit (`payment_habits`). *Uvanlig sen* (usually pays
      inside the reminder rule, or now more than twice his own lateness):
      ring first, high. *Fast sen betaler* (habit past the rule, at least 3
      paid invoices): a reminder, medium, and the forecast already expects it
      late. *Ukjent vane*: as before
- [x] A ladder: a reminder, a second firmer one 14 days later, and after two
      without payment the next step is the owner's (inkassovarsel, a call, an
      instalment agreement), with nothing drafted for it
- [x] A daily view of what should go out: "Innkreving i dag" at the top of
      Saker, one row per late customer, what to do today first; a row opens
      its card; what waits says until when
- [x] The draft survives being sent without editing: a deadline seven days
      on (a working day), the account (`kontonummer` in Selskapet, else "the
      account on the invoice"), the invoice numbers; the second one says when
      the first went and that further steps follow without payment or answer
- [x] The agent's briefing names the habitual late payers and that the step
      after two reminders is the owner's
- [x] Tests with made-up customers

## Log
- 2026-09-29 (agent): created, transferred from TODO.md
- 2026-10-04 (agent): Phase 2 in the AI CFO Strategy Playbook (CFO tier receivables follow-up). Added to Backlog.
- 2026-11-08 — Planned with @edmir: after two reminders the next step is
  his; the list at the top of Saker, not its own tab. Built on
  `collections-process`.
  - `backend/innkreving.py`: `habit`, `sent`/`step` (reminders approved on the
    customer's card in this round of lateness: not released), `draft` for
    steps 1 and 2, `habit_text`, and `today_list`.
  - `backend/cards.py`: `_late` finds each late customer once; `_collections`
    builds the card per step; `refresh` adds `collections` to the deck.
  - `backend/company.py`: setting `kontonummer` (text in the drafts, not a
    calculation; `main.py` leaves it out of "used in calculations").
  - `backend/cashflow.py` briefing: "Faste sene betalere".
  - `frontend-react/src/pages/saker.tsx`: "Innkreving i dag".
  - Seen on the Lindeskar demo: one customer, usually 4 days after due, now
    39 days late, listed first with "Ring dem"; the row opens the card with
    "Jeg ringer dem" as the main button.
  - On the real books (read only, through the Tripletex connector): four
    customers are over the rule, each with invoices that are months to years
    old against many invoices paid since. All four come out as *uvanlig*,
    which fits: an old invoice from a customer who keeps paying is a dispute
    or a booking error, not a slow payer. No customer has a habit past
    14 days. The habit days in the sandbox port came out negative, so the
    port is rough; the labels, not its figures, are the finding.
  - Suite: 594 passed.
