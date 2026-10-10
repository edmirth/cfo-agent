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
- [ ] One action produces the health check for a newly connected company
- [ ] Every figure comes from the engine and passes `verify`
- [ ] The clean-up list states preflight's findings in words a regnskapsfører can act on, ready to forward
- [ ] Both are saved and viewable in the app, and a card asks the CEO to forward the list

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 13 in Next: what the Cash tier sells on to a new customer.
- 2026-10-10 (agent): claimed. Planned with @edmir. What exists: the figures for every section — cash and runway (`cashflow.py`, `commitments.py`, `bankgap.py`), payroll share by month (`overview.py`), receivables and concentration (the forecast's open invoices), VAT and tax (`commitments.py`), data gaps (`preflight.py`, plus `bankgap`'s unreadable reconciliation months and unbooked bank lines). What is missing: turning them into two documents, a page to read them, and the card.
- 2026-10-10 (agent): decided by @edmir: (1) no project codes — the company does not use projects in Tripletex, so the check is left out; (2) the card gives the clean-up list as text to copy and send, nothing is emailed; (3) a page in the app that prints and saves as PDF from the browser; (4) made on a button and once a month. Monthly on the 6th working day at 07:00, after the morning run: on the 1st last month is rarely posted yet (preflight gives invoicing five working days), and the check would always open on an unposted month.
- 2026-10-10 (agent): plan, the brief's pattern. `health.py` gathers one fact sheet per section and the clean-up items with no model; the `helsesjekk` job writes a short text per section for the CEO and the list for the regnskapsfører in their own terms, everything through `verify`; without the model both are written from the figures. Saved in `reports` as `health_check` and `cleanup_list`, a new run a new row. A Helsesjekk page with a make-new button, print-ready. A card with the list as its draft.
