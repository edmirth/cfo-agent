"""Six months of trading that has not happened yet: the sales still to be
invoiced, the VAT on them, and the running costs, month by month."""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

import commitments
import workdays

from .common import MONTH_NAMES, MVA_RATE
from .costs import _cost_parts
from .models import Runs
from .common import _next_month


def _revenue_in(rates: dict, season: dict, month_no: int) -> float:
    return rates["revenue"] * ((season.get("revenue") or {}).get(month_no, 1.0))


def _opex_in(rates: dict, season: dict, month_no: int) -> float:
    return rates["opex"] * ((season.get("opex") or {}).get(month_no, 1.0))



@dataclass
class _Trading:
    """Everything the six months of trading ahead are read from."""
    today: date
    horizon: date
    rates: dict
    season: dict
    vat_share: float
    booked_vat: float
    invoiced_this_month: float
    runs: Runs
    sales_profile: dict
    sales_lag: int
    credit_days: int
    bank_costs: dict | None
    known_by_month: dict
    fixed_by_month: dict
    profile: dict
    opex_left: float


@dataclass
class _Month:
    """One month of trading ahead, as the three legs below need it."""
    start: date
    current: bool
    revenue: float
    opex: float
    gross: float = 0.0
    contract: float = 0.0
    tied: float = 0.0

    @property
    def name(self) -> str:
        return MONTH_NAMES[self.start.month - 1]


def _trading(t: _Trading, committed: list, expected: list) -> dict:
    """Six months of trading that has not happened yet: the sales still to
    be invoiced, the VAT on them, and the running costs. Returns what each
    month rests on, for the assumptions."""
    sales, costs, invoicing = [], [], []
    month = date(t.today.year, t.today.month, 1)
    for _ in range(6):
        m = _Month(start=month, current=(month.year, month.month) == (t.today.year, t.today.month),
                   revenue=_revenue_in(t.rates, t.season, month.month),
                   opex=_opex_in(t.rates, t.season, month.month))
        sales.append({"month": m.name, "amount": round(m.revenue, 2)})
        costs.append({"month": m.name, "amount": round(
            t.bank_costs["level"] if t.bank_costs else m.opex, 2)})
        row = _month_sales(t, m, expected)
        if row:
            invoicing.append(row)
        _month_vat(t, m, committed, expected)
        _month_costs(t, m, committed, expected)
        month = _next_month(month)
    return {"sales": sales, "costs": costs, "invoicing": invoicing}


def _month_sales(t: _Trading, m: _Month, expected: list) -> dict | None:
    """The month's invoicing still to be won, on the expected line. Sets the
    month's gross, its contract part and the share tied to the contracts.
    Returns the register's reading of the month, when it is the source.

    The contract customers' part of the month is in the committed line
    already, each on his own dates. The same share of the VAT and of the
    running costs moves with it: a contract costs materials and fuel to serve
    like any other sale, and a floor that took the money without the cost
    would stand higher than it is."""
    key = (m.start.year, m.start.month)
    run = t.runs.by_month.get(key, {"low": 0.0, "usual": 0.0})
    gross = m.revenue * (1 + MVA_RATE)
    if m.current:
        gross = max(0.0, gross - t.invoiced_this_month)
    m.contract = run["low"]
    row = None
    if t.runs.from_register:
        # Everything still to be invoiced, from the register: the regular
        # customers at their usual month and the rest at its median. Already
        # on the weeks; here only for the VAT and the share of the costs.
        other = t.runs.other_by_month.get(key, 0.0)
        gross = run["usual"] + other
        row = {"month": m.name,
               "fast_lavest": round(run["low"], 2), "fast_vanlig": round(run["usual"], 2),
               "annen": round(other, 2), "regnskapet": round(m.revenue * (1 + MVA_RATE), 2)}
    m.tied = min(1.0, m.contract / gross) if gross > 0 else (1.0 if m.contract else 0.0)
    m.gross = max(0.0, gross - m.contract)
    for landing, share, days in _sales_landing(t, m):
        amount = m.gross * share
        if t.today <= landing < t.horizon and round(amount) > 0:
            expected.append({"date": landing, "amount": amount,
                             "kind": "new_sales",
                             "label": f"Fakturering {m.name}"
                                      f"{', ' + days.replace('fakturert ', '') if days else ''}"
                                      f", betalt"})
    return row


def _sales_landing(t: _Trading, m: _Month) -> list:
    """(landing, share, which days) for the accounts' reading of the month's
    sales. Nothing when the register is the source: its runs are placed."""
    if t.runs.from_register:
        return []
    if t.sales_profile.get("measured"):
        # Each period's share, paid its own terms plus the lateness after.
        # This month's remainder only in the days still to come.
        return [(pay + timedelta(days=t.sales_lag), share, days)
                for pay, share, days in _cost_parts(t.sales_profile, m.start,
                                                    t.today, m.current)]
    month_end = date(m.start.year, m.start.month,
                     monthrange(m.start.year, m.start.month)[1])
    return [(month_end + timedelta(days=t.credit_days + t.sales_lag), 1.0, "")]


