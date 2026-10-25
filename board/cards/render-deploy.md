---
title: Make the platform deployable on Render: Tripletex login kept on the disk, pinned versions, Dockerfile, nightly backup
owner: @edmir
milestone: #platform
created: 2026-10-25
---
## Goal
The platform runs only while the Mac runs `run.sh`. To run on Render at `app.arvaka.no`, around the clock, the code needs a few changes first. Planned with @edmir: Render with a disk (not a VPS), one copy per pilot company, SQLite until one shared app is built (`docs/database.md`). The landing page is already on Render (`docs/hosting.md`).

## Done when
- [x] The rotated Tripletex refresh token is kept in `state/` on the disk, taken from the setting the first time; a new login put in Render's settings replaces it. Today `tlx_oauth.py` writes it to `.env`, which Render does not have, so the first restart would lock the account out
- [x] Library versions are pinned, so Render runs what was tested, and `test_auth.test_the_page_itself_is_not_behind_the_gate` passes on a fresh install
- [x] A Dockerfile builds the frontend and runs the backend: one worker, no `--reload`, Render's port, and never `.env` or `state/` inside
- [x] `render.yaml`: one web service in Frankfurt, a disk on `state/`, health check on `/api/auth/config`, deployed on merge to main
- [x] A nightly backup: a safe copy of `state/cfo.db` and `company.md`, the last 14 kept on the disk and one copy outside Render
- [x] The server refuses to start on Render with `CFO_AUTH=off`
- [x] `docs/hosting.md` covers the platform: first deploy, adding a pilot company, moving `state/` from the Mac, restoring a backup

## Log
- 2026-10-25 (agent): created on @edmir's call. Open for @edmir: where the backup copy outside Render goes (Supabase Storage in Stockholm needs no new provider). Related: [[tripletex-login-expiry]] (card 18): on a server, nobody sees the terminal when the Tripletex login expires, as it did on 2026-10-07.
- 2026-10-25 (agent): claimed on @edmir's go-ahead, branch `render-deploy`. Backup outside Render: Supabase Storage, encrypted before it leaves Render (recommended in chat; @edmir did not object).
- 2026-10-25 (agent): Tripletex login: the rotated token goes to `state/tripletex.json` (0600), with a fingerprint of the setting it started from; a different setting is a new login and wins. `.env` is no longer written by the server. Tests: `tests/test_tlx_oauth.py`.
- 2026-10-25 (agent): versions pinned to what the Mac runs (anthropic 1.4.0, fastapi 0.141.1, starlette 1.6.0 …), transitive ones too. The failing test was the test's fake client: newer Starlette listens for a disconnect while sending a file, and the fake answered with a second request. Fixed in the test; it passes on starlette 1.6 and 1.10. Fresh install: 453 passed.
- 2026-10-25 (agent): Dockerfile + .dockerignore. Built locally and run as Lindeskar: `/api/auth/config` 200, the page 200, an API route without login 401, no `.env` in the image. Runs as root, because a Render disk's owner is not something the image can know in advance.
- 2026-10-25 (agent): `config.HOSTED` (Render sets `RENDER`; `CFO_HOSTED` for any other host); `auth.check_config()` refuses `CFO_AUTH=off` there. Checked in the image with `RENDER=true CFO_AUTH=off`: refuses with the reason.
- 2026-10-25 (agent): nightly backup as scheduler job `backup` (02:00, every night): `backend/backup.py`, `scripts/backup.py` (key / now / open). Tried on the real data: 135 kB, opens with all 36 cards, integrity ok. The upload to Supabase Storage is tested against a fake only; the first real one waits for a bucket and a service key. Also the rulebook's neighbours (definitions, profile, summary) go in; the Tripletex token does not.
- 2026-10-25 (agent): `render.yaml`: one Docker web service, Frankfurt, Starter, a 1 GB disk on `/app/state`, health check `/api/auth/config`, deploy on every commit to main. Not yet read by Render itself; card 52 is where it meets the real thing.
- 2026-10-25 (agent): restoring is a copy left in `state/restore/` and a restart; the server swaps it in at start-up, before anything opens the database, and keeps what was there in `before-restore-<time>/`. `scripts/backup.py list` / `fetch` bring a copy back from Supabase. Checked end to end in Docker: the Mac's real copy went in on start-up, 36 cards and 11 forecasts. `docs/hosting.md` has first deploy, adding a company, moving from the Mac, restoring.
- 2026-10-25 (agent): verified: 463 tests pass on the Mac and on a fresh install; the image builds and runs; a demo server answers health, overview, preflight, commitments, cashflow, cards, rules, dashboard, and the schedule lists the backup at 02:00. Not verified until card 52: Render reading `render.yaml`, and a real upload to Supabase Storage.
- 2026-10-25 (agent): found while verifying: the real Tripletex login has expired (`invalid_grant: Session not found`; last good call 2026-10-23 08:26). Not caused by this card: the server sent the same token the old code would have. Fix: `./.venv/bin/python scripts/oauth_login.py`, which @edmir runs (it needs a browser). Same failure as card 18.
