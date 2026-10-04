---
title: Open the forecast on the money that is in the bank, not on the booked balance
owner: @edmir
milestone: #liquidity
created: 2026-10-02
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
- [ ] The opening balance accounts for bank transactions that have landed but
      are not booked
- [ ] The adjustment is declared, with the date and the number of lines, never
      folded in silently
- [ ] A reconciliation that does not exist, or a period nobody has opened, reads
      as unknown rather than as zero unbooked
- [ ] A test pins the adjustment against a known gap

## Log
- 2026-10-02 (agent): raised after the owner said the brief showed less cash
  than the account held. A refresh was the first suspicion and was wrong — the
  app's figure ties to the ledger to the øre, so the lag is the books, not the
  cache. See [[receivables-gap]] for the same shape of problem on account 1500,
  where the ledger is the authority and the invoice list the one that lags.
- 2026-10-04 (agent): part of the playbook MVP ("real cash comes from the bank, not the ledger"). Interim step before [[psd2-bank]]. Moved to Next.
