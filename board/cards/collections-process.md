---
title: Build a daily collections list that flags repeat late payers
owner: @either
milestone: #liquidity
created: 2026-09-29
---
## Goal
`cards.py` already drafts a reminder per late customer. What is missing is the process around it: who is late, who is *habitually* late, what goes out today, with the chase drafted.

**Note.** Owner is @either: sending anything outward is a product and liability decision, and `cards.py` deliberately has no mail server today.

## Done when
- [ ] Habitual lateness is distinguished from a one-off
- [ ] A daily view of what should go out
- [ ] The draft survives being sent without editing

## Log
- 2026-09-29 (agent): created, transferred from TODO.md
