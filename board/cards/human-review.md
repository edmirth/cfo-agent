---
title: Hold the agent's output for human review while a customer is new
owner: @either
milestone: #review
created: 2026-10-04
priority: 15
---
## Goal
The playbook's MVP includes human review: "Onboarding: human reviews everything. Graduated: random samples plus anything the agent flags as uncertain. Mature: exceptions only." Graduation criteria: the 4-week-ahead forecast within about ±10% for 8 weeks in a row, over 90% of prepared actions approved without edits, and no critical errors.

**Note.** Owner is @either: who reviews, and through which screen, is your call.

## Done when
- [ ] Each company has a review mode: onboarding, graduated or mature
- [ ] In onboarding, the brief and new cards wait in a review queue and go out only once approved
- [ ] The reviewer can edit before approving, and the edit is recorded
- [ ] Graduation status is computed from [[forecast-ledger]] and [[service-metrics]]

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 15 in Next: needed before the first paying customer beyond the pilot; uses the metrics.
