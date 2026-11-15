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

# The modules, each importable as `cashflow.<module>`.
from . import (  # noqa: F401
    assemble, common, costs, declare, invoicing, ledger, models, narrative, payables,
    payroll, pipeline, receivables, reconcile, sources, tax, texts, trading,
)
# What the rest of the backend uses. Everything else belongs to its module.
from .narrative import after_text, at_edge, below_floor, briefing, rules  # noqa: F401
from .pipeline import build

CACHE_SECONDS = 600


_flight = freshness.Cached(build, CACHE_SECONDS,
                           degraded=lambda d: bool(d.get("partial")))


async def cached() -> dict:
    return await _flight.get()
