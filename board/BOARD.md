---

kanban-plugin: board

---

## Backlog

- [ ] Build an in-app screen to connect a customer's own accounting system @either #platform
- [ ] Move chat sessions from an in-process dict into a shared store @either #platform
- [ ] Make the 13 Week Cash brief stronger, and more accurate so that the user gets the right information it needs. Go on to the deep side of building it right, and the AI CFO Agent to understand it and build them.
- [ ] Build a monthly financial pack on a cadence, with an archive @either #pack
- [ ] Build a daily collections list that flags repeat late payers @either #liquidity
- [ ] Add budget-vs-actual variance per line, with the cause named @agent #kpi
- [ ] Send approved reminders through Tripletex after the CEO taps Send @edmir #actions
- [ ] Propose a weekly payment run with its cash effect @edmir #liquidity
- [ ] Let the agent propose company memory that the CEO approves @edmir #memory
- [ ] Add project mode to the cash engine for construction and painting @edmir #forecast
- [ ] Sync Tripletex and bank data into the database on a schedule @edmir #platform
- [ ] Isolate each customer's data and keep a full audit log @edmir #platform
- [ ] Push urgent alerts to the CEO's phone @edmir #delivery


## Next

- [ ] Extract the shared agent core so every AI job runs on it @agent #agent
- [ ] Store forecasts, cards, memory and job runs in a database @either #platform
- [ ] Move the cash floor, reminder days and alert minimum into the company rulebook @agent #rulebook
- [ ] Save every weekly forecast and score it against the real balance @agent #forecast
- [ ] Open the forecast on the money that is in the bank, not on the booked balance @edmir #liquidity
- [ ] Add a scheduler so the daily brief and checks run unprompted @either #ops
- [ ] Run a morning watch that raises and closes findings and cards unasked @agent #agent
- [ ] Write the Monday cash brief: traffic light, low point against the floor, what changed, up to three decisions @agent #agent
- [ ] Send the Monday brief by email @either #delivery
- [ ] Add login and authentication in front of every API route @either #platform
- [ ] Open and approve a card with one tap from the email @agent #delivery
- [ ] Produce the onboarding health check and the clean-up list for the regnskapsfører @agent #onboarding
- [ ] Flag customers with bankruptcy or dissolution notices from Brønnøysund @agent #warnings
- [ ] Hold the agent's output for human review while a customer is new @either #review
- [ ] Measure what the playbook says matters @agent #metrics
- [ ] Choose a PSD2 partner and read the balance from the bank @edmir #liquidity


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