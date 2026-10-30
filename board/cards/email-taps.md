---
title: Record taps from the Monday email, with the user's consent
owner: @edmir
milestone: #metrics
created: 2026-10-30
---
## Goal
The last open box on card 15 (`service-metrics.md`): email opens and link taps as a proxy for the CEO's time. Since card 36 the Monday email links each decision and the brief into the app, so whether the CEO acts on the letter from the email can be seen. Measured by our own app, without an open pixel or a third party, and only for a user who has said yes.

## Done when
- [ ] Consent: each user's yes or no is stored with when; asked once at the first login, with «Ja, gjerne» and «Nei takk» equal; changeable on Selskapet. Without a yes the server stores no minutes and no taps, whatever the app sends
- [ ] The email's links carry `?fra=brev&b=<brief id>` before the `#…`; the app records one tap (brief, card or Saker) on arrival and takes the marker out of the address; it survives logging in
- [ ] `#maling` shows, per week, the Monday letter: when it was sent, taps on the brief, cards and Saker, the time from the send to the first visit, and minutes that day
- [ ] Personvern (no and en) says minutes and taps are counted only with a yes
- [ ] Tests: nothing stored without consent, a tap stored once, the links with and without `CFO_APP_URL`, the week's numbers on `#maling`
- [ ] Tested live: yes on the phone, the letter sent again, a card tapped, the tap on `#maling`

## Log
- 2026-10-30 (agent+@edmir): planned and started. Decided by @edmir: our own taps, no open pixel (EDPB guidelines 2/2023 put pixels and tracking links under the cookie rules, and open counts are unreliable on Apple Mail and Gmail); a simple opt-in that also covers the minute signal from card 15. The minutes already recorded are only @edmir's own and are kept, covered by his yes.
