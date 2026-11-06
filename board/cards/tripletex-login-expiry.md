---
title: Say clearly when the Tripletex login has expired, and stop after one try
owner: @edmir
milestone: #platform
created: 2026-10-07
---
## Goal
On 2026-10-07 the Tripletex refresh token expired (`invalid_grant: Refresh
token expired - please re-authenticate`). Two things went wrong around it.

**1. Nobody was told.** `scripts/oauth_login.py` says the refresh token "never
expires" (*utløper ikke*), and the app treats it that way. When it did expire,
the only trace was in the server log; every panel just failed to load. The
owner has to know, in the app, that the CFO is blind until someone logs in
again, and what to run.

**2. One failure became about thirty.** `TokenManager.access_token()` in
`backend/tlx_oauth.py` serialises renewals with a lock but does not remember a
failure. Every request waiting on the lock, about thirty on a cold page,
then tries the dead refresh token again in turn. The first attempt answered
"Refresh token expired"; every one after it answered "Session not found". A
failure that only a browser login can fix should stop the next attempt until
the credentials change.

## Done when
- [x] After an `invalid_grant`, further renewals fail at once with the same
      message, without calling Tripletex, until `.env` holds a new refresh
      token (e.g. the login script has run) or the server restarts
- [x] The front page shows one clear notice when Tripletex access is gone:
      that the figures cannot be fetched, and the command to log in again
- [x] `/api/health` reports the Tripletex login as ok, expired or missing
- [x] The login script's docstring and output stop saying the token never
      expires
- [x] A test pins that thirty waiting requests make one renewal call, not thirty

### Extended on 2026-11-06 (@edmir)
Reading the code for why the front page did not show whether figures came in
found three more faults, added here:
- [x] A panel that fails on a dead login says so, not «Noe feilet i
      beregningen» (`main._panel` did not know an `OAuthError`)
- [x] Every panel keeps why it is empty: four of six dropped their error
- [x] The notice says when the headline is from the stored Monday brief,
      which otherwise looked fresh while nothing new could be fetched

## Log
- 2026-10-07 (agent): created after the refresh token expired during the
  state-database live check; the owner logged in again with
  `scripts/oauth_login.py`. Cause of the retry burst read from
  `tlx_oauth.py`: the lock serialises the retries but nothing records the
  failure.
- 2026-11-06 (agent): moved to ## Doing on @edmir's call, with the three
  faults above. Built on `tripletex-login-expiry`:
  - `TokenManager` remembers an `invalid_grant` or `invalid_client` and fails
    at once until `.env` holds a new login (taken without a restart) or the
    app restarts. A 5xx is not dead and is still retried.
  - `tokens.status()` gives ok / expired / missing / untested (and demo).
    `/api/health` carries it as `tripletex`.
  - One check and one message for the morning run and the panels:
    `tlx_oauth.is_login_error`, `LOGIN_LOST`, `login_fix()`. On Render the
    fix also says to put TRIPLETEX_CLIENT_ID and TRIPLETEX_REFRESH_TOKEN in
    the settings and restart.
  - The front page keeps each panel's reason, asks `/api/health` once the
    panels have answered, and shows one notice at the top.
  - Tests: 7 new in `tests/test_tlx_oauth.py`, and the scheduler test updated
    for the shared wording. Suite: 503 passed, 2 failed. Both failures are
    demo tests, `test_kvarnheim_runs_dry_unless_the_developer_pays` and
    `test_lindeskar_is_a_yellow_week_with_one_late_customer`, and both fail on
    `main` too, since the demo books depend on today's date.
  - Not seen in a browser yet: running the app here would renew the real
    login, which the server on Render needs. Check it on app.arvaka.no after
    the deploy.
- 2026-11-07 — Seen working on app.arvaka.no. Right after #90 deployed, the
  notice showed what it was built for: "invalid_grant: Session not found" on
  the server's login. Edmir logged in again with `scripts/oauth_login.py`,
  which registered a new client, so both `TRIPLETEX_CLIENT_ID` and
  `TRIPLETEX_REFRESH_TOKEN` had to go into Render. Once Render had both and
  had redeployed, @edmir confirmed the red notice was gone.
  - Follow-ups merged on the way: #91 (the scripts warn not to renew the
    login meant for Render) and #92 (the login script reuses the client id in
    `.env`, so next time only the refresh token changes).
  - Found on the way: the test run writes a copy of the login into the real
    `state/tripletex.json`. It saved the token as it was, without contacting
    Tripletex, so nothing was rotated, but tests should not touch `state/`.
