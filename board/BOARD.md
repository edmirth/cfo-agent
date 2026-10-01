---

kanban-plugin: board

---

## Backlog

- [ ] Build an in-app screen to connect a customer's own accounting system @either #platform
- [ ] Add login and authentication in front of every API route @either #platform
- [ ] Move chat sessions from an in-process dict into a shared store @either #platform
- [ ] Model December half-tax and the feriepenger month in the payroll forecast @agent #forecast
- [ ] Add a scheduler so the daily brief and checks run unprompted @either #ops
- [ ] Add deterministic ledger tripwires to the pre-flight checks @agent #warnings


## Next



## Doing






## Done

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