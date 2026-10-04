---
title: Produce the onboarding health check and the clean-up list for the regnskapsfører
owner: @agent
milestone: #onboarding
created: 2026-10-04
priority: 13
---
## Goal
"The Cash tier sells on the health check, the Monday brief and seasonal warnings." The health check is 2–3 pages: cash and runway, payroll-ratio trend, receivables and concentration, VAT and tax status, and data gaps. The clean-up list is what the regnskapsfører must fix: unposted invoices, missing project codes, unreconciled accounts. `preflight.py` and `commitments.py` already find most of it; nothing turns it into a deliverable. It is an agent job on the shared core.

## Done when
- [ ] One action produces the health check for a newly connected company
- [ ] Every figure comes from the engine and passes `verify`
- [ ] The clean-up list states preflight's findings in words a regnskapsfører can act on, ready to forward
- [ ] Both are saved and viewable in the app, and a card asks the CEO to forward the list

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 13 in Next: what the Cash tier sells on to a new customer.
