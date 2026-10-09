---
title: Send the Monday brief by email
owner: @either
milestone: #delivery
created: 2026-10-04
priority: 9
---
## Goal
"Email is the backbone, the app handles one-tap decisions" and "the product works even if the CEO never installs the app." Today nothing leaves the web app.

**Note.** Owner is @either: the provider (Postmark, Resend, SendGrid) and the sending domain are your call.

## Done when
- [ ] The brief arrives in the CEO's inbox every Monday morning without anyone asking
- [ ] It reads on a phone in one screen, in Norwegian, with a link to the full view
- [ ] A failed send is recorded and retried, never silent
- [ ] Recipients are set per company in the rulebook
- [ ] The provider has a data processing agreement, with EU/EEA handling noted

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 9 in Next: "email is the backbone": the brief has to reach the CEO without the app.
- 2026-10-08 (agent): claimed. @edmir chose: Resend, free plan, no domain yet — sent from `onboarding@resend.dev`, which Resend only delivers to the account's own email; fine while the CEO is the only recipient. The email is complete on its own with no links, since the app is not reachable from a phone yet. Plan: `mailer.py` is the only module that knows the provider (Resend's HTTP API, no new dependency). The weekly job gets a send step after the brief: it sends the stored brief, never a fresh one, keyed to the week so a retry never sends twice, and marks the report `sent`. Recipients are a rulebook setting (`brev_mottakere`), defaulting to `CFO_OWNER_EMAIL`. Phone-first HTML with a plain-text part. A send-now button for testing.
