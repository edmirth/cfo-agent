---
title: Open and approve a card with one tap from the email
owner: @agent
milestone: #delivery
created: 2026-10-04
priority: 11
---
## Goal
The playbook's decision queue is reached by "app cards, magic links from email" with "no-friction access: magic links, no password to approve a reminder". Depends on [[login-on-the-app]] and [[email-delivery]].

## Done when
- [x] Each decision in the Monday brief carries a signed link to its card
- [x] The link works without a password, for one company and one card, and expires
- [x] Approving from the link records the decision exactly as the in-app button does
- [x] An expired or altered link fails closed with a plain Norwegian message

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 11 in Next: turns the brief's decisions into one-tap approvals.
- 2026-10-25 (agent): the server and the web page it waited for are now [[render-deploy]] and [[platform-switch-over]] (cards 51, 52). This waits on those.
- 2026-11-03 (agent+@edmir): claimed; cards 51, 52 and 36 are done, so nothing it waited for is left. Decided by @edmir: a link lives 7 days (that week's brief), is used once, works only while its card is open, and opens that one card and nothing else; seeing the rest still needs a login. When card 42 lets a tap send something through Tripletex, the link must ask for a login first.
- 2026-11-03 (agent): plan. A random token per decision, minted when the brief is sent (`card_links`, migration 007), kept only as its SHA-256, so the database holds nothing a link can be rebuilt from and an altered token simply matches nothing. No signing key to configure. Two routes open without a login, the token in the POST body so it never lands in an access log: `/api/link` shows the card, `/api/link/decide` calls the same `cards.decide` as the button in the app and marks the link used. The email's decision links become `APP_URL/?fra=brev&b=<id>#godkjenn/<token>`; the app shows that page before the login gate. A tap through it is not counted for #maling (card 37 counts only a signed-in user's yes); «Åpne i appen» from it is.
- 2026-11-03 (agent): built. Migration 007 `card_links`; `card_links.py` mints a link per decision when the brief is sent (only with `CFO_APP_URL`), shows its card (`/api/link`) and decides it (`/api/link/decide`) through `cards.decide`, so the card, its `card_events` row (actor ceo) and the memory are written as from the app; the link is marked used under the write lock, and freed again if the decision fails. Refusals: altered or unknown 404, used or older than 7 days 410, card no longer open 409, each with a Norwegian sentence that ends in «Logg inn i appen». The `link` box is ticked for a random token kept as a hash, not a signature: same guarantee, no key to manage. Frontend: `#godkjenn/<token>` is drawn before the login gate with the app's own `DecisionBody` (draft editable, sent with the choice); after a choice it says «Registrert» and links on to the card in the app. Tests 482 passed, 0 failed (11 new in `test_card_links.py`); tsc and build clean. Checked in demo mode with login on: the card opens without a login, `/api/cards` still answers 401, a phone-sized browser tapped «Send påminnelsen» and the card was done with actor ceo, a reload said the link was used, the token is not in the access log. Left: the live test after the merge, a brief sent from app.arvaka.no and a decision approved from the phone.
- 2026-11-03 (agent+@edmir): PR #83 merged. @edmir ran the live test on app.arvaka.no and reports it passed. Done.
