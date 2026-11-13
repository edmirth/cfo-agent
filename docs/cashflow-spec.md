# Spec: a plug-and-play cash-flow forecast

Status: draft · Owner: @edmir · Created 2026-11-13

## 1. Why

`backend/cashflow.py` produces the 13-week forecast, the main thing the product delivers. It works,
but it was tuned on the first customer:

- **It does not carry over to the next company unchanged.** Several assumptions are fixed
  (25 % VAT on all sales, input VAT capped at 50 % "for a cleaning company", krone thresholds
  such as 5 000 / 1 000 / 50 000, one monthly pay day). They are right for one cleaning
  company and wrong for a retailer, a restaurant or a consultancy.
- **It finds its data by fixed account ranges and heuristics.** A chart of accounts that departs
  from NS 4102, or a one-off month the median filter cannot explain, silently changes the
  numbers.
- **It is too large to change safely.** It is 2 826 lines, `build()` alone is 657 and
  `briefing()` is 383. Around 810 lines are comments, many of them stories of past bugs. One
  confirmed bug (§3) survived because the logic is hard to follow.

**Goal:** a company connects to Tripletex and gets a correct, explained forecast with no code
changes. The module is smaller, typed and tested, and does at least everything it does today.

## 2. Non-goals

- Replacing Tripletex as the data source. Other accounting systems are a separate card
  (`connect-own-accounting-system`).
- Letting a model produce forecast numbers. The forecast stays deterministic and reproducible,
  because `forecasts.record` / `scoring.score` grade it against the bank afterwards.
- Changing the output shape the frontend, `brief.py`, `cards.py` and the email depend on, except
  where a phase says so explicitly.

## 3. Known defects to fix first

**D1. AGA and VAT counted twice in the months a tax payment goes out.**
`aga_booked` (`cashflow.py:1750`) and `booked_vat` (`:1799`) take the current month's *net*
movement on 2770 / 2700–2739 as "already accrued this month". In a payment month the net movement
is accrual minus last term's payment, usually positive, so `max(0, -x)` gives 0:
- AGA: this month's AGA is added again as `aga_future` although it is already in the 2770 balance
  commitments dates. That is one month of AGA too much in every odd month after payroll is posted.
- VAT, accounts path (`from_register` false): this month's VAT is charged a second time in
  settlement months.

Fix (card 68, done): take this month's payment and settlement vouchers, found in its postings,
off the month's movement. Plain credits would also drop input VAT and credit notes.

**Check while refactoring (not confirmed):**
- `issued["this_month"]` sums `amount`, while the open list is `amountOutstanding`. If `amount`
  excludes VAT, the `max()` at `:1819` compares net with gross.
- `_sales_rows` drops a partly credited invoice and its negative credit note together, so the
  balance left between them disappears from the invoicing history.
- `payroll_paid`: a run on the 30th/31st booked on the 1st is counted as an extra run of the next
  month.
- The `_register_months` docstring says it stops at the first empty month. The code counts every
  month that has invoicing.

## 4. Design

### 4.1 Principle: the AI chooses the data, code fetches and calculates

The AI decides **which data is the right data**: which accounts, suppliers, customers, months and
bank lines count, and as what. It hands this over as a **data map** (§4.3), never as numbers.
Code checks the map against the books, then fetches the exact amounts from Tripletex and
calculates.

The AI never passes kroner to the calculation. A model copying or summing hundreds of invoices
can drop a row, round, or produce a plausible figure that is wrong, and can give a different
answer on a second run. Through the map, the AI's judgement decides what goes in, while every
krone comes straight from the ledger.

| Concern | Who | Why |
|---|---|---|
| What an account, supplier, customer, month or bank line *is* | AI, in the data map | Judgement, needs context such as voucher text and the industry |
| Whether each claim in the map holds | Code (verification) | Must be checkable against the numbers |
| Fetching the amounts the map points to | Code (`sources.py`) | Exact, complete, repeatable |
| Every krone in the forecast | Code | Reproducible, scorable, cheap |

The forecast build never calls a model. It reads the stored, verified data map.

### 4.2 Company profile and resolver

The **profile** is what the forecast runs on: the verified data map (§4.3) plus every parameter
the calculation needs. Every entry resolves in this order and records its source:

1. **`company.md`**: stated by the owner or bookkeeper
2. **Data map, verified**: the AI's claim, confirmed by the data
3. **Measured**: read from the ledger by code alone
4. **Default**: today's constants (NS 4102 account ranges, the current thresholds)

```python
@dataclass(frozen=True)
class Resolved(Generic[T]):
    value: T
    source: Literal["stated", "verified", "measured", "default"]
    note: str | None = None
```

