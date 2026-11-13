---
title: Readiness levels, test companies and the onboarding questions for a new company
owner: @either
milestone: #forecast
created: 2026-11-13
---
## Goal
Card 72, phase 5 of `docs/cashflow-spec.md`: a plug-and-play cash-flow forecast
that works for any company that connects, in a smaller, typed and tested module. Read the
spec first; its principle holds for every phase: the AI chooses the data (the data map),
code fetches and calculates every krone.

Based on `main`, never stacked. The snapshot tests from card 67 stay green, and any number
that changes on purpose is updated in its own commit with the reason.

## Done when
- [ ] Readiness levels in one place (§4.4), each with a test
- [ ] Fixture companies with a known correct profile: a retailer at 15 % VAT, a consultancy with no
      stock, a company with no staff, a seasonal business, a yearly VAT term, a company under
      3 months old. Each gives a sensible forecast and discovery finds its profile
- [ ] Onboarding report and questions in the app. Answers written to `company.md`

## Log
- 2026-11-13 (claude): created from the spec on @edmir's request
