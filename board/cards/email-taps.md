---
title: Record taps from the Monday email, with the user's consent
owner: @edmir
milestone: #metrics
created: 2026-10-30
---
## Goal
The last open box on card 15 (`service-metrics.md`): email opens and link taps as a proxy for the CEO's time. Since card 36 the Monday email links each decision and the brief into the app, so whether the CEO acts on the letter from the email can be seen. Measured by our own app, without an open pixel or a third party, and only for a user who has said yes.

## Done when
- [x] Consent: each user's yes or no is stored with when; asked once at the first login, with «Ja, gjerne» and «Nei takk» equal; changeable on Selskapet. Without a yes the server stores no minutes and no taps, whatever the app sends
- [x] The email's links carry `?fra=brev&b=<brief id>` before the `#…`; the app records one tap (brief, card or Saker) on arrival and takes the marker out of the address; it survives logging in
- [x] `#maling` shows, per week, the Monday letter: when it was sent, taps on the brief, cards and Saker, the time from the send to the first visit, and minutes that day
- [x] Personvern (no and en) says minutes and taps are counted only with a yes
- [x] Tests: nothing stored without consent, a tap stored once, the links with and without `CFO_APP_URL`, the week's numbers on `#maling`
- [ ] Tested live: yes on the phone, the letter sent again, a card tapped, the tap on `#maling`

## Log
- 2026-10-30 (agent+@edmir): planned and started. Decided by @edmir: our own taps, no open pixel (EDPB guidelines 2/2023 put pixels and tracking links under the cookie rules, and open counts are unreliable on Apple Mail and Gmail); a simple opt-in that also covers the minute signal from card 15. The minutes already recorded are only @edmir's own and are kept, covered by his yes.
- 2026-10-30 (agent): built. Migration 006: `consents` (one answer per user, with when) and `email_taps` (brief, link brief/card/saker, card). `metrics.ping` and `metrics.tap` keep nothing without a yes (and a tap only for a real weekly brief and a known link); `metrics.letters` gives each emailed brief its taps, minutes from the send to the first open minute, and minutes in the first 24 hours; `/api/metrics` carries it per week as `letter`. Endpoints `/api/consent` (GET/POST) and `/api/email-tap`. The email's links are `APP_URL/?fra=brev&b=<id>#…`. The app asks once (`ConsentPrompt`, «Ja, gjerne» and «Nei takk» alike), holds a tap from the email until the answer, takes the marker out of the address, and keeps it through the email-link login; Selskapet has the switch; `#maling` a «Mandagsbrevet» table. Personvern no/en: minutes and taps only with a yes, basis consent (6(1)(a)), no tracking images. Tests 470 passed, 1 failed (the demo date test). Smoke-tested in demo mode: before a yes `recorded: false`, after it true. Left: the live test.
