---
title: Add a scheduler so the daily brief and checks run unprompted
owner: @either
milestone: #ops
created: 2026-09-29
priority: 6
---
## Goal
Nothing is early, because nothing runs unasked. Everything in the early-warning lane is worth roughly half while the owner has to think to ask. The README says the same of the daily brief.

**Note.** Owner is @either: where this runs — cron, a scheduled deployment, something else — depends on where you intend to host it.

## Done when
- [x] The daily brief arrives without being asked for
- [x] Pre-flight checks run on a cadence
- [x] A failed run is visible rather than silent

## Log
- 2026-09-29 (agent): created, transferred from TODO.md
- 2026-10-04 (agent): scope set by the AI CFO Strategy Playbook: the brief is weekly, not daily. Monday 07:00 runs figures → save forecast → [[watch-job]] → [[weekly-brief]] → [[email-delivery]]; weekday mornings run [[watch-job]]. Moved to Next.
- 2026-10-04 (agent): priority 6 in Next: without it nothing arrives unasked, which is the difference between a tool and a service.
- 2026-10-08 (agent): claimed. Hosting decision (owner): run on the Mac for
  now. So the scheduler is a task inside the server (`backend/scheduler.py`),
  not cron: a second process renewing the Tripletex token would lock the
  account out (`lock.py`), and the same code moves to a host unchanged.
- 2026-10-08 (agent): built. Every Norwegian working day at 07:00 Oslo time
  the `morning` run does, in order: preflight checks → cashflow (keeps today's
  forecast and bank balances, scores old ones) → overview + commitments (keeps
  the KPI snapshot) → cards refresh → summary. It checks the wall clock every
  minute, so a Mac that slept through seven catches up within a minute of
  waking, the same day only; a slot is run once (`job_runs`, started after the
  slot). A step that fails costs that step, not the run (`partial`); a run
  that is not `ok` is retried 30 min after it started, 3 attempts at most. A
  run the server died in is closed as `failed` at the next startup
  (`job_runs.close_orphans`) and retried. Work a scheduled run causes is
  filed with `triggered_by = 'schedule'` via a `job_runs.trigger` ContextVar.
  Visible: `GET /api/schedule` gives an `attention` sentence for a failed,
  partial or missed (server off) morning, shown at the top of the front page
  with a **Kjør nå** button (`POST /api/schedule/morning/run`); a good run
  shows "Klargjort HH:MM" in the header. A dead Tripletex login is named
  once with its fix (`scripts/oauth_login.py`). Settings: `CFO_SCHEDULER`,
  `CFO_MORNING_AT`, `CFO_TIMEZONE`. "Arrives" means waiting in the app;
  by email is [[email-delivery]]. The Monday chain adds [[weekly-brief]] and
  [[email-delivery]] as steps; weekday [[watch-job]] likewise.
- 2026-10-08 (agent): 265 tests pass (13 new in `tests/test_scheduler.py`:
  slots over weekends, Christmas, Easter and the October clock change; catch-up
  after sleep; no run for a day already gone; retry, give-up and their
  sentences; orphaned run; trigger filing; no runaway when the database will
  not record). Live check in the cloud container (no Tripletex or Anthropic
  credentials): the server started the scheduler, caught up the 07:00 slot at
  09:00, recorded it `partial`, a restart did not run it twice, the manual run
  was filed as `user`, and the front page showed the notice and, after an ok
  run, "Klargjort". Not yet seen against real data: the first real morning is
  the next working day the Mac is awake with `run.sh` going.
