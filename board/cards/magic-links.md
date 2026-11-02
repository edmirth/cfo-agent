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
- [ ] Each decision in the Monday brief carries a signed link to its card
- [ ] The link works without a password, for one company and one card, and expires
- [ ] Approving from the link records the decision exactly as the in-app button does
- [ ] An expired or altered link fails closed with a plain Norwegian message

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 11 in Next: turns the brief's decisions into one-tap approvals.
- 2026-10-25 (agent): the server and the web page it waited for are now [[render-deploy]] and [[platform-switch-over]] (cards 51, 52). This waits on those.
- 2026-11-03 (agent+@edmir): claimed; cards 51, 52 and 36 are done, so nothing it waited for is left. Decided by @edmir: a link lives 7 days (that week's brief), is used once, works only while its card is open, and opens that one card and nothing else; seeing the rest still needs a login. When card 42 lets a tap send something through Tripletex, the link must ask for a login first.
- 2026-11-03 (agent): plan. A random token per decision, minted when the brief is sent (`card_links`, migration 007), kept only as its SHA-256, so the database holds nothing a link can be rebuilt from and an altered token simply matches nothing. No signing key to configure. Two routes open without a login, the token in the POST body so it never lands in an access log: `/api/link` shows the card, `/api/link/decide` calls the same `cards.decide` as the button in the app and marks the link used. The email's decision links become `APP_URL/?fra=brev&b=<id>#godkjenn/<token>`; the app shows that page before the login gate. A tap through it is not counted for #maling (card 37 counts only a signed-in user's yes); «Åpne i appen» from it is.
