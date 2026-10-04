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
- [ ] The daily brief arrives without being asked for
- [ ] Pre-flight checks run on a cadence
- [ ] A failed run is visible rather than silent

## Log
- 2026-09-29 (agent): created, transferred from TODO.md
- 2026-10-04 (agent): scope set by the AI CFO Strategy Playbook: the brief is weekly, not daily. Monday 07:00 runs figures → save forecast → [[watch-job]] → [[weekly-brief]] → [[email-delivery]]; weekday mornings run [[watch-job]]. Moved to Next.
- 2026-10-04 (agent): priority 6 in Next: without it nothing arrives unasked, which is the difference between a tool and a service.
