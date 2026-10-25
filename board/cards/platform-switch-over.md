---
title: Move the platform from the Mac to app.arvaka.no: a test run with a demo company, then the switch-over
owner: @edmir
milestone: #platform
created: 2026-10-25
---
## Goal
Once [[render-deploy]] is merged, the platform moves to Render, first as a demo company with made-up books, then as the real company with its history, at `app.arvaka.no`. After this the Mac is for development only.

## Done when
- [ ] Test run: the platform runs on Render as a demo company with login on; signing in from a phone, the front page and a chat answer work, and the data survives a deploy
- [ ] Switch-over: `run.sh` stopped on the Mac for the real company, `state/` copied safely and uploaded to the disk, the keys in Render's settings with the newest Tripletex token
- [ ] The front page on Render shows the same figures the Mac did
- [ ] The Tripletex token is gone from the Mac's `.env`; the Mac runs the demo companies, or its own separate login with the morning run and email off
- [ ] DNS at domene.no: a CNAME `app` to the service's `onrender.com` address, and the certificate issued
- [ ] Supabase: Site URL `https://app.arvaka.no`, also under Redirect URLs
- [ ] The 07:00 morning run happens on Render on the next working day

## Log
- 2026-10-25 (agent): created on @edmir's call. Waits on [[render-deploy]]. Render's Hobby plan includes two custom domains, both used by arvaka.no and www; `app.arvaka.no` is a third, $0.25 a month. Pick a switch-over time outside 07:00 to 08:00 on a working day.
- 2026-10-25 (agent): claimed on @edmir's go-ahead, branch `platform-switch-over`. Decided with @edmir: the test run is a service of its own, `arvaka-demo` (Lindeskar), kept online afterwards for sales demos; the real company is `arvaka-app`.
- 2026-10-25 (agent): code side done (PR below): `arvaka-demo` in `render.yaml` (CFO_STATE on the disk, morning run off); a hosted demo writes its own company.md and profile at start; `arvaka-app` no longer asks for the Tripletex login in the Blueprint, so applying it while the Mac runs cannot lock the account out; `docs/hosting.md` has the demo and the switch-over step by step. Checked in Docker: the demo's files land on the disk and survive a restart. 464 tests pass. Next: @edmir merges, then the Render, Supabase and DNS steps.
