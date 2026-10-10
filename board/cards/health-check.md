---
title: Produce the onboarding health check and the clean-up list for the regnskapsfører
owner: @agent
milestone: #onboarding
created: 2026-10-04
priority: 13
---
## Goal
"The Cash tier sells on the health check, the Monday brief and seasonal warnings." The health check is 2–3 pages: cash and runway, payroll-ratio trend, receivables and concentration, VAT and tax status, and data gaps. The clean-up list is what the regnskapsfører must fix: unposted invoices, missing project codes, unreconciled accounts. `preflight.py` and `commitments.py` already find most of it; nothing turns it into a deliverable. It is an agent job on the shared core.

## Done when
- [x] One action produces the health check for a newly connected company
- [x] Every figure comes from the engine and passes `verify`
- [x] The clean-up list states preflight's findings in words a regnskapsfører can act on, ready to forward
- [x] Both are saved and viewable in the app, and a card asks the CEO to forward the list

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 13 in Next: what the Cash tier sells on to a new customer.
- 2026-10-10 (agent): claimed. Planned with @edmir. What exists: the figures for every section — cash and runway (`cashflow.py`, `commitments.py`, `bankgap.py`), payroll share by month (`overview.py`), receivables and concentration (the forecast's open invoices), VAT and tax (`commitments.py`), data gaps (`preflight.py`, plus `bankgap`'s unreadable reconciliation months and unbooked bank lines). What is missing: turning them into two documents, a page to read them, and the card.
- 2026-10-10 (agent): decided by @edmir: (1) no project codes — the company does not use projects in Tripletex, so the check is left out; (2) the card gives the clean-up list as text to copy and send, nothing is emailed; (3) a page in the app that prints and saves as PDF from the browser; (4) made on a button and once a month. Monthly on the 6th working day at 07:00, after the morning run: on the 1st last month is rarely posted yet (preflight gives invoicing five working days), and the check would always open on an unposted month.
- 2026-10-10 (agent): plan, the brief's pattern. `health.py` gathers one fact sheet per section and the clean-up items with no model; the `helsesjekk` job writes a short text per section for the CEO and the list for the regnskapsfører in their own terms, everything through `verify`; without the model both are written from the figures. Saved in `reports` as `health_check` and `cleanup_list`, a new run a new row. A Helsesjekk page with a make-new button, print-ready. A card with the list as its draft.
- 2026-10-10 (agent): built on branch `health-check`. `health.py`: facts per section with no model (cash: bank, free now and after everything, both low points against the floor, the first week under it, when the committed line goes dry; payroll share per finished month, the month running left out; receivables with overdue buckets 1–30, 31–60, 61–90, over 90 days and the three largest customers' share; VAT and tax per item with due dates; what could not be checked). Clean-up items: preflight's warnings then notes, unbooked bank lines, reconciliation months that could not be read, foreign-currency invoices. The `helsesjekk` job writes the sections and one point per item; an item it leaves out is filled from the engine, one it invents is dropped; the whole text is checked by `verify` again before it is kept. Without the model both are written from the figures. Kept in `reports` (`health_check`, `cleanup_list`). The card ("Send oppryddingslisten til regnskapsfører (n punkter)") has the list as its draft, and a new run closes the card from the run before. Scheduled job `health_check` on the 6th working day; button on a new Helsesjekk page (`#helsesjekk`), which prints without the menu. `main.py` imports it as `health_report`, since `health` is the `/api/health` route. Suite: 335 passed (9 new in `test_health_check.py`).
- 2026-10-10 (agent): page checked in a headless browser, on screen and in print mode (menu and buttons gone). Left in Doing until @edmir makes the first real one with the button.
- 2026-10-10 (agent): made for real by @edmir with the button: written from the figures (no Anthropic credit yet), 12 clean-up items, no figure without a source, card K021 on the deck. @edmir: it works as it should; the layout and how it reads for the user can be improved — a follow-up, not part of this card.
