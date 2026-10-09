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
- [x] The brief arrives in the CEO's inbox every Monday morning without anyone asking
- [x] It reads on a phone in one screen, in Norwegian, with a link to the full view
- [x] A failed send is recorded and retried, never silent
- [x] Recipients are set per company in the rulebook
- [x] The provider has a data processing agreement, with EU/EEA handling noted

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 9 in Next: "email is the backbone": the brief has to reach the CEO without the app.
- 2026-10-08 (agent): claimed. @edmir chose: Resend, free plan, no domain yet — sent from `onboarding@resend.dev`, which Resend only delivers to the account's own email; fine while the CEO is the only recipient. The email is complete on its own with no links, since the app is not reachable from a phone yet. Plan: `mailer.py` is the only module that knows the provider (Resend's HTTP API, no new dependency). The weekly job gets a send step after the brief: it sends the stored brief, never a fresh one, keyed to the week so a retry never sends twice, and marks the report `sent`. Recipients are a rulebook setting (`brev_mottakere`), defaulting to `CFO_OWNER_EMAIL`. Phone-first HTML with a plain-text part. A send-now button for testing.
- 2026-10-08 (agent): built on branch `email-delivery`. `mailer.py` (Resend's HTTP API through httpx2, an `Idempotency-Key` on every send, Resend's refusals said in Norwegian — the test sender's own-address-only rule named as such). `brief_email.py`: the stored brief as a 560 px, inline-styled email with a plain-text part, complete on its own; sent to `brev_mottakere` from the rulebook (new `emails` setting type; a typo is said under Selskapet and not sent to; default `CFO_OWNER_EMAIL`); the report is marked `sent` with when, to whom and Resend's id. Sending is its own scheduled job, `weekly_mail`, straight after `weekly_brief`: a failed send is retried every half hour, three times, without writing the brief again; a scheduled retry carries the same key, so it is never delivered twice; a brief already sent is skipped unless someone sends it by hand. The brief card shows "Sendt på e-post til … " and a send-now button. Suite: 310 passed (25 new in `test_brief_email.py`, `test_brief.py` adjusted for the third job).
- 2026-10-08 (agent): sent for real: Resend account made with the CEO's email, key in `.env`. Week 41's brief (GUL) arrived in Gmail's inbox, not spam, and reads as intended; the report is `sent`. The first attempt, before the week's brief existed, failed with "ikke skrevet" and was said, as designed. The scheduled Monday send is first seen on 12 October.
- 2026-10-08 (agent): on the boxes. "With a link to the full view": left out on @edmir's call, since the app runs on a Mac a phone cannot reach; the email is complete instead. The link waits for hosting (Backlog). DPA: Resend's GDPR Art. 28 DPA is pre-signed for every account (resend.com/legal/dpa); data is stored in the US — the sending region does not move it — with transfers under the EU SCCs and the EU-US Data Privacy Framework (resend.com/security/gdpr). @edmir: data location does not matter yet; revisit before a customer's books go through it.