The profile is stored at `state/cashflow_profile.json` with a version and the date it was made.
The briefing and the assumptions block report each value's source, which generalises what
`credit_source`, `"antatt"` and `kilde` already do.

**Values that become measured or profiled instead of fixed:**

| Today | Becomes |
|---|---|
| `MVA_RATE = 0.25` on all sales | Effective output VAT rate per revenue account, from 2700 against 3000–3999 and the VAT codes |
| Input VAT share capped at 0.5 | Measured share, bounded by the company's own history |
| `MVA_TERMS` every two months | VAT term from the profile (bi-monthly, yearly, primary industry) |
| One monthly pay day | Pay frequency and day from the payroll vouchers |
| `BEHIND_MIN`, residual `> 1000`, `VAT_RATIO_MIN` | Fractions of the company's median monthly revenue or costs |
| `LATE_DAYS`, `SLOW_WEEKS`, `LATE_SPREAD_WEEKS`, `PAY_LAG_DAYS` | Measured from the company's own payment history where there is enough of it; today's values as defaults |
| Fixed account ranges (1500–1509, 2400–2409, 2700–2739, 2770–2779, 5000–5099, `OPEX_RANGES`) | Account roles from the data map, with NS 4102 as the default |

### 4.3 AI discovery and the data map

A separate module, `backend/discovery/`. Its only product is the **data map**: a description of
where the right numbers are and what they mean, with no amounts the calculation will use.

**Example** (abridged):

```json
{
  "version": 3, "made": "2026-11-13", "model": "claude-opus-5-5", "prompt": "discovery-v1",
  "accounts": {
    "receivables": {"accounts": [1500, 1530], "why": "1530 holds factoring receivables"},
    "payables":    {"accounts": [2400]},
    "output_vat":  {"accounts": [2700, 2702]},
    "aga":         {"accounts": [2770]}
  },
  "revenue": [
    {"account": 3000, "vat_rate": 0.25},
    {"account": 3100, "vat_rate": 0.15, "why": "food sales"}
  ],
  "vat_term": "bimonthly",
  "payroll": {"frequency": "monthly", "day": 20},
  "fixed_suppliers": [
    {"supplier_id": 812, "name": "Eiendom AS", "kind": "rent"},
    {"supplier_id": 455, "name": "DNB", "kind": "loan"}
  ],
  "contract_customers": [{"customer_id": 1021, "name": "Lindeskar AS"}],
  "related_parties": [{"customer_id": 1188, "name": "Holding AS", "kind": "owner"}],
  "exclude_months": [
    {"series": "revenue", "month": "2026-03", "kind": "one_off",
     "why": "machine sale on voucher 4471"}
  ],
  "bank_rules": [{"match": "SKATTEETATEN", "kind": "tax"}]
}
```

Claims point to records by their Tripletex IDs, so code can fetch exactly what they name.
Figures in a `why` are explanation for the owner only, never input to the calculation.

**How the map drives the calculation.** `sources.py` reads the map to decide what to fetch: the
receivables are the balance on the mapped receivables accounts, the fixed bills are the mapped
suppliers' bills, and the excluded months are left out of the run rates. Where the map has no
entry, or an entry failed verification, the default for that entry is used and declared.

It runs:
- when a company connects;
- when code detects drift: a new account in use, a new large supplier or customer, a VAT ratio or
  payroll pattern that moves outside its band;
- on demand from the admin.

**Input:** the chart of accounts and trial balance (12 months), a sample of customer invoices,
supplier bills and bank lines with voucher text, the Brønnøysund entry (industry code, VAT
registration, employees), and the `company.md` prose.

**Output:** the data map, validated against a JSON schema, covering:
- **account roles:** bank, receivables, payables, output and input VAT, AGA, payroll, owner, loans
- **VAT:** rate per revenue account, term
- **payroll:** frequency and pay day
- **suppliers:** fixed or variable, with a reason (rent, leasing, loan, insurance, software)
- **customers:** contract, related party or owner, public sector
- **months:** one-offs and backlog months, each with a reason
- **bank lines:** tax, loans, transfers between own accounts, owner withdrawals

**Verification** is code, one check per claim, for example:
- VAT rate vs the measured 2700/3xxx ratio, within tolerance
- a fixed supplier vs its bill history
- the pay day vs the voucher dates
- an account role vs the sign and size of its balance

Each claim ends up *verified*, *contradicted* (the measured value wins and the question goes to
the owner) or *unverifiable* (it goes to the owner). An unverified claim never moves a number.

