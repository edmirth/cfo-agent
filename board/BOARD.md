---

kanban-plugin: board

---

## Backlog

- [ ] 21. Add budget-vs-actual variance per line, with the cause named @agent #kpi
- [ ] 25. Propose a weekly payment run with its cash effect @edmir #liquidity
- [ ] 26. Let the agent propose company memory that the CEO approves @edmir #memory
- [ ] 27. Build a monthly financial pack on a cadence, with an archive @either #pack
- [ ] 29. Convert foreign-currency supplier invoices instead of taking them as kroner @edmir #liquidity
- [ ] 30. We need to make a database for the platform here, and also design the architecture of the database here so the agent can actually use it and also how to store the database here. We need to make a good database for the platform and also structure it.
- [ ] 31. Sync Tripletex and bank data into the database on a schedule @edmir #platform
- [ ] 32. Isolate each customer's data and keep a full audit log @edmir #platform
- [ ] 33. Move chat sessions from an in-process dict into a shared store @either #platform
- [ ] 34. Build an in-app screen to connect a customer's own accounting system @either #platform
- [ ] 35. Push urgent alerts to the CEO's phone @edmir #delivery
- [ ] 15. Hold the agent's output for human review while a customer is new (Wait until the first customer outside the pilot is onboarded) @either #review
- [ ] 38. give the project agent tool to use the web as well to get information. It could be for indusrey or other stuff.
- [ ] 39. Could autoresearch of ai agent be something that could help here for future fetaure so it could find stuff for the company and give it benefits or find something based on the data.
- [ ] 40. Add project mode to the cash engine for construction and painting @edmir #forecast
- [ ] 41. Flag suppliers with bankruptcy or dissolution notices too, where we have prepaid or depend on them @edmir #warnings
- [ ] 42. Send approved reminders through Tripletex after the CEO taps Send @edmir #actions
- [ ] 43. How could we design the ai agent to look at the numbers and then also the company and then understand their industry, and know then what type of CFO work it needs and how they operate in the sense of financials.
- [ ] 44. On the backend there is a seperate file that does the summary, isnt it better to just let the ai agent make it? so it also has the memory, and also writes the summary as well.
- [ ] 45. Could the frontpage use any AI, and if so, what type of work would that be?
- [ ] 47. Check payroll against contracts each month: hours, overtime and NAV sick-pay refunds @edmir #warnings
- [ ] 48. Draft next year's budget in October from actuals, contracts and pipeline @edmir #kpi
- [ ] 49. Ask Arvaka by replying to the Monday email or sending a voice note @edmir #delivery
- [ ] 54. Rotate the three keys shown in chat on 2026-10-25: Supabase service key (backups), CFO_BACKUP_KEY, Resend @edmir #platform
- [ ] 55. Run the tests on GitHub for every PR, and let Render deploy only when they pass @edmir #platform
- [ ] 56. Skip the Render deploy when a merge only changes the board or the docs @edmir #platform
- [ ] 61. A read-only page on the server that backtests each invoice run, predicted against sent, on the real books @edmir #forecast
- [ ] 62. Score the forecast every Monday against what came in and went out, part by part @edmir #forecast
- [ ] 65. Find one-offs and the costs that came with them (a big job and its extra wage run), and ask the owner in Saker whether they were one-offs @edmir #forecast
	  - Also from card 63: the owner says once what the bank lines with no category are, and it is remembered. Same question, same place in Saker.
- [ ] 66. Let the owner add known events ahead (a big job, a contract ending, a purchase) as their own lines in the forecast @edmir #forecast


## Next

- [ ] 10. Choose a PSD2 partner and read the balance from the bank (We wait until we have done the meeting with Neonomics and enable banking) @edmir #liquidity

- [ ] 69. Split cashflow.py into a typed package without changing a single number @either #forecast

- [ ] 70. Run the forecast on a per-company profile and data map instead of fixed constants @either #forecast

- [ ] 71. Let the AI write the data map on connect, checked against the books before it counts @either #forecast

- [ ] 72. Readiness levels, test companies and the onboarding questions for a new company @either #forecast


