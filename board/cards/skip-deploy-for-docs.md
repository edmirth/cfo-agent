---
title: Skip the Render deploy when a merge only changes the board or the docs
owner: @edmir
milestone: #platform
created: 2026-10-25
---
## Goal
Every merge to `main` rebuilds and restarts both services, and a service with a disk is away for about a minute while it does. A PR that only moves a card or edits a doc does not change the app, so it should not restart it, least of all around the 07:00 morning run.

## Done when
- [ ] `render.yaml`: a build filter on both services, so changes only under `board/`, `docs/`, `site/`, `site-pages/`, `tests/` or to `*.md` at the root do not deploy them
- [ ] The landing page's static site deploys only for `site/` (set in Render's dashboard, since it is not in `render.yaml`)
- [ ] A board-only merge is shown not to restart `app.arvaka.no`, and a merge that changes `backend/` still does

## Log
- 2026-10-25 (agent): created on @edmir's call.
