---
title: Measure what the playbook says matters
owner: @agent
milestone: #metrics
created: 2026-10-04
priority: 14
---
## Goal
"What to measure (not daily active users): CEO time per week (target under 10 minutes), share of prepared actions approved without edits, problems caught early, e.g. cash dips flagged weeks ahead, whether the CEO forwards the monthly pack." None of it is measured today. Agent cost per company matters for the margins the human-layer section worries about.

## Done when
- [x] Every card decision records how long it took and whether the draft was edited
- [x] The approval-without-edits rate is computed per week
- [x] For each cash dip that happened, the number of weeks it was flagged in advance
- [ ] Email opens and link taps are recorded as a proxy for CEO time
- [x] Agent cost per company per week, from the job runs
- [x] A simple internal page or weekly report shows all of the above

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 14 in Next: needed to know whether it works, and for human-review graduation.
- 2026-10-10 (agent): claimed. Planned with @edmir. What exists: every card change is in `card_events` with a timestamp (and a `draft_edited` column nobody sets), every model run's cost is in `job_runs`, every daily forecast and bank balance since 7 October is kept. What is missing: drafts cannot be edited, so "approved without edits" would always read 100 %; nothing measures time in the app; nothing ties a cash dip to the forecast that first saw it; email opens cannot be had without our own domain (Resend tracks opens per domain) and a public address for its webhooks.
- 2026-10-10 (agent): decided by @edmir. (1) Drafts become editable on the card before approving, and the edit is recorded. (2) CEO time is measured as active minutes in the app — a ping a minute while it is open and in focus, nothing about what is read — and it is for the product owner, not shown to the customer. (3) A page for the owner only: `#maling`, not in the menu; behind an admin role once customers log in. (4) A cash dip is a week the bank's own balance closed under the floor; its warning is the weeks from the first saved forecast that showed that week under the floor. Email opens and link taps wait for a domain and hosting (Backlog).
- 2026-10-10 (agent): plan. `metrics.py` computes, per ISO week: AI cost by job (`job_runs`); decisions, approvals and the share approved without edits, and the median time from card to decision (`card_events`); active minutes (`activity`, migration 004); cash dips with weeks of warning (`bank_balances`, `forecast_weeks`). `/api/metrics`, `/api/activity`. Saker gets an editable draft; the decision carries the text, and an edit sets `draft_edited`.
- 2026-10-10 (agent): built on branch `service-metrics`. `metrics.py` per ISO week: active minutes (`activity`, migration 004; the app pings `/api/activity` once a minute while visible and in focus), decisions with approved, approved unedited and the median hours from the card's `created` event to its decision (`card_events`), agent cost by job with runs that have no price counted apart (`job_runs`), and cash dips — weeks the bank's own balance closed under today's floor — each with the first saved forecast whose committed line showed that week under the floor, and the weeks between (0 when seen only in its own week, none when never). Saker's draft is an editable text box with "Tilbake til CFO-ens tekst"; the decision sends the text, a change replaces the draft and sets `draft_edited` (cards without a draft stay NULL). `#maling` is the owner's page, not in the menu. Suite: 342 passed (8 new in `test_metrics.py`). Checked on the live data in a headless browser: week 41 at $0.19 with 13 unpriced runs (failed for want of credit), no dips since the bank's balance began to be kept on 7 October.
- 2026-10-10 (agent): left open on purpose: "Email opens and link taps are recorded" — @edmir's decision; Resend tracks opens only on our own domain, and its webhooks need the app on a public address. Moved to Backlog. Until then, minutes in the app are the measure of the CEO's time. Note: the floor has no history, so a changed floor re-measures past dips.
