---
title: Flag customers with bankruptcy or dissolution notices from Brønnøysund
owner: @agent
milestone: #warnings
created: 2026-10-04
---
## Goal
Brønnøysundregistrene is one of the playbook's three MVP data sources (free and open), and "late or at-risk customer" is a Cash-tier alert. `lookup_company_in_brreg` is already in the read-only allowlist, but nothing uses it.

## Done when
- [ ] Every customer with an open receivable is checked against Enhetsregisteret at least weekly
- [ ] Bankruptcy, liquidation or dissolution raises a card with the amount at risk
- [ ] Results are cached, and a failed lookup is reported rather than treated as clean

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
