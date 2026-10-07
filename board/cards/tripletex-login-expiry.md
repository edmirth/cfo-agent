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
- [ ] After an `invalid_grant`, further renewals fail at once with the same
      message, without calling Tripletex, until `.env` holds a new refresh
      token (e.g. the login script has run) or the server restarts
- [ ] The front page shows one clear notice when Tripletex access is gone:
      that the figures cannot be fetched, and the command to log in again
- [ ] `/api/health` reports the Tripletex login as ok, expired or missing
- [ ] The login script's docstring and output stop saying the token never
      expires
- [ ] A test pins that thirty waiting requests make one renewal call, not thirty

## Log
- 2026-10-07 (agent): created after the refresh token expired during the
  state-database live check; the owner logged in again with
  `scripts/oauth_login.py`. Cause of the retry burst read from
  `tlx_oauth.py`: the lock serialises the retries but nothing records the
  failure.