def _month_vat(t: _Trading, m: _Month, committed: list, expected: list) -> None:
    """The VAT on the month's invoicing, whether or not the customer has paid
    by then — the deadline does not wait for the money. Scheduled even when
    the receipt itself falls outside the window, because that is the case that
    hurts: the liability inside, the cash outside."""
    keep = 1 - t.vat_share
    net_vat = m.revenue * MVA_RATE * keep
    if t.runs.from_register:
        # On what is still to be invoiced. What has gone out this month is
        # booked on 2700 already, and dated by commitments.
        net_vat = (m.gross + m.contract) / (1 + MVA_RATE) * MVA_RATE * keep
    elif m.current:
        net_vat = max(0.0, net_vat - t.booked_vat)
    contract_vat = m.contract / (1 + MVA_RATE) * MVA_RATE * keep
    net_vat = max(0.0, net_vat - contract_vat)
    vat_due = workdays.forward(
        commitments.term_due(m.start.year, m.start.month, commitments.MVA_TERMS))
    if t.today <= vat_due < t.horizon and round(contract_vat) > 0:
        committed.append({"date": vat_due, "amount": -contract_vat,
                          "kind": "vat_recurring",
                          "label": f"Merverdiavgift på fast fakturering {m.name}"})
    if t.today <= vat_due < t.horizon and round(net_vat) > 0:
        expected.append({"date": vat_due, "amount": -net_vat,
                         "kind": "vat_future",
                         "label": f"Merverdiavgift på fakturering {m.name}"})


def _month_costs(t: _Trading, m: _Month, committed: list, expected: list) -> None:
    """The month's running costs, by when the bills are paid. A part paid
    after the window leaves it, as sales collected after it do. The share
    tied to the contracts (from the bank: also what comes whatever is sold)
    is on the committed line."""
    month_vat = m.revenue * MVA_RATE * t.vat_share
    if t.bank_costs:
        # From the bank (card 64): the usual month of what left the account,
        # gross, by the day it left. What is dated already in the same month —
        # open bills, fixed bills, and this month what has left the bank — is
        # part of that month, so it comes off.
        b = t.bank_costs
        fixed = t.known_by_month.get((m.start.year, m.start.month), 0.0)
        cost = max(0.0, b["level"] - fixed - (b["paid_this_month"] if m.current else 0.0))
        cost_tied = b["certain_share"] + (1 - b["certain_share"]) * m.tied
        parts = _cost_parts(b["profile"], m.start, t.today, m.current)
        month_vat = 0.0
    else:
        cost = (t.opex_left * ((m.opex + month_vat) / m.opex) if m.opex else 0.0) \
            if m.current else m.opex + month_vat
        # The fixed bills of this month are its cost too, placed in the
        # committed line on their own dates. Both gross. Never below zero:
        # fixed bills above the run-rate mean the rate is low, not that money
        # comes back.
        fixed = t.fixed_by_month.get((m.start.year, m.start.month), 0.0)
        cost = max(0.0, cost - fixed)
        cost_tied = m.tied
        parts = _cost_parts(t.profile, m.start, t.today, m.current)
    for pay, share, days in parts:
        part = cost * share
        if pay >= t.horizon or round(part) <= 0:
            continue
        label = _cost_label(t, m, days, fixed, month_vat)
        sure = (", den faste delen" if t.bank_costs
                else ", til den faste faktureringen")
        if round(part * cost_tied) > 0:
            committed.append({"date": pay, "amount": -part * cost_tied,
                              "kind": "opex_recurring", "label": label + sure})
        if round(part * (1 - cost_tied)) > 0:
            expected.append({"date": pay, "amount": -part * (1 - cost_tied),
                             "kind": "opex", "label": label})


def _cost_label(t: _Trading, m: _Month, days: str, fixed: float, month_vat: float) -> str:
    if t.bank_costs:
        return (f"Driftskostnader {m.name}"
                f"{', resten' if m.current else ''}"
                f"{', betalt ' + days.replace('fakturert ', '') if days else ''}"
                f", fra banken"
                f"{' utenom kjente regninger' if fixed >= 0.5 else ''}")
    return (f"Driftskostnader {m.name}"
            f"{', resten' if m.current else ''}"
            f"{', ' + days if days else ''}"
            f"{' utenom faste regninger' if fixed >= 0.5 else ''}"
            f"{' (inkl. moms)' if month_vat >= 0.5 else ''}")
