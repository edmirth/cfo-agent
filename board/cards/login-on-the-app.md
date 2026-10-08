---
title: Add login and authentication in front of every API route
owner: @either
milestone: #platform
created: 2026-09-29
priority: 8
---
## Goal
There is none. Anyone who reaches the port gets the CFO and the company's complete ledger — bank balance, every customer, every invoice. On a laptop that is a nuisance; anywhere else it is the blocker.

**Note.** Owner is @either: I can implement whatever you choose, but which mechanism — your own accounts, an identity provider, something in front of the app — is your call. This is the gate on connect-own-accounting-system.

## Done when
- [x] The app requires a login before any `/api/*` route answers
- [x] Session handling survives a restart, or fails closed
- [x] The README's "No auth on the app itself" bullet can be deleted honestly

## Log
- 2026-09-29 (agent): created, transferred from TODO.md and the README's customer-readiness list
- 2026-10-04 (agent): needed by [[magic-links]], which the playbook makes the way the CEO approves from email. Moved to Next.
- 2026-10-04 (agent): priority 8 in Next: must exist before the brief and its links leave the building.
- 2026-10-08 (agent): claimed. @edmir chose: Supabase Auth for now (CEO only; BankID/Vipps later; our own accounts when the platform is rebuilt). Plan: `auth.py` is the only module that knows the provider. A middleware in front of every `/api/*` route (fail closed: a new route is covered without anyone remembering to) verifies the Supabase access token locally (signature from the project's JWKS, or the legacy HS256 secret; issuer, audience, expiry) and lets in only the emails in `CFO_OWNER_EMAIL`. `/api/auth/config` is the one open route: it hands the frontend the project URL and the public key. The server will not start without auth configured unless `CFO_AUTH=off` is set on purpose. Sessions are Supabase's signed tokens, refreshed in the browser, so a server restart logs no one out. Frontend: a login page (password, or a login link by email), the token on every `/api` call, sign-out in the sidebar.
- 2026-10-08 (agent): built on branch `login-on-the-app`. `backend/auth.py`: middleware on every `/api/*` route; the Supabase token checked locally (signature from the project's JWKS, kept an hour and refetched at most once a minute for a rotated key; or the legacy HS256 secret), issuer, audience, expiry, then the email against `CFO_OWNER_EMAIL` (403 when signed in but not listed). `alg: none` and HS256-without-a-secret are refused. The server stops at startup without SUPABASE_URL, SUPABASE_ANON_KEY and CFO_OWNER_EMAIL, unless CFO_AUTH=off. Frontend: `lib/auth.ts` (`authFetch` on all six call sites), a login page (password, or an email link with `shouldCreateUser: false`, PKCE so the link returns in `?code=` and not in the routing hash), sign-out in the sidebar, a 401/403 shows the login with the server's reason. Sessions are Supabase's own tokens, so a restart logs no one out. New dependency: `PyJWT[crypto]`. Tests: 15 new, among them one that walks every `/api` route in the app and asserts each answers 401 without a login, so a route added later is checked too. Suite 300 passed. Smoke-tested on a real uvicorn: config open, routes 401, page 200; a server without the settings refuses to start.
- 2026-10-08 (agent): BLOCKED on one check only: a real sign-in, which needs @edmir's Supabase project (README → Innlogging, five steps, then the three lines in `.env`). Do not merge before that: from the merge on, `./run.sh` stops without them. When it is set up: `./run.sh`, sign in with the password, then sign out and sign in with the email link; both should land on the front page with figures. Then tick this off and move the card to Done.
- 2026-10-08 (agent): unblocked. Supabase project `cfo-agent` (Stockholm, ref akygfxlimtcfulaknxbl) set up with the CLI: sign-ups off (a stranger's sign-up is refused with `signup_disabled`), site URL `http://localhost:8000`, the CEO's account created in the dashboard with a password; the three lines are in `.env`. Pushing `[auth.email] enable_signup = false` turned the whole email provider off ("Email logins are disabled"); @edmir switched it back on in the dashboard — `[auth] enable_signup = false` is the one that stops sign-ups. A real Supabase token (ES256, from the project's JWKS) was accepted on every front-page route. The first browser sign-ins bounced back to the login: `signOut()` defaults to every session on the account, so a stale tab's 401 threw out the tab that had just signed in. Automatic sign-out is now this tab only; the sidebar's Logg ut still signs out everywhere. @edmir signed in with the password and is in.
- 2026-10-08 (agent): not verified: the email login link. The one attempt was during the bounce above, so it may work now; until someone sees it work, the password is the way in.
