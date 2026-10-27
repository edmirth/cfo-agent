---
title: Send the Monday email from arvaka.no instead of Resend's test address
owner: @edmir
milestone: #platform
created: 2026-10-27
---
## Goal
The Monday email goes out from `onboarding@resend.dev`, Resend's shared test address. On 2026-10-26 Gmail put it in Spam, and Resend only lets that address send to the email the Resend account was made with, so no pilot customer could get the letter at all. Sending from our own domain, with the DNS records that prove it is ours, fixes both.

## Done when
- [ ] `arvaka.no` (or a subdomain such as `mail.arvaka.no`) added in Resend → Domains, and its SPF, DKIM and MX records put in domene.no's zone editor, until Resend shows the domain as Verified
- [ ] A DMARC record (`_dmarc`, `p=none` to start) in the zone editor
- [ ] `CFO_MAIL_FROM` set in Render's arvaka-app to an address on the domain, e.g. `Arvaka <brev@arvaka.no>`
- [ ] The Monday email, sent with «Send på e-post nå», lands in the Gmail inbox, not Spam
- [ ] It also reaches an address that is not the Resend account's own
- [ ] The comment in `.env.example` and `backend/config.py` that says the test address is all we have, updated

## Log
- 2026-10-27 (agent): created on @edmir's call, after the W44 email from Render went to Spam. Do it together with card 54 (a new Resend key) if that is still open.
