---
title: Make the platform deployable on Render: Tripletex login kept on the disk, pinned versions, Dockerfile, nightly backup
owner: @edmir
milestone: #platform
created: 2026-10-25
---
## Goal
The platform runs only while the Mac runs `run.sh`. To run on Render at `app.arvaka.no`, around the clock, the code needs a few changes first. Planned with @edmir: Render with a disk (not a VPS), one copy per pilot company, SQLite until one shared app is built (`docs/database.md`). The landing page is already on Render (`docs/hosting.md`).

## Done when
- [ ] The rotated Tripletex refresh token is kept in `state/` on the disk, taken from the setting the first time; a new login put in Render's settings replaces it. Today `tlx_oauth.py` writes it to `.env`, which Render does not have, so the first restart would lock the account out
- [ ] Library versions are pinned, so Render runs what was tested, and `test_auth.test_the_page_itself_is_not_behind_the_gate` passes on a fresh install
- [ ] A Dockerfile builds the frontend and runs the backend: one worker, no `--reload`, Render's port, and never `.env` or `state/` inside
- [ ] `render.yaml`: one web service in Frankfurt, a disk on `state/`, health check on `/api/auth/config`, deployed on merge to main
- [ ] A nightly backup: a safe copy of `state/cfo.db` and `company.md`, the last 14 kept on the disk and one copy outside Render
- [ ] The server refuses to start on Render with `CFO_AUTH=off`
- [ ] `docs/hosting.md` covers the platform: first deploy, adding a pilot company, moving `state/` from the Mac, restoring a backup

## Log
- 2026-10-25 (agent): created on @edmir's call. Open for @edmir: where the backup copy outside Render goes (Supabase Storage in Stockholm needs no new provider). Related: [[tripletex-login-expiry]] (card 18): on a server, nobody sees the terminal when the Tripletex login expires, as it did on 2026-10-07.
- 2026-10-25 (agent): claimed on @edmir's go-ahead, branch `render-deploy`. Backup outside Render: Supabase Storage, encrypted before it leaves Render (recommended in chat; @edmir did not object).