## Doing



## Done

- [x] 68. Stop paying AGA and VAT twice in the months a tax payment goes out @either #forecast ✓ 2026-11-13

- [x] 67. Give the cash forecast a test baseline: pytest in the venv, and snapshot tests of the full forecast @either #forecast ✓ 2026-11-13

- [x] 20. Build a daily collections list that flags repeat late payers @either #liquidity ✓ 2026-11-08
	  - Built 2026-11-08: each late customer against his own habit (uvanlig sen: ring; fast sen betaler: a reminder), two reminders and then the owner decides, and "Innkreving i dag" at the top of Saker. Card: board/cards/collections-process.md.
- [x] 19. Verify flags a figure written as "minus 845 481" as having no source, though −845 481 is in the facts @edmir #agent ✓ 2026-11-08
	  - Built 2026-11-08: a written minus ("minus", −, –) is read as a sign, and a figure is traced by its size, with a differing sign noted rather than flagged. Card: board/cards/verify-negative-figures.md.
- [x] 64. Build the money going out per stream from the bank lines (63), at the median month, with one-offs left out @edmir #forecast ✓ 2026-11-08
	  - Built 2026-11-08: the running costs from the bank lines at the median month, one-offs held out. Merged as #104. Card: board/cards/bank-costs.md.
- [x] 17. We only invoice with max 45 days, so most of the invoices go to 6 weeks ahead, so when we look at december we dont get the fully picture as the incvoices has not been sent out yet, and then it could look like we have a fall on the invooices around that time and low on cash, so we need to fix this, and maybe use like a average or try to predict what it could be around there. ✓ 2026-11-08
	  - Mostly solved by the cash-flow work (PRs #58, #60, #61): sales not yet invoiced are in the expected line with last year's season, the company's own invoice day and terms, and its customers' own lateness. Still open: a month whose sales are paid after week 13 is outside the window, so December looks light from October.
	  - #94 (2026-11-07): every customer billed each month counts in the committed line, and each week opens to show what is in it. Card: board/cards/invoicing-ahead.md. The rest of the card is card 60: the invoice runs at month end, from the invoice register.
	  - Built 2026-11-08: what is left was the edge of the window. The money in after week 13 from invoicing sent inside it is said under the chart, as the last row, and after a low point in the last weeks. Merged as #103. Card: board/cards/window-edge.md.
- [x] 63. Give every bank line a category (wages, taxes, VAT, loans, rent, suppliers, card, owner, customers): rules first, AI suggestions the owner approves once @edmir #forecast ✓ 2026-11-08
	  - #102: every bank line has a category by fixed rules; 96 % of the money going out over six months on the real books. The owner naming the unknown ones moved to card 65. Card: board/cards/bank-categories.md.
- [x] 60. Build the cash coming in from the invoice register: sent invoices, the next invoice runs per customer (own day, own 30/45-day terms, own lateness), and other invoicing; each run shown as one line @edmir #forecast ✓ 2026-11-08
	  - #97–#101: money coming in from the invoice register per customer, booked payments no longer taking open invoices, the pay day from the payroll vouchers, no jumps without a cause, and deadlines by the bank figure's date. Card: board/cards/invoice-runs.md.
- [x] 46. Based on the commintements.py, it uses the bankbalance and then subtracts everything owed. But we need to make sure that the bank balance that is used is actually correct, because we need the right answer/amount. ✓ 2026-11-08
	  - Checked 2026-11-08 against the Nordea statements through the Tripletex connector: the figure the forecast opens on is the balance on the bank statements. The booked balance is higher because payments in October are not booked yet.
- [x] 28. Page through a truncated invoice month instead of warning about it @edmir #liquidity ✓ 2026-11-08
	  - Done in PR #89: a full month is read page by page (`_month_rows`).
- [x] 23. Could we use AI to reason and be smart on which numbers and data to get from Tripletex for then to model the right type of 13 week cash brief, so that we could have the right numbers and smarter type of CFO work. ✓ 2026-11-08
	  - Answered by the plan in board/cards/smarter-cashflow.md: the engine reads the invoice register, the bank lines and the payroll vouchers; the AI suggests categories and one-offs and asks the owner (cards 63 and 65).
- [x] 24. Should we assign the ai agent to do the 13 week cash brief? could it be better at calculating it, and what tools would it need, should we give it coding tools so it could calculate it for us. ✓ 2026-11-08
	  - Answered by the same plan: the figures come from fixed, testable rules, and the AI explains and asks rather than calculates (cards 63 and 65).
- [x] 59. VAT, employer's contribution and withheld tax past their deadline count as paid, also on the settlement accounts, instead of being paid again at the next deadline @edmir #forecast ✓ 2026-11-08
- [x] 18. Say clearly when the Tripletex login has expired, and stop after one try @edmir #platform ✓ 2026-11-07
- [x] 58. Design the Monday email: Arvaka's brand, built to work as an email (phone, Outlook, dark mode) @edmir #delivery ✓ 2026-11-04
- [x] 11. Open and approve a card with one tap from the email (We need to wait until we have the server up and running and a web page so we can use it on the phone as well) @agent #delivery ✓ 2026-11-03
- [x] 37. Record Monday email opens and link taps for the metrics page, once there is a domain and the app is hosted @edmir #metrics ✓ 2026-11-01
- [x] 36. Link the Monday email to the full brief once the app is hosted somewhere a phone can reach @edmir #delivery ✓ 2026-10-30
- [x] 53. Send the Monday brief from cfo@arvaka.no: verify arvaka.no in Resend @edmir #delivery ✓ 2026-10-30
- [x] 50. Put arvaka.no live: booking link, contact email, approved pages, English versions @edmir #platform ✓ 2026-10-29
- [x] 52. Move the platform from the Mac to app.arvaka.no: a test run with a demo company, then the switch-over @edmir #platform ✓ 2026-10-26
- [x] 51. Make the platform deployable on Render: Tripletex login kept on the disk, pinned versions, Dockerfile, nightly backup @edmir #platform ✓ 2026-10-25
- [x] Make an "Mock Up" company, where we have their accountant data and use their numbers instead of using URT number, so that we can present the product without showing any confidential numbers. But we have all the numbers it needs so we can show the ability of the ai agent. ✓ 2026-10-24
	  - Demo mode (PRs #50, #51): Lindeskar, Kvarnheim and Aslefjord with whole generated books; ./demo.sh starts them on ports 8101–8103. Nothing in demo mode reaches the real ledger.
- [x] Lets add the new branding guidelines that we have made on to the frontend on our platform so we have the same style on it. ✓ 2026-10-24
	  - Arvaka redesign of frontend-react (PRs #44, #47): brand tokens, Newsreader and Geist, Arvaka in the copy, the Brief restructured.
- [x] 22. Make the 13 Week Cash brief stronger, and more accurate so that the user gets the right information it needs. Go on to the deep side of building it right, and the AI CFO Agent to understand it and build them. ✓ 2026-10-24
	  - PRs #52–#61: running costs with their VAT and this month's remainder, fixed bills in the committed line, costs spread by when they are paid, overdue invoices by age, unexplained receivables not counted on, seasons and trend, each customer's own lateness, and sales as the company invoices. Also #54: structured JSON output for the written jobs.
- [x] The daily summary is cut off for being too long (since 10 Oct), so the front page shows an old one @edmir #agent ✓ 2026-10-11
	  - Caps raised (summary and Monday brief 4 000, morning watch 8 000); a cut-off answer is now kept in job_runs.details. Live: today's summary written, 1 156 tokens.
- [x] 16. Flag customers with bankruptcy or dissolution notices from Brønnøysund @agent #warnings ✓ 2026-10-11
- [x] 14. Measure what the playbook says matters @agent #metrics ✓ 2026-10-10
- [x] 13. Produce the onboarding health check and the clean-up list for the regnskapsfører @agent #onboarding ✓ 2026-10-10
- [x] 12. Run a morning watch that raises and closes findings and cards unasked @agent #agent ✓ 2026-10-09
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