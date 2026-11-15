---
title: Run the forecast on a per-company profile and data map instead of fixed constants
owner: @either
milestone: #forecast
created: 2026-11-13
---
## Goal
Card 70, phase 3 of `docs/cashflow-spec.md`: a plug-and-play cash-flow forecast
that works for any company that connects, in a smaller, typed and tested module. Read the
spec first; its principle holds for every phase: the AI chooses the data (the data map),
code fetches and calculates every krone.

Based on `main`, never stacked. The snapshot tests from card 67 stay green, and any number
that changes on purpose is updated in its own commit with the reason.

## What it does
Today `backend/cashflow` has 52 fixed constants and about 60 hard-coded account numbers,
tuned on a cleaning company. Card 70 replaces them with a profile per company. Every value
the forecast uses is resolved in this order, and keeps its source:

1. `company.md`: stated by the owner or bookkeeper (`stated`)
2. the data map, checked against the books (`verified`); hand-written here, the AI's in card 71
3. measured from the ledger by code (`measured`)
4. today's value (`default`)

The data map (`state/data_map.json`) says where the numbers are and what they mean (account
roles, VAT rate per revenue account, fixed suppliers, one-off months), never the amounts.

| Today | After card 70 |
|---|---|
| 25 % VAT on all sales | The rate per revenue account, measured from postings (`vatPercentage`) |
| Input VAT share from today's 2700/2710 balances, capped at 50 % | Measured over the last closed term, no cap; fixes Ullensaker's 0.4 % |
| VAT due every two months | The company's real term: bi-monthly, yearly, primary industry |
| One pay day a month | Pay frequency and day from the payroll vouchers |
| 5 000 / 1 000 / 50 000 kr thresholds | Fractions of the company's own monthly revenue or costs |
| Fixed account ranges (1500-1509, 2400, 3000-3999, ...) | Account roles from the data map, NS 4102 as the default |

Not in this card: the AI (71), the onboarding screen and test companies (72), other sources.

## Plan: five PRs, each against the snapshots
1. **Profile, no change.** `Resolved` and `profile.py`; every constant read through the
   profile with today's values as defaults. Output byte-identical, demo and Ullensaker.
2. **Data map format and account roles.** JSON schema, loader, validation; the hard-coded
   ranges become roles. The roles and the VAT term are shared with `commitments.py`, which
   dates the tax balances, so the two cannot disagree. Identical output without a map.
3. **A hand-written data map end to end,** for Aslefjord (the wholesaler, furthest from a
   cleaning company); one for Ullensaker kept in `state/` only.
4. **Measured values, one commit each, snapshots updated and explained:** (a) output VAT rate
   per revenue account; (b) input VAT share over the last closed term, uncapped; (c) VAT term
   from when settlements happen or `company.md`; (d) pay frequency and day from the vouchers;
   (e) thresholds relative to scale; (f) lateness and spread where history allows.
5. **Reporting.** The assumptions carry each value's source; the briefing names what is
   assumed and asks the owner to confirm it.

Risks: touching `commitments.py` widens the card; step 4 moves numbers on purpose, Ullensaker's
too (expected VAT out goes down once the input share is read properly); about card 69's size.

## Decisions (@edmir, 2026-11-15)
1. **The owner's answers go into the company's own `company.md`.** Read from it and written
   back to it, as today.
2. **The system runs the data map, not the user.** No approval step. The guardrails are
   automatic: only entries the books confirm are applied; one they contradict, or that cannot
   be checked, is not applied and the measured or default value stays. Every version is kept
   with what changed and why, so it can be rolled back and every number traced, and the
   briefing says when the map changed something. Built in card 71; card 70's format carries a
   version and the check result per entry. Card 72's owner questions become optional
   information, not a step the owner must take.
