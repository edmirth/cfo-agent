---
title: Move the platform from the Mac to app.arvaka.no: a test run with a demo company, then the switch-over
owner: @edmir
milestone: #platform
created: 2026-10-25
---
## Goal
Once [[render-deploy]] is merged, the platform moves to Render, first as a demo company with made-up books, then as the real company with its history, at `app.arvaka.no`. After this the Mac is for development only.

## Done when
- [x] Test run: the platform runs on Render as a demo company with login on; signing in from a phone, the front page and a chat answer work, and the data survives a deploy
- [x] Switch-over: `run.sh` stopped on the Mac for the real company, `state/` copied safely and uploaded to the disk, the keys in Render's settings with the newest Tripletex token
- [x] The front page on Render shows the same figures the Mac did
- [x] The Tripletex token is gone from the Mac's `.env`; the Mac runs the demo companies, or its own separate login with the morning run and email off
- [x] DNS at domene.no: a CNAME `app` to the service's `onrender.com` address, and the certificate issued
- [x] Supabase: Site URL `https://app.arvaka.no`, also under Redirect URLs
- [x] The 07:00 morning run happens on Render on the next working day

## Log
- 2026-10-25 (agent): created on @edmir's call. Waits on [[render-deploy]]. Render's Hobby plan includes two custom domains, both used by arvaka.no and www; `app.arvaka.no` is a third, $0.25 a month. Pick a switch-over time outside 07:00 to 08:00 on a working day.
- 2026-10-25 (agent): claimed on @edmir's go-ahead, branch `platform-switch-over`. Decided with @edmir: the test run is a service of its own, `arvaka-demo` (Lindeskar), kept online afterwards for sales demos; the real company is `arvaka-app`.
- 2026-10-25 (agent): code side done (PR below): `arvaka-demo` in `render.yaml` (CFO_STATE on the disk, morning run off); a hosted demo writes its own company.md and profile at start; `arvaka-app` no longer asks for the Tripletex login in the Blueprint, so applying it while the Mac runs cannot lock the account out; `docs/hosting.md` has the demo and the switch-over step by step. Checked in Docker: the demo's files land on the disk and survive a restart. 464 tests pass. Next: @edmir merges, then the Render, Supabase and DNS steps.
- 2026-10-25 (agent+@edmir): Blueprint applied; both services live at arvaka-app.onrender.com and arvaka-demo.onrender.com, login on, API 401 without it. Test run on the phone: Lindeskar, Kjør nå, a chat answer, and the brief still there after a deploy.
- 2026-10-25 (agent+@edmir): the backup to Supabase tested for real from the Mac (sent, unreadable without the key, opened: 36 cards, integrity ok). Switch-over at ~18:45: nothing running on the Mac, the Mac's figures noted, a final copy sent, the Tripletex login added by hand in Render, the copy fetched in Render's Shell and put in place at restart. Two snags: `COMPANY_NAME` was empty on Render (so it looked in `selskapet/`), and `CFO_BACKUP_KEY` was not a valid key there; both fixed in Render's settings. The front page on Render matches the Mac (revenue 14 901 128, operating result −407 715, bank 4 004 930, receivables 2 347 796).
- 2026-10-25 (agent): the Tripletex login taken off the Mac: the lines gone from `.env` and its two backups, `state/tripletex.json` deleted. While doing it the agent printed three secrets into the chat; card 54 rotates them.
- 2026-10-25 (agent+@edmir): app.arvaka.no: Custom Domain in Render, CNAME `app` → `arvaka-app.onrender.com` in domene.no's zone editor, certificate issued (Google Trust Services, to 2027-01-23). Supabase Site URL `https://app.arvaka.no`, added under Redirect URLs beside the two onrender.com addresses. @edmir signed in on the phone at app.arvaka.no.
- Left: the 07:00 morning run on Render on Monday 2026-10-26.
- 2026-10-26 (agent+@edmir): the Monday run on Render, from its log: the brief for 2026-W44 written by the model at 07:02 (GUL, 4 decisions), the email accepted by Resend and delivered. Gmail put it in Spam, as mail from Resend's shared `onboarding@resend.dev` tends to go; marked not spam. Done.
