---

kanban-plugin: board

---

## Backlog

- [ ] Build an in-app screen to connect a customer's own accounting system @either #platform
- [ ] Add login and authentication in front of every API route @either #platform
- [ ] Move chat sessions from an in-process dict into a shared store @either #platform
- [ ] Add a scheduler so the daily brief and checks run unprompted @either #ops
- [ ] Make the 13 Week Cash brief stronger, and more accurate so that the user gets the right information it needs. Go on to the deep side of building it right, and the AI CFO Agent to understand it and build them.
- [ ] Open the forecast on the money that is in the bank, not on the booked balance @edmir #liquidity
- [ ] How could we design the ai agent to look at the numbers and then also the company and then understand their industry, and know then what type of CFO work it needs and how they operate in the sense of financials.
- [ ] Could we use AI to reason and be smart on which numbers and data to get from Tripletex for then to model the right type of 13 week cash brief, so that we could have the right numbers and smarter type of CFO work.
- [ ] We need to make a database for the platform here, and also design the architecture of the database here so the agent can actually use it and also how to store the database here. We need to make a good database for the platform and also structure it.


## Next



## Doing



## Done

- [x] Place the 13 Week Cash Table on a better visual part, so that it it at least over the CFO summary and under the 4 cards, but that it is visible to see and track. ✓ 2026-10-02
- [x] Model December half-tax and the feriepenger month in the payroll forecast @agent #forecast ✓ 2026-10-02
- [x] Add deterministic ledger tripwires to the pre-flight checks @agent #warnings ✓ 2026-10-02
- [x] Pay the skattetrekk on pay day, and stop treating feriepenger as cash @agent #forecast ✓ 2026-10-01
- [x] Use FTE from Tripletex instead of headcount in per-employee KPIs @agent #kpi ✓ 2026-10-01
- [x] Add tests for the single-flight cache and the equity ratio @agent #tests ✓ 2026-10-01
- [x] Pay wages on the day company.md says, not month end @agent #forecast ✓ 2026-10-01
- [x] Find why open invoices do not reconcile to account 1500 @agent #liquidity ✓ 2026-09-30
- [x] Split booked VAT by term so each lands on its own due date @agent #forecast ✓ 2026-09-30
- [x] Retry failed Tripletex report builds instead of caching empty KPIs @agent #reliability ✓ 2026-09-30
- [x] Roll due dates forward off weekends and Norwegian holidays @agent #forecast ✓ 2026-09-30
- [x] Top up the Anthropic credit balance @edmir #ops ✓ 2026-09-29
- [x] Enforce read-only with a Tripletex toolset allowlist @agent #platform ✓ 2026-09-29




%% kanban:settings
```
{"kanban-plugin":"board"}
```
%%