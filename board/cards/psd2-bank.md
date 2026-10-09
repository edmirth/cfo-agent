---
title: Choose a PSD2 partner and read the balance from the bank
owner: @edmir
milestone: #liquidity
created: 2026-10-04
priority: 10
---
## Goal
"Bank data is the harder part. Real cash comes from the bank, not the ledger." The bank aggregator is in the playbook's MVP. [[bank-behind-ledger]] is the interim fix; this is the real one. Open question from the playbook: own licence or partner (Neonomics, Tink, Enable Banking), price per connection, timeline.

## Done when
- [ ] Partner or licence chosen, with price per connection and contract terms known
- [ ] Balances and transactions are read daily for a connected company
- [ ] The forecast opens on the bank's own balance, with any gap to the ledger declared

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 10 in Next: a business decision with a long lead time, so talks should start now even though the code comes later.
- 2026-10-09 (agent): planned with @edmir. What exists: the forecast already opens on the bank's own balance, read indirectly from Tripletex's bank reconciliation (`bankgap.py`, card 1), and says when that feed stops; `bank_balances.source` already allows `psd2`. What PSD2 adds: the balance from the bank itself, at any hour, independent of the bookkeeping and of Tripletex's feed, and for customers whose bank is not connected to Tripletex. Partners compared: Neonomics (Norwegian, licensed by Finanstilsynet; priced per successful data fetch), Enable Banking (Finnish, ERP and accounting focus; volume-priced with a monthly minimum; a "restricted mode" that runs a production app on your own linked accounts before any contract), Tink (Visa; sales-led, from about EUR 0.50 per user per month), GoCardless/Nordigen (closed to new sign-ups since July 2025, out). Own AISP licence: not worth it now; all partners let us work under theirs.
- 2026-10-09 (agent): decided by @edmir. The company banks with **Nordea** (business account; Enable Banking lists it as "Nordea" for Nordea Business), and @edmir has access to its online bank. Start with **Enable Banking in restricted mode** on the company's own account, at no contract cost, to build and test; the final partner is chosen once both have quoted. Condition from @edmir: no risk to the account. Answer: account information (AIS) only, read-only; no payment consent is ever requested; the consent is granted with BankID, expires by itself (about 180 days) and can be withdrawn in Nordea's online bank; the remaining risk is data exposure, so the app key stays in `.env`, behind the login.
- 2026-10-09 (agent): price and terms requests drafted for @edmir to send: to Neonomics (Norwegian) and to Enable Banking (English, info@enablebanking.com). Both ask for price per connected company per month, the minimum, contract length, coverage of Norwegian business accounts (Nordea Business, DNB, SpareBank 1) and consent length, working under their licence (KYB), the DPA and where data is stored, and test access before a contract. Next: @edmir sends the emails and creates the Enable Banking account; then the build (daily balance and transactions as `psd2`, the forecast on the bank's figure with the gap to the ledger declared, a warning before the consent expires) can start.
- 2026-10-09 (agent): paused by @edmir until after a meeting with **Neonomics on Monday 12 October**. Where it stopped: registering the Enable Banking production application, which requires a public privacy URL and terms URL; with no website or domain yet, nothing was published and the registration was not completed, so no key exists. Redirect URL chosen if it resumes: `http://localhost:8000/bank/callback` (a page of its own, so the bank's `?code=` does not collide with the Supabase login's). Picks up after the meeting with the partner choice.
