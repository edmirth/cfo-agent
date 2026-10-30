---
title: Link the Monday email to the full brief in the app
owner: @edmir
milestone: #delivery
created: 2026-10-30
---
## Goal
The Monday email was written to be complete on its own, because the app ran on a Mac no phone could reach. Now it runs at https://app.arvaka.no, so the email can take the CEO straight to what it mentions: the full brief, and each decision's card, where it is decided.

## Done when
- [ ] `CFO_APP_URL` says where the app is (`https://app.arvaka.no` in `render.yaml`); without it, as on a laptop, the email has no links and is exactly as before
- [ ] In the email: each decision links to its card (`#saker/<id>`), «og N til i appen» links to Saker, and a button opens the brief in the app; the plain-text version has the address
- [ ] A link from the email survives logging in: with a password it already does; with an email link it is kept and restored after
- [ ] Tests cover the email with and without `CFO_APP_URL`
- [ ] Tested for real: «Send på e-post nå» from app.arvaka.no, a decision tapped on the phone opens its card

## Log
- 2026-10-30 (agent): created and started on @edmir's call. `brief.decisions` already gives every card a `link` (`#saker/<id>`); the email did not use it. Password login keeps the address's `#…`; the email-link login (`signInWithOtp`) redirects to the origin and loses it.
