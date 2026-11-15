"""The company's own settings for the forecast, and where each came from.

Every value the calculation would otherwise hard-code is resolved here, in
this order, and keeps its source:

1. `stated`   — company.md, written by the owner or the bookkeeper
2. `verified` — the data map, checked against the books (card 70 step 2 on)
3. `measured` — read off the ledger by code (step 4)
4. `default`  — the value the forecast has always used

The defaults are the forecast as it was tuned on its first customer, so a
company with nothing stated and nothing measured gets exactly that forecast.
The briefing says which values are assumed (step 5), because an assumption
the owner is not told about reads as a fact about his business.
"""
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields, replace
from typing import Any, Generic, Literal, TypeVar

import company

Source = Literal["stated", "verified", "measured", "default"]
T = TypeVar("T")


@dataclass(frozen=True)
class Resolved(Generic[T]):
    """One value, where it came from, and a word on why where that helps."""
    value: T
    source: Source
    note: str | None = None


@dataclass(frozen=True)
class Profile:
    """The forecast's parameters for one company. Read as plain values
    (`p.late_days`); `sources` says where each came from."""

    # VAT. Invoicing that has not happened yet brings in gross cash and creates
    # a liability on the same krone, and the liability leaves first: October's
    # VAT falls due 10 December while October's invoicing is collected around
    # 22 December. 25 % on every sale; the deduction share read off 2700
    # against 2710 and capped at half, which "for a cleaning company" would
    # mean a posting error. Both are card 70's to measure (step 4).
    vat_rate: float = 0.25
    # Below this the output-VAT balance is too small to read a ratio off,
    # which happens for a few days after every settlement clears both accounts.
    vat_ratio_min: float = 50_000.0
    vat_input_cap: float = 0.5

    # How late an overdue invoice is decides how far it is counted on. Up to
    # late_days is ordinary lateness: in both lines, over late_spread_weeks.
    # Up to doubtful_days it usually pays, but not reliably and not soon: in
    # the expected line only, over slow_weeks. Beyond that it is not counted
    # on at all — money that in practice comes back through debt collection or
    # not at all — and is named instead, so it is chased rather than forecast.
    late_days: int = 30
    doubtful_days: int = 90
    slow_weeks: tuple[int, int] = (3, 8)
    late_spread_weeks: int = 3
    pay_lag_days: int = 7               # customers pay this late even when not "late"

    # The invoice runs (card 60). Money coming in is read off the invoice
    # register, customer by customer: what the company invoices is what
    # reaches the bank, on each customer's own day and terms. Regular:
    # invoiced in run_active of the last run_months closed months, and in each
    # of the last recurring_months. Usual is the median of his months; the
    # committed line takes the lowest of the last recurring_months, because
    # the floor is where being wrong costs most.
    recurring_months: int = 3
    run_months: int = 6
    run_active: int = 5
    # The register is read this many closed months before it is trusted over
    # the revenue in the accounts; a younger book keeps the old reading.
    run_min_months: int = 3
    # A regular customer leaves the committed line, never the forecast, when
    # his invoicing is less sure: more than behind_min kroner and behind_share
    # of his usual month over late_days late, or his usual invoice days this
    # month stall_days past with nothing sent. Only a customer with more than
    # his usual month over late_days late is out of both lines.
    behind_min: float = 5_000.0
    behind_share: float = 0.25
    stall_days: int = 10
    # The rest of the invoicing is one stream at its median month; a month
    # above unusual × that median is a one-off (a big job), left out and named.
    unusual: float = 1.5

    # The fewest closed months a run rate may rest on; before April this year
    # has fewer, and the gap is made up from the end of last year. Sales and
    # running costs get last year's pattern, each month against the year's
    # average, held within season_limits and taken at season_weight since one
    # year is a thin basis; and a level from the last level_months closed
    # months with the season taken out, which carries the trend.
    min_closed_months: int = 3
    level_months: int = 6
    season_weight: float = 0.5
    season_limits: tuple[float, float] = (0.5, 1.5)

    # A supplier's bill is fixed, for the committed line, when billed in
    # fixed_min of the last fixed_lookback closed months (or fixed_min quarters
    # in a row), every amount within fixed_tolerance of the median. The rest
    # are spread over the month by cost_periods, as this company's bills are
    # dated and paid, once there are profile_min_bills to read.
    fixed_lookback: int = 4
    fixed_min: int = 3
    fixed_tolerance: float = 0.15
    cost_periods: tuple[tuple[int, int], ...] = ((1, 7), (8, 14), (15, 21), (22, 31))
    profile_min_bills: int = 10
    profile_weight_cap: float = 3
    profile_min_period_bills: int = 3
    # Above this share of the money out with no category, the bank's costs
    # leave too much out, and the accounts carry the forecast (card 64).
    bank_unknown_max: float = 0.10

    # Reconciliations: a gap smaller than this between ledger and register is noise.
    ar_residual_min: float = 1000.0
    ap_residual_min: float = 1000.0
    # Register and accounts compared on next month: further apart than this,
    # the forecast says so rather than choosing between them.
    register_check: float = 0.35

    # Payroll.
    ferie_weeks: int = 5                # ferieloven gives 4 + 1, most agreements give 5
    payroll_months: int = 6             # months of payroll vouchers measured
    payroll_min: int = 3                # measured before the vouchers are trusted
    payday_window: int = 3              # days either side of the pay day that are its run

    sources: Mapping[str, Resolved[Any]] = field(default_factory=dict, compare=False)

    def source(self, name: str) -> Source:
        r = self.sources.get(name)
        return r.source if r else "default"


DEFAULT = Profile()


def _ferie_weeks() -> Resolved[int] | None:
    """Holiday weeks from company.md, 0-10, as `_ferie_withheld` always read it."""
    stated = company.setting("ferie_uker")
    if stated is None or not 0 <= int(stated) <= 10:
        return None
    return Resolved(int(stated), "stated")


# What company.md can state, by the profile field it sets.
STATED: dict[str, Callable[[], Resolved[Any] | None]] = {
    "ferie_weeks": _ferie_weeks,
}


def resolve() -> Profile:
    """The profile for the company this deployment serves.

    Stated values first; the data map and the measurements come in later
    steps of card 70. A value nothing says anything about keeps its default,
    and is recorded as such."""
    found: dict[str, Resolved[Any]] = {}
    for name, read in STATED.items():
        r = read()
        if r is not None:
            found[name] = r
    defaults = {f.name: getattr(DEFAULT, f.name) for f in fields(Profile) if f.name != "sources"}
    sources = {name: found.get(name) or Resolved(value, "default")
               for name, value in defaults.items()}
    return replace(DEFAULT, **{name: r.value for name, r in found.items()}, sources=sources)