The map is stored at `state/data_map.json`, with each claim's verification result and the model
and prompt version that produced it. A new map replaces the old one only after verification. The
previous version is kept, so a change in the forecast can be traced to a change in the map.

**Models:** Opus 5.5 (`claude-opus-5-5`) for discovery, which is rare and needs judgement.
Sonnet 5.5 (`claude-sonnet-5-5`) for bulk classification such as bank lines.

**First use: `bankcat.py`.** It is self-contained, rule-based today, and already measures
`unknown_share_out`, so the gain can be measured before and after.

### 4.4 Readiness levels

Detected once, in one place, instead of fallbacks spread through `build()`. Each level picks a
tested path and the briefing says which.

| Situation | Path |
|---|---|
| Fewer than `RUN_MIN_MONTHS` of invoicing | Revenue from the accounts, not the register |
| No employees | No payroll or AGA lines |
| Not VAT-registered | No VAT lines |
| No bank reconciliation in Tripletex | Booked balance as the opening, declared |
| Foreign-currency invoices | At face value, declared (as today) |
| Profile missing or stale | Defaults, declared, and discovery queued |

### 4.5 Onboarding report

The first build for a new company lists what was stated, verified, measured and assumed, with
questions the owner can answer in the app ("Is Lindeskar AS on a monthly contract?"). Answers are
written to `company.md` and become *stated*.

### 4.6 Module structure

`backend/cashflow/` as a package, each module under about 300 lines and with one job:

| Module | Contents |
|---|---|
| `models.py` | `Flow`, `FlowKind` (enum), `Line` (committed/expected), `Week`, `Forecast`, `Resolved` |
| `sources.py` | Every Tripletex read (invoices, postings, trial balance, commitments), fetched once in parallel and selected by the data map. The only module that does I/O |
| `profile.py` | The resolver: loads the verified data map and resolves every parameter (§4.2) |
| `receivables.py` | Open invoices, when they are paid, ageing, doubtful ones |
| `payables.py` | Open bills |
| `invoicing.py` | Contract customers and other invoicing not yet sent |
| `costs.py` | Fixed bills, the cost profile, bank-based costs |
| `tax.py` | VAT, AGA, statutory dates from commitments |
| `payroll.py` | Pay days, runs, measured pay per run |
| `reconcile.py` | Ledger vs register (1500, 2400) and the bank gap |
| `assemble.py` | Week buckets, the two lines, low points, the money after week 13 |
| `briefing.py` | The prose block for the agent |
| `texts.py` | Every user-facing Norwegian sentence |
| `__init__.py` | Public API: `build`, `cached`, `briefing`, `rules`, `below_floor`, `at_edge`, `after_text` |

`build()` becomes a short pipeline:

```python
async def build(today: date | None = None) -> dict:
    today = today or date.today()
    data_map = profile_mod.load_map()           # verified; never calls a model
    data = await sources.fetch(today, data_map)
    profile = profile_mod.resolve(data, data_map, today)
    flows = [
        *receivables.schedule(data, profile, today),
        *payables.schedule(data, profile, today),
        *invoicing.schedule(data, profile, today),
        *costs.schedule(data, profile, today),
        *tax.schedule(data, profile, today),
        *payroll.schedule(data, profile, today),
        *reconcile.residuals(data, profile, today),
    ]
    forecast = assemble.forecast(today, data.opening, flows, profile)
    record_and_score(forecast, data, today)
    return forecast.to_dict()
```

### 4.7 Coding standards for the package

- **Pure functions over typed data.** Only `sources.py` awaits anything. Everything else takes
  data in and returns data, so it is testable without mocks.
- **One `Flow` type.** The roughly 20 `kind` strings become a `FlowKind` enum that knows its line
  (committed/expected) and whether it counts after week 13, replacing `AFTER_KINDS` and the
  scattered `kind ==` checks.
- **Shared helpers instead of repetition:** month arithmetic (`_add_months`, `_month_bounds` and
  four hand-written month loops), "parse date or skip" (about 8 copies), "a liability is a credit
  balance, so negate it" (5 copies), and one parser for supplier rows instead of two
  (`_bill_rows` / `_fixed_bills`).
- **No constants at module top.** They become profile defaults with names and units.
- **Comments say why, not history.** The reasoning a reader needs stays. Incident stories move to
  git history and this spec.
- **English identifiers, Norwegian text only in `texts.py`.** Output keys stay as they are for
  compatibility (§2). A later, coordinated change can rename them.
- **Functions under about 60 lines. Type hints throughout. `ruff` and `mypy`** on the package
  in CI.
- **Tests exercise the public module functions, not private helpers,** so internals can change
  without rewriting the tests.

## 5. Phases