3. **One deployment serves many companies, each logging in to its own.** That switch is
   card 32 (tenant isolation): per-company login, Tripletex login, `company.md`, caches. Card 70
   keys everything new by company from the start (the profile resolved for a company, the data
   map stored per company, no new global cache), so card 32 only supplies which company a
   request is for.
4. **Card 70 may extend into `commitments.py`:** step 2 puts the VAT and AGA terms and the
   account roles in one place both read.

## Done when
- [x] `Resolved` and `profile.py`. Every former constant resolves through it (step 1; the
      account ranges become roles in step 2)
- [x] Data map schema defined. `sources.py` fetches by the map, and a missing map gives the NS 4102
      defaults with snapshots unchanged (step 2: `datamap.py`, `chart.py`; the tax and payroll
      postings are fetched by role; the bank range stays locked until bankgap and bankcat take
      the company's chart)
- [ ] A hand-written data map for the demo company drives the forecast end to end, before any AI
      is involved
- [ ] Measured: effective output VAT rate, uncapped input share, VAT term, pay frequency and day,
      thresholds relative to scale, payment-lag parameters
- [ ] Assumptions block and briefing report each value's source
- [ ] Snapshots differ only where a measured value replaces a default, and each difference is
      explained

## Log
- 2026-11-13 (claude): created from the spec on @edmir's request
- 2026-11-15 (claude): plan written above, claimed, step 1 on
  `cashflow-data-map-profile`. Open decisions 1-4 not answered yet; step 1
  does not depend on them.
  - `cashflow/profile.py`: `Resolved` (value, source, note), `Profile` (a
    frozen dataclass of the 35 company parameters at today's values, and
    `sources`), `DEFAULT`, and `resolve()`: company.md first (ferie_uker,
    which the code already read), then the defaults. The data map and the
    measurements join in steps 2 and 4.
  - Threaded by a script from the syntax tree: each constant became
    `p.<field>`, 45 functions take `p: Profile = DEFAULT`, calls between
    them pass `p=p`, and `build` resolves the profile once. The three that
    read company.md resolve it themselves when called without one, as
    before. The 1 000 kr reconciliation gaps and the 0.5 VAT cap, literals
    the script could not see, are profile fields too. The old constants are
    gone; their reasoning moved into profile.py beside the fields.
  - Caught on the way: `payroll_paid` used `p` as its loop variable over
    postings, which would have shadowed the profile after the loop (mypy
    flagged it). Renamed there and in four comprehensions.
  - The briefing (narrative.py) reads `DEFAULT` until step 5, when it reads
    the forecast's own values.
  - 610 passed (4 new for the profile); ruff and mypy clean; the demo
    snapshots and Ullensaker byte-identical.


- 2026-11-15 (claude): step 2 on `cashflow-data-map-profile` (2a, 2b).
  - `backend/chart.py`: the account roles and the VAT and AGA terms, the
    standard chart as default; `for_company()` lays the data map's verified
    roles over it. `backend/datamap.py`: schema 1, validation with a reason
    per entry left out, loading per company from
    `state/data_maps/<company id>.json`; only `verified` entries count.
  - The forecast reads every range and term from `p.chart`; the commitments
    build their groups and term deadlines from the company's chart and pass
    it down. Old names (GROUPS, TERM_DUE, MVA_TERMS, SKATT_TERMS) remain as
    the default chart's. bankgap's bank range comes from the chart default.
  - Locked for now: the bank role, because bankgap and bankcat read it and
    do not take the company's chart. For a later step or card 32.
  - Fixed on the way: `term_due` read a term as its two named months, so a
    yearly VAT term covered only January and December. Now a range; every
    existing two-month term gives the same dates. Step 4c needs it.
  - `_settled` used `p` for each posting (as `payroll_paid` did); renamed.
  - Not per company yet, left for card 32: `sources._payroll_cache` is
    keyed by day only.
  - 618 passed (8 new); ruff and mypy clean; the demo snapshots and
    Ullensaker unchanged.

