---

kanban-plugin: board

---

## Backlog

- [ ] Build an in-app screen to connect a customer's own accounting system @either #platform
- [ ] Move chat sessions from an in-process dict into a shared store @either #platform
- [ ] Make the 13 Week Cash brief stronger, and more accurate so that the user gets the right information it needs. Go on to the deep side of building it right, and the AI CFO Agent to understand it and build them.
- [ ] Page through a truncated invoice month instead of warning about it @edmir #liquidity
- [ ] Convert foreign-currency supplier invoices instead of taking them as kroner @edmir #liquidity
- [ ] How could we design the ai agent to look at the numbers and then also the company and then understand their industry, and know then what type of CFO work it needs and how they operate in the sense of financials.
- [ ] Could we use AI to reason and be smart on which numbers and data to get from Tripletex for then to model the right type of 13 week cash brief, so that we could have the right numbers and smarter type of CFO work.
- [ ] We need to make a database for the platform here, and also design the architecture of the database here so the agent can actually use it and also how to store the database here. We need to make a good database for the platform and also structure it.
- [ ] Could autoresearch of ai agent be something that could help here for future fetaure so it could find stuff for the company and give it benefits or find something based on the data.
- [ ] Could the frontpage use any AI, and if so, what type of work would that be?
- [ ] On the backend there is a seperate file that does the summary, isnt it better to just let the ai agent make it? so it also has the memory, and also writes the summary as well.
- [ ] Based on the commintements.py, it uses the bankbalance and then subtracts everything owed. But we need to make sure that the bank balance that is used is actually correct, because we need the right answer/amount.
- [ ] Should we assign the ai agent to do the 13 week cash brief? could it be better at calculating it, and what tools would it need, should we give it coding tools so it could calculate it for us.
- [ ] give the project agent tool to use the web as well to get information. It could be for indusrey or other stuff.
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
- [ ] We only invoice with max 45 days, so most of the invoices go to 6 weeks ahead, so when we look at december we dont get the fully picture as the incvoices has not been sent out yet, and then it could look like we have a fall on the invooices around that time and low on cash, so we need to fix this, and maybe use like a average or try to predict what it could be around there.
- [ ] Say clearly when the Tripletex login has expired, and stop after one try @edmir #platform
- [ ] Link the Monday email to the full brief once the app is hosted somewhere a phone can reach @edmir #delivery


## Next

- [ ] 10. Choose a PSD2 partner and read the balance from the bank (We wait until we have done the meeting with Neonomics and enable banking) @edmir #liquidity
- [ ] 11. Open and approve a card with one tap from the email (We need to wait until we have the server up and running and a web page so we can use it on the phone as well) @agent #delivery
- [ ] 13. Produce the onboarding health check and the clean-up list for the regnskapsfører @agent #onboarding
- [ ] 14. Measure what the playbook says matters @agent #metrics
- [ ] 15. Hold the agent's output for human review while a customer is new @either #review
- [ ] 16. Flag customers with bankruptcy or dissolution notices from Brønnøysund @agent #warnings


## Doing

- [ ] 12. Run a morning watch that raises and closes findings and cards unasked @agent #agent


## Done

- [x] 9. Send the Monday brief by email @either #delivery ✓ 2026-10-08
- [x] 8. Add login and authentication in front of every API route @either #platform ✓ 2026-10-08
- [x] 7. Write the Monday cash brief: traffic light, low point against the floor, what changed, up to three decisions @agent #agent ✓ 2026-10-08
- [x] 6. Add a scheduler so the daily brief and checks run unprompted @either #ops ✓ 2026-10-08
- [x] 5. Save every weekly forecast and score it against the real balance @agent #forecast ✓ 2026-10-08
- [x] 4. Store forecasts, cards, memory and job runs in a database @either #platform ✓ 2026-10-07
- [x] 3. Extract the shared agent core so every AI job runs on it @agent #agent ✓ 2026-10-05
- [x] 2. Move the cash floor, reminder days and alert minimum into the company rulebook @agent #rulebook ✓ 2026-10-05
- [x] 1. Open the forecast on the money that is in the bank, not on the booked balance @edmir #liquidity ✓ 2026-10-04
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