Each phase is its own card and branch, with a PR based on `main` (never stacked). The snapshot
tests from phase 0 must stay green in every phase. Where a phase changes numbers on purpose, the
snapshot is updated in its own commit with the reason.

### Phase 0: baseline
- [x] Tests run green before any change. The plain runner (`python -m tests.run`) stays;
      pytest added beside it through `requirements-dev.txt`, `pytest.ini` and `tests/conftest.py`
- [x] Snapshot tests: the full `build()` output (weeks, flows, assumptions, warnings) and
      `briefing()` text for the three demo companies on three days each, saved and compared
      exactly (`tests/test_cashflow_snapshots.py`)
- [x] How to run the tests is documented in `README.md`

### Phase 1: fix D1
- [x] AGA and VAT "already this month" no longer count the month's payment or settlement: the
      month's movement less the payment and settlement vouchers found in its postings
      (`_settled`). Plain credits would also drop input VAT and credit notes, so not that
- [x] Regression tests for a payment month: November with the run journalised before its pay
      day, November with it not yet journalised, and October with a VAT settlement
- [x] Snapshots: nothing moved, on the demo companies or Ullensaker. Neither books hits the
      case (see the log), so no snapshot commit was needed

### Phase 2: split without changing behaviour
- [ ] `backend/cashflow/` package as in §4.6. `import cashflow` and the public API unchanged
- [ ] `models.py` with `Flow` and `FlowKind`. `texts.py` holds every user sentence
- [ ] Shared helpers replace the duplicates listed in §4.7
- [ ] Tests moved off private functions and module patching (`cashflow.mcp`,
      `cashflow.commitments`) onto `sources` fakes and the public functions
- [ ] `ruff` and `mypy` clean on the package. No function over about 60 lines
- [ ] Snapshots byte-identical

### Phase 3: profile and resolver
- [ ] `Resolved` and `profile.py`. Every former constant resolves through it
- [ ] Data map schema defined. `sources.py` fetches by the map, and a missing map gives the NS 4102
      defaults with snapshots unchanged
- [ ] A hand-written data map for the demo company drives the forecast end to end, before any AI
      is involved
- [ ] Measured: effective output VAT rate, uncapped input share, VAT term, pay frequency and day,
      thresholds relative to scale, payment-lag parameters
- [ ] Assumptions block and briefing report each value's source
- [ ] Snapshots differ only where a measured value replaces a default, and each difference is
      explained

### Phase 4: AI discovery
- [ ] `backend/discovery/` produces the data map: prompt, schema validation, verification checks
      and drift triggers
- [ ] On the demo company, the AI's map matches the hand-written one from phase 3, or each
      difference is explained
- [ ] `bankcat` classification through discovery. `unknown_share_out` compared before and after on
      the demo company
- [ ] Account roles, fixed suppliers, contract customers and one-off months fed into the profile
      as *verified* or as questions
- [ ] The build never calls a model (enforced by a test)

### Phase 5: readiness, fixtures, onboarding
- [ ] Readiness levels in one place (§4.4), each with a test
- [ ] Fixture companies with a known correct profile: a retailer at 15 % VAT, a consultancy with no
      stock, a company with no staff, a seasonal business, a yearly VAT term, a company under
      3 months old. Each gives a sensible forecast and discovery finds its profile
- [ ] Onboarding report and questions in the app. Answers written to `company.md`

## 6. Risks

| Risk | Mitigation |
|---|---|
| The split silently changes numbers | Exact snapshots. No logic changes in phase 2 |
| Tests coupled to private names break wholesale | Move them in phase 2, area by area, before deleting the old names |
| The model mislabels data and moves numbers | Nothing unverified moves a number. A contradiction falls back to measured and asks the owner |
| The model's figures leak into the calculation | The map schema has no amount fields the calculation reads. Amounts only ever come from `sources.py` |
| Cost and latency of discovery | Runs rarely (connect, drift, on demand), never per build |
| Output key changes break the frontend, brief or cards | Keys frozen until a separate coordinated change |
| One company's profile leaks into another's | The profile lives in `state/` like `company.md`, which is already per deployment |

## 7. Open questions

1. Do fixture ledgers exist beyond `state-demo/`, or do they need to be built for phase 0?
2. Should owner answers be written into `company.md` (readable, editable) or a separate
   `profile_answers.json` (structured)?
3. The data map records the model, prompt version and date for each claim (§4.3). Should the
   human-review card also require a person to approve a new map before it replaces the old one?
4. Is a per-deployment state still the long-term model, or will one deployment serve several
   companies? A shared deployment changes where the profile and caches (`_payroll_cache`, `_flight`)
   must live.
