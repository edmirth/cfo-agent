---
title: Open the forecast on the money that is in the bank, not on the booked balance
owner: @edmir
milestone: #liquidity
created: 2026-10-02
priority: 1
---
## Goal
The 13-week forecast opens on the closing balance of accounts 1900-1949 in
Saldobalanse — the *booked* bank balance. The bank itself is ahead of the books
whenever transactions have landed but not been posted, and the whole forecast
is shifted down by that difference: every week's balance, the low point, and
the answer to "will I make it".

Measured 2 October 2026: ledger 2 625 898,93 kr, nine unmatched bank lines dated
1 October worth +134 375,44 kr net (163 761,72 in, 29 386,28 out), so the real
balance was 2 760 274,37 kr. The forecast was understating the account by
134 375 kr, and the owner spotted it before the software did.

`get_unmatched_bank_transactions` is already in the toolset allowlist, so no
permission work is needed. Note the company has three bank accounts — 1920
Bedriftskonto, 1940 Bankinnskudd utland, 1950 Skattetrekk — and the tool needs
one named per call.

## Done when
- [x] The opening balance accounts for bank transactions that have landed but
      are not booked
- [x] The adjustment is declared, with the date and the number of lines, never
      folded in silently
- [x] A reconciliation that does not exist, or a period nobody has opened, reads
      as unknown rather than as zero unbooked
- [x] A test pins the adjustment against a known gap

## Log
- 2026-10-02 (agent): raised after the owner said the brief showed less cash
  than the account held. A refresh was the first suspicion and was wrong — the
  app's figure ties to the ledger to the øre, so the lag is the books, not the
  cache. See [[receivables-gap]] for the same shape of problem on account 1500,
  where the ledger is the authority and the invoice list the one that lags.
- 2026-10-04 (agent): part of the playbook MVP ("real cash comes from the bank, not the ledger"). Interim step before [[psd2-bank]]. Moved to Next.
- 2026-10-04 (agent): priority 1 in Next: the Monday brief is only trusted if its opening balance is right; it was 134 375 kr too low and the owner noticed first.
- 2026-10-04 (agent): **the 134 375 kr was October alone, and too small.** Read
  across every reconciliation period this year, bank movement less ledger
  movement on 1920 is zero Jan–Apr (clean), then May −9 949, Jul −6 272, Aug
  −21 251, **Sep +280 001** (107 unposted lines, mostly customer receipts on 30
  Sep), Oct +134 375. The bank is **376 904 kr** ahead: 3 002 803 kr, not the
  2 760 274 written above. Measured on movements, not on the unmatched lists,
  because the lists miss postings the user may not read and disagree with the
  identity in Jan (12 688) and Jul (21 829).
- 2026-10-04 (agent): **lifting the opening alone double counts.** 8 of the 10
  largest unposted receipts match an invoice still open in the register, which
  the forecast schedules as a future receipt. So the unbooked lines now settle
  the counterparty's open invoices (exact amount first, else oldest due first);
  live: 43 customer invoices / 672 745 kr and 2 supplier bills / 99 650 kr come
  off the schedules. The 1500/2400 reconciliations still compare the full
  register with the ledger, and `ar_open` for reminders is the settled list, so
  nobody is chased for an invoice the bank has already been paid.
- 2026-10-04 (agent): built in `backend/bankgap.py`, wired into
  `cashflow.build`, declared in the briefing and on the brief page;
  `tests/test_bankgap.py` pins the October figures. 191 tests pass.
  **Open before Done:** (1) confirm 3 002 803 kr against the bank app — if it
  disagrees, the old May/Jul lines are mismatches, not lag; (2) decide whether
  `commitments` (free money) moves to the bank figure too — it still opens on
  the books, so the two screens disagree by the adjustment; (3) name matching
  is by normalised counterparty name, which misses a payer who pays under
  another name (factoring: "Factor AS", "Riverty").

