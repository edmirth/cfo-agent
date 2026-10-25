---
title: Check payroll against contracts each month: hours, overtime and NAV sick-pay refunds
owner: @edmir
milestone: #warnings
created: 2026-10-24
---
## Goal
arvaka.no promises it under «Dette får du»: a monthly payroll check, «Timer mot kontrakter, uvanlig overtid, manglende sykepengerefusjon fra NAV», answered with Bekreft. Nothing builds it yet. Payroll is read today only as a cost and as FTE (card «Use FTE from Tripletex»); individual payslips are closed off in `backend/toolset.py` on purpose, and this card must keep it that way.

## Done when
- [ ] Hours registered per contract or project are set against what the contract covers, each month
- [ ] Overtime well above a contract's usual level is raised as a card
- [ ] Sick pay paid beyond the employer period with no matching NAV refund booked is flagged, from the accounts, without reading anyone's absence or pay
- [ ] Individual pay is still never read or shown

## Log
- 2026-10-24 (agent): created from the landing page, which promises it. Open for @edmir: where «what the contract covers» comes from (Tripletex projects, the company description, or a new setting), and whether flagging sick pay from the accounts alone is enough.
