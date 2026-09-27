# To do

## Scope

Five lanes are ours: **liquidity and cash management**, **KPIs and budget vs
actual**, **the monthly pack and board narrative**, **early warnings and
follow-up**, **decision support on pricing, hiring and financing**.

Four things are the accountant's and we do not build them: bookkeeping and
posting vouchers, VAT and payroll *reporting*, year-end accounts and tax
returns, and the statutory responsibility for the accounts being right.

The test when it is not obvious: **if it changes what the CEO should do this
week, it is ours; if it is a submission to an authority, it is theirs.** Reading
the bookkeeping and judging its quality stays ours — we cannot advise on figures
that have not been tied out — but fixing it never is.

---

## Platform

### Let customers connect their own accounting system

**A page in the app where the user adds their own API connection**, instead of
the credentials living in `.env` on our machine.

Today it is `scripts/oauth_login.py` — a one-time browser login run from a
terminal, writing `TRIPLETEX_CLIENT_ID` and `TRIPLETEX_REFRESH_TOKEN` into
`.env`. Fine for one company, impossible to sell. It needs to be a screen the
customer walks through, and the same screen is where the key goes in.

What it drags in with it:

- **Per-customer credentials.** One `.env` is one company, and `tlx_oauth.py`
  writes the rotated refresh token straight back into it.
- **Login on the app.** There is none. Connecting a customer's live ledger to
  an unauthenticated page is not shippable.
- **State is single-tenant.** `state/memory.json` and `state/profile.json` have
  no tenant in the path, nor does the `SESSIONS` dict in `main.py`.
- **Provider as a choice.** Fiken, PowerOffice and Visma are the other systems
  Norwegian SMBs use, even while Tripletex is the only one wired.
- **Detect capabilities at connect time.** Ullensaker books no hours and no
  projects, so job costing is unavailable there and available elsewhere. Find
  out on connection and stop promising what a given ledger cannot support.

### Make read-only real

`agent.py:194` attaches the whole Tripletex toolset, `send_invoice`,
`approve_month` and `create_employee` included. Nothing but a sentence in
`cfo.md` stops it writing. Since we have now said we never post anything, this
is a toolset allowlist, not a judgement call.

---

## Lane 1 — Liquidity and cash management

*Built: `commitments.py`, `cashflow.py`.* The strongest part of the product.

- **Fix the weekend and holiday shift.** Norwegian due dates landing on a
  Saturday, Sunday or holiday move to the next working day; we use the literal
  date. MVA 640 930 falls on Sat 10 Oct and AGA 199 990 on Sun 15 Nov — both
  are placed a week early, and the second moves the reported low point. This is
  wrong now, not merely missing.
- **Explain the receivables gap.** Open invoices sum to 940 926 against
  1 997 489 on account 1500, and every customer's ledger balance exceeds their
  invoice total by a different ratio. The residual is carried and declared,
  which is honest but not an answer.
- **Cash-moving dates only.** MVA and AGA leave the account on known dates and
  belong here. The filing calendar — a-melding, skattemeldingen, årsregnskap —
  does *not*: that is the accountant's, and we removed it deliberately.
- **Two payroll quirks that move cash**: half tax in December means a larger
  net payment; in the holiday month staff draw feriepenger instead of salary.
  The forecast assumes twelve identical months.
- **Collections as a process** — who is late, who is habitually late, what goes
  out today, with the chase drafted.

## Lane 2 — KPIs and budget vs actual

*Half built: `industry.py` tracks against industry norms, `overview.py` has
revenue and result vs budget.*

- **Line-by-line variance against their own budget**, with the cause named, not
  just the gap reported. Today the KPI targets come from industry norms rather
  than from the company's budget — both matter, and only one is wired.
- **A rolling reforecast** the agent owns and is measured on, building on the
  forecast scoring already in `memory.py`.
- **FTE, not headcount.** Two KPIs divide by 47 people, many part-time in this
  trade, judged against a full-time benchmark. Tripletex holds the employment
  percentages.

## Lane 3 — Monthly pack and board narrative

*Not built.* It can write a brief when asked; there is no pack.

- Define what is in it, produce it on a cadence, keep the archive so month
  three can refer to month two.
- Write it so it survives being handed to a board or a bank.

## Lane 4 — Early warnings and follow-up

*Half built: `preflight.py` warns, `memory.py` keeps findings open and ageing.*
Nothing is early, because nothing runs unasked.

- **A scheduler.** Everything in this lane is worth roughly half while the
  owner has to think to ask.
- **Checks the machine should not need to reason its way to**: withholding held
  back but not set aside (1950 went from 331 143 to zero while 2600 stayed at
  zero with payroll booked); accrual accounts that stop moving (2945 has sat at
  −986 108 since 1 January); duplicate supplier payments, changed supplier bank
  accounts, round-number invoices.

## Lane 5 — Decision support

*Thin. The `afford` preset and the Python sandbox.*

- **Pricing** needs cost-per-hour, which needs hours and projects — unavailable
  at Ullensaker, available at customers who track them. Tie this to capability
  detection above.
- **Financing.** Equity ratio is 8 % and nobody has raised it. What a bank will
  want to see, and whether a credit line is realistic.
- **The owner's own money** — how much can come out, as salary or dividend, and
  what each costs.
