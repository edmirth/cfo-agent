---
title: Rotate the three keys shown in chat on 2026-10-25: Supabase service key (backups), CFO_BACKUP_KEY, Resend
owner: @edmir
milestone: #platform
created: 2026-10-25
---
## Goal
During the switch-over (card 52) the agent printed the end of `.env` into the chat by mistake, with three secrets in it. The chat is not public, but it is kept in Claude Code's logs and was sent to Anthropic, so the keys count as burned. `SUPABASE_ANON_KEY` was shown too; it is public by design and needs nothing.

## Done when
- [ ] Supabase, the backups project (`dtpfff…`): Project Settings → JWT Keys → rotate the legacy JWT secret; the new `service_role` key in `.env` (`SUPABASE_SERVICE_KEY`) and in Render (`arvaka-app`). The old key no longer works
- [ ] Resend: a new API key, the old one deleted; the new one in `.env` and Render (`RESEND_API_KEY`)
- [ ] `CFO_BACKUP_KEY`: a new key in `.env`, Render and the password manager (the agent writes it to `.env` and the clipboard without showing it); the copies in Supabase encrypted with the old key deleted, and a fresh copy sent with the new one
- [ ] `scripts/backup.py now` on the Mac and the nightly run on Render both send a copy afterwards

## Log
- 2026-10-25 (agent): created on @edmir's call. The keys stay in use until this is done; nothing has been seen misused.
