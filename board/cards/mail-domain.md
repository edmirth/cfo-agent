---
title: Send the Monday brief from cfo@arvaka.no: verify arvaka.no in Resend
owner: @edmir
milestone: #delivery
created: 2026-10-25
---
## Goal
The Monday brief goes out from Resend's test sender, which only delivers to the email the Resend account was made with ([[email-delivery]]). With arvaka.no verified, it can go from `cfo@arvaka.no` to anyone in `brev_mottakere`, and Resend can record opens and link taps, which card 37 waits for.

## Done when
- [ ] arvaka.no is verified in Resend (region EU), its records added at domene.no; the MX to Google Workspace is untouched, so email to @arvaka.no keeps working
- [ ] `CFO_MAIL_FROM` is set to `cfo@arvaka.no` in Render, with cfo@ an alias in Workspace so replies arrive, and a test send reaches an address outside the Resend account
- [ ] The Monday brief lands in the Gmail inbox, not Spam (on 2026-10-26 the W44 brief from the test sender went to Spam)
- [ ] The SPF line at domene.no is tidied: `+a` removed, since arvaka.no now points at Render, which sends no mail
- [x] A DMARC record (`_dmarc.arvaka.no`) exists, at least `p=none`, so mail providers trust the brief

## Log
- 2026-10-25 (agent): created on @edmir's call. Resend's records go on `send.arvaka.no` and `resend._domainkey.arvaka.no`, beside the existing email at domene.no, not instead of it. The databehandleravtale draft already lists Resend.
- 2026-10-30 (agent+@edmir): started. Card 57 (PR #74) was a duplicate of this one and is removed; its inbox-not-Spam check is a box here now. DNS checked: MX now goes to Google Workspace (not `mail.arvaka.no`), Google's DKIM is in place, and `_dmarc` already says `v=DMARC1; p=none;`. SPF is `+a +mx +ip4:185.126.36.19 include:_spf.google.com include:_spf.spamprotection.no ~all`; no Resend records yet.
