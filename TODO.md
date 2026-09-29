# To do

The task list lives on the board now: `board/BOARD.md`, with the detail behind
each card in `board/cards/`. What stays here is what a board column cannot
hold — what we are for, and the scope decisions we have already made and should
not relitigate.

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

## Decisions already made

- **Cash-moving dates only.** MVA and AGA leave the account on known dates and
  belong in the forecast. The filing calendar — a-melding, skattemeldingen,
  årsregnskap — does *not*: that is the accountant's, and we removed it
  deliberately.
- **Read-only is enforced, not asked for.** The Tripletex toolset is declared
  closed and opened tool by tool from the allowlist in `backend/toolset.py`.
  This was a lane of its own until it was built; it is now a property of the
  system and `/api/toolset` audits it against the live server.

## Where the lanes stand

- **Lane 1, liquidity** — the strongest part of the product. `commitments.py`,
  `cashflow.py`.
- **Lane 2, KPIs and budget** — half built. `industry.py` tracks against
  industry norms, `overview.py` has revenue and result vs budget.
- **Lane 3, monthly pack** — not built. It can write a brief when asked; there
  is no pack.
- **Lane 4, early warnings** — half built. `preflight.py` warns and `memory.py`
  ages findings, but nothing is early because nothing runs unasked.
- **Lane 5, decision support** — thin. The `afford` preset and the Python
  sandbox.
