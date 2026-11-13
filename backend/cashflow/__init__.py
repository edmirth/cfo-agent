"""Thirteen weeks of cash, week by week.

The deliverable that defines the job. `commitments.py` answers "how much of
this is mine"; this answers the question underneath it — *will I make it to
Christmas, and which week is the tight one*. An owner who knows his low point
is in the week of 12 October can act in September. Told in November, he can
only apologise.

Two lines, never one:

- **Committed** — money already invoiced in or out, plus payroll and the tax
  dates that arrive whether or not anyone sells anything, plus the customers
  invoiced every month on what is plainly a contract — with the VAT and the
  running costs that come with serving them. This is the floor.
- **Expected** — committed plus the rest of continued trading: the invoicing
  that normally goes out each month beyond the contracts, collected on the
  terms this company's customers actually pay on, less its running costs.

Showing only the first makes a healthy company look dying; showing only the
second hides how much of the comfort is a forecast rather than a fact. A CFO
shows both and says which is which.

Everything modelled is declared in `assumptions` and shown to the owner in the
answer. Nothing here is a black box: he is being asked to make decisions on it.
"""
import freshness
# Reached through the package by the tests, as on the single module.
import bankcat  # noqa: F401
import brreg  # noqa: F401
import commitments  # noqa: F401

# Every name the single module had, so `cashflow.<name>` answers as before.
# The public ones are build, cached, briefing, rules, below_floor, at_edge
# and after_text; the rest are here for the tests until they move to the
# modules themselves.
from .common import (  # noqa: F401
    AGA_ACCRUED,
    BANK_UNKNOWN_MAX,
    COST_PERIODS,
    DOUBTFUL_DAYS,
    LATE_DAYS,
    LATE_SPREAD_WEEKS,
    LEVEL_MONTHS,
    MONTH_NAMES,
    MVA_RATE,
    OPEX_RANGES,
    PAID_FROM,
    PAYROLL_MONTHS,
    PAY_LAG_DAYS,
    RECURRING_MONTHS,
    RUN_ACTIVE,
    RUN_MONTHS,
    SEASON_WEIGHT,
    SLOW_WEEKS,
    TERM_STEPS,
    VAT_ACCRUED,
    WAGE_ACCOUNTS,
    WEEKS,
    _add_months,
    _kr,
    _monday,
    _month_bounds,
    _term_step,
    _weighted_median,
)
from .payables import (  # noqa: F401
    _payment_parts,
    _schedule_payments,
)
from .receivables import (  # noqa: F401
    _days_overdue,
    _expected_items,
    _receipt_parts,
    _schedule_receipts,
)
from .costs import (  # noqa: F401
    FIXED_LOOKBACK,
    FIXED_MIN,
    FIXED_TOLERANCE,
    PROFILE_MIN_BILLS,
    PROFILE_MIN_PERIOD_BILLS,
    PROFILE_WEIGHT_CAP,
    _bank_costs,
    _bill_rows,
    _cost_parts,
    _cost_profile,
    _fixed_bills,
    _profile,
)
from .invoicing import (  # noqa: F401
    BEHIND_MIN,
    BEHIND_SHARE,
    STALL_DAYS,
    UNUSUAL,
    _invoice_months,
    _invoice_runs,
    _other_invoicing,
    _place_month,
    _register_months,
    _run_parts,
    _sales_profile,
    _sales_rows,
)
from .ledger import (  # noqa: F401
    SEASON_LIMITS,
    _closing_or_none,
    _closing_range,
    _merged,
    _month_no,
    _run_rates,
    _seasons,
)
from .tax import (  # noqa: F401
    VAT_INPUT,
    VAT_OUTPUT,
    VAT_RATIO_MIN,
    VAT_SETTLEMENT,
    _settled,
    _vat_input_share,
)
from .payroll import (  # noqa: F401
    FERIE_WEEKS,
    PAYDAY_WINDOW,
    PAYROLL_MIN,
    VIRKEDAGER,
    _ferie_withheld,
    _pay_days,
    _payroll_runs,
    payroll_paid,
)
from .sources import (  # noqa: F401
    AR_MONTHS_BACK,
    INVOICE_PAGE,
    INVOICE_PAGES,
    PAYROLL_PAGES,
    _month_rows,
    _open_invoices,
    _payroll_cache,
    _payroll_measured,
    _postings_in,
    _tax_postings,
)
from .narrative import (  # noqa: F401
    EDGE_WEEKS,
    HALF_TAX_MONTH,
    _bank_cost_words,
    _floor_line,
    _opening_note,
    after_text,
    at_edge,
    below_floor,
    briefing,
    rules,
)
from .assemble import (  # noqa: F401
    AFTER_KINDS,
    _after_payload,
    _assemble,
    _bank_payload,
)
from .pipeline import (  # noqa: F401
    MIN_CLOSED_MONTHS,
    REGISTER_CHECK,
    RUN_MIN_MONTHS,
    STATUTORY_FROM_COMMITMENTS,
    build,
)


CACHE_SECONDS = 600


_flight = freshness.Cached(build, CACHE_SECONDS,
                           degraded=lambda d: bool(d.get("partial")))


async def cached() -> dict:
    return await _flight.get()
