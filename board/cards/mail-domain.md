---
title: Send the Monday brief from cfo@arvaka.no: verify arvaka.no in Resend
owner: @edmir
milestone: #delivery
created: 2026-10-25
---
## Goal
The Monday brief goes out from Resend's test sender, which only delivers to the email the Resend account was made with ([[email-delivery]]). With arvaka.no verified, it can go from `cfo@arvaka.no` to anyone in `brev_mottakere`, and Resend can record opens and link taps, which card 37 waits for.

## Done when
- [ ] arvaka.no is verified in Resend, its records added at domene.no; the MX for `mail.arvaka.no` is untouched, so email to @arvaka.no keeps working
- [ ] `CFO_MAIL_FROM` is set to `cfo@arvaka.no`, and a test send from the front page reaches an address outside the Resend account
- [ ] The SPF line at domene.no is tidied: `+a` removed, since arvaka.no now points at Render, which sends no mail
- [ ] A DMARC record (`_dmarc.arvaka.no`) exists, at least `p=none`, so mail providers trust the brief

## Log
- 2026-10-25 (agent): created on @edmir's call. Resend's records go on `send.arvaka.no` and `resend._domainkey.arvaka.no`, beside the existing email at domene.no, not instead of it. The databehandleravtale draft already lists Resend.
