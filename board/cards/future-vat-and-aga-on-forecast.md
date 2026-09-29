---
title: Put future VAT and arbeidsgiveravgift on the cashflow expected line
owner: @agent
milestone: #forecast
created: 2026-09-29
---
## Goal
The expected line credits `rates["revenue"] * 1.25` — VAT-inclusive cash — for invoicing that has not happened yet, 4 072 570 kr across the horizon, but never schedules the VAT back out. The only VAT leaving in the 13 weeks is the 905 542 already standing on 2700/2710 today.

The timing is the point. October's invoicing is collected 22 Dec (31 Oct + 45 credit days + 7 pay lag), while VAT on October's sales falls due 10 Dec, same termin as September. Money leaves before it arrives and the model has neither side, so the expected line overstates comfort in exactly the weeks that are already tightest. AGA accruing on future payroll has the same shape.

**Note.** Came out of the question about the 13-week forecast and the 45-day terms. The 45 days themselves are already handled correctly — credit_days is the measured median of 71 open invoices.

## Done when
- [ ] Future invoicing books its output VAT out on the termin due date
- [ ] AGA on future payroll is scheduled on its own term dates
- [ ] Both appear in `assumptions`, so the owner can see what is modelled
- [ ] The committed and expected lines stay internally consistent: no gross receipt without its liability
- [ ] A test pins the Oct-sales/10-Dec-VAT case

## Log
- 2026-09-29 (agent): created
