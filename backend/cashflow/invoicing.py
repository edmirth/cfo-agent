"""Invoicing not sent yet: the regular customers' runs and the rest."""
import statistics
from calendar import monthrange
from datetime import date, timedelta

import payment_habits
import workdays

from .common import COST_PERIODS, LATE_DAYS, MONTH_NAMES, PAY_LAG_DAYS, RECURRING_MONTHS, RUN_ACTIVE, RUN_MONTHS, _add_months, _kr, _term_step
from .costs import _profile
from .models import FlowKind, Runs, Sources
from .receivables import _days_overdue
from .common import _iso, _months_until


# The rest of the invoicing, to customers not billed every month, is one stream
# whose level is the median month. A month above UNUSUAL × that median is a
# one-off (a big job) and is left out of how the rest is timed, and named.
UNUSUAL = 1.5
# A regular customer leaves the committed line, never the forecast, when
# something says his invoicing is less sure: more than BEHIND_MIN kroner and
# BEHIND_SHARE of his usual month over LATE_DAYS late, or his usual invoice
# days this month STALL_DAYS past with nothing sent. One small invoice a month
# late used to take his whole invoicing out of both lines. Only a customer
# with more than his usual month over LATE_DAYS late is out of both: that is a
# customer in trouble, not a slow payment.
BEHIND_MIN = 5_000.0
BEHIND_SHARE = 0.25
STALL_DAYS = 10


def _sales_rows(history: list):
    """(issued, due, amount, customer) for every customer invoice in the
    history that stands: a credited invoice and its credit note are left out
    together."""
    for row in history:
        if row.get("isCredited"):
            continue
        issued, due = _iso(row.get("invoiceDate")), _iso(row.get("dueDate"))
        if issued is None or due is None:
            continue
        amount = float(row.get("amount") or row.get("amountCurrency") or 0)
        if amount > 0:
            yield issued, due, amount, row.get("customerName") or ""


def _sales_profile(history: list) -> dict:
    """When in the month this company's invoices are dated, and on what
    terms — the same reading `_cost_profile` makes of the supplier bills.

    New sales were assumed invoiced on the last day of every month, on the
    median terms of the open invoices: a company invoicing on the 10th had
    its money placed three weeks late, and October's invoicing paid in
    January fell outside the window altogether.
    """
    return _profile([(i, d, a) for i, d, a, _ in _sales_rows(history)])


def _invoice_months(history: list, skip: set[str] = frozenset()) -> dict:
    """{customer: {(year, month): {"amount", "parts": [(day, terms, amount)]}}}
    for every standing invoice in the history."""
    by_customer: dict = {}
    for issued, due, amount, name in _sales_rows(history):
        if not name or name in skip:
            continue
        m = by_customer.setdefault(name, {}).setdefault(
            (issued.year, issued.month), {"amount": 0.0, "parts": []})
        m["amount"] += amount
        m["parts"].append((issued.day, max(0, (due - issued).days), amount))
    return by_customer


def _run_parts(parts: list[tuple[int, int, float]]) -> list[tuple[int, int, float]]:
    """(day, terms, share): one customer's invoicing by day and terms."""
    total = sum(a for _, _, a in parts)
    grouped: dict = {}
    for day, terms, amount in parts:
        grouped[(day, terms)] = grouped.get((day, terms), 0.0) + amount
    return [(d, t, a / total) for (d, t), a in sorted(grouped.items())] if total else []


def _place_month(parts, y: int, mo: int, today: date, current: bool):
    """(issue day, share) for each part of a month still to be invoiced.

    This month, only the days still to come: what was due to go out before
    today has gone, and is in the open invoices. Where every usual day has
    passed, the rest goes out today at the earliest."""
    last = monthrange(y, mo)[1]
    if current:
        ahead = [p for p in parts if min(p[0], last) >= today.day]
        if ahead:
            total = sum(p[2] for p in ahead)
            parts = [(d, t, sh / total) for d, t, sh in ahead]
    return [(max(date(y, mo, min(d, last)), today), t, sh) for d, t, sh in parts]


def _invoice_runs(history: list, today: date, horizon: date,
                  habits: dict | None = None, season: dict | None = None,
                  skip: set[str] = frozenset(),
                  overdue: dict[str, float] | None = None) -> tuple[list, list, dict]:
    """The regular customers' invoicing still to be sent, from the register.

    Returns the flows (`recurring` in the committed line at the customer's
    lowest recent month, `recurring_usual` in the expected line for the rest
    of his usual month), what was found per customer, and each month's
    {"low", "usual"} still to be invoiced by `(year, month)`, inside the
    window or not, for the VAT and the running costs.

    Each customer on his own days and terms, from his last RECURRING_MONTHS
    months: at the first customer three customers were invoiced through the
    month on 45 days, most of the rest at month end on 30, and the housing
    cooperatives on 14. One rule for all of them put most of the money weeks
    from where it lands. What he has been invoiced this month already comes
    off his month; an invoice once sent is in the open invoices instead.

    The usual month is the median of his months, so one big job does not set
    it; the committed line still takes the lowest of the last three.

    Regular is RUN_ACTIVE of the last RUN_MONTHS months. Only a customer
    invoiced in each of the last RECURRING_MONTHS, not behind (`overdue`, his
    invoices over LATE_DAYS late, against BEHIND_MIN and BEHIND_SHARE of his
    usual month) and not stalled this month is in the committed line; the
    others keep their usual month in the expected line. Each of those used to
    take him out of both lines at once: one month invoiced late, or one small
    invoice a month overdue, and a customer billed every month vanished from
    the chart overnight. `skip` is the customers out altogether.
    """
    this = (today.year, today.month)
    closed = [_add_months(*this, -n) for n in range(1, RUN_MONTHS + 1)]
    flows, found, by_month = [], [], {}
    for name, months in _invoice_months(history, skip).items():
        recent = closed[:RECURRING_MONTHS]
        active = [months[k]["amount"] for k in closed if k in months]
        if len(active) < RUN_ACTIVE:
            continue
        usual = statistics.median(active)
        if usual <= 0:
            continue
        timed = [k for k in closed if k in months][:RECURRING_MONTHS]
        parts = _run_parts([p for k in timed for p in months[k]["parts"]])
        behind = (overdue or {}).get(name, 0.0)
        if behind > BEHIND_MIN and behind >= usual:
            found.append({"name": name, "amount": 0.0, "usual": round(usual, 2),
                          "committed": False, "excluded": True,
                          "why": f"{_kr(behind)} kr over {LATE_DAYS} dager på overtid, "
                                 f"mer enn en vanlig måned",
                          "day": None, "terms": None, "term_steps": [], "late": None,
                          "next": None})
            continue
        why = _why_aside(months, recent, behind, usual, parts, today)
        low = min(months[k]["amount"] for k in recent) if why is None else 0.0
        late = payment_habits.lag(habits, name, PAY_LAG_DAYS)
        upcoming = _place_runs(name, months, parts, low, usual, late, season,
                               today, horizon, by_month, flows)
        found.append(_run_found(name, low, usual, why, parts, late, upcoming))
    found.sort(key=lambda f: -f["usual"])
    return flows, found, by_month


def _why_aside(months: dict, recent: list, behind: float, usual: float,
               parts: list, today: date) -> str | None:
    """Why a regular customer is in the expected line only, or None."""
    if not all(k in months for k in recent):
        return "en av de siste månedene uten faktura"
    if behind > BEHIND_MIN and behind >= BEHIND_SHARE * usual:
        return f"{_kr(behind)} kr over {LATE_DAYS} dager på overtid"
    sent_now = months.get((today.year, today.month), {}).get("amount", 0.0)
    last_day = max(d for d, _, _ in parts)
    if today.day > last_day + STALL_DAYS and sent_now < 0.5 * usual:
        return f"ingen faktura ennå denne måneden, vanligvis den {last_day}."
    return None


def _place_runs(name: str, months: dict, parts: list, low: float, usual: float,
                late: int, season: dict | None, today: date, horizon: date,
                by_month: dict, flows: list) -> list[date]:
    """One customer's invoicing still to be sent, month by month: the lowest
    recent month on the committed line, the rest of the usual one on the
    expected. Returns the pay days inside the window."""
    this = (today.year, today.month)
    upcoming = []
    for y, mo in _months_until(*this, horizon):
        s = (season or {}).get(mo, 1.0)
        sent = months.get((y, mo), {}).get("amount", 0.0)
        left_low = max(0.0, low * min(1.0, s) - sent)
        left_usual = max(left_low, usual * s - sent)
        if left_usual >= 0.5:
            m = by_month.setdefault((y, mo), {"low": 0.0, "usual": 0.0})
            m["low"] += left_low
            m["usual"] += left_usual
            for issued, terms, share in _place_month(parts, y, mo, today, (y, mo) == this):
                pay = workdays.forward(issued + timedelta(days=terms + late))
                # Sent inside the window and paid after it: kept for the
                # line after week 13 (`after` in `_assemble`), never on
                # the weeks.
                if issued >= horizon:
                    continue
                label = (f"Fakturering {MONTH_NAMES[mo - 1]} (ikke sendt), "
                         f"{_term_step(terms)} dager")
                if round(left_low * share) > 0:
                    flows.append({"date": pay, "amount": left_low * share,
                                  "kind": FlowKind.RECURRING, "month": (y, mo),
                                  "customer": name, "label": label})
                    if pay < horizon:
                        upcoming.append(pay)
                if round((left_usual - left_low) * share) > 0:
                    flows.append({"date": pay, "amount": (left_usual - left_low) * share,
                                  "kind": FlowKind.RECURRING_USUAL, "month": (y, mo),
                                  "customer": name, "label": label})
    return upcoming


def _run_found(name: str, low: float, usual: float, why: str | None, parts: list,
               late: int, upcoming: list[date]) -> dict:
    """One regular customer as the forecast declares him."""
    return {"name": name, "amount": round(low, 2), "usual": round(usual, 2),
            "committed": why is None, "excluded": False, "why": why,
            "day": int(statistics.median([d for d, _, _ in parts])),
            "terms": int(statistics.median([t for _, t, _ in parts])),
            "term_steps": sorted({_term_step(t) for _, t, _ in parts}), "late": late,
            "next": min(upcoming).isoformat() if upcoming else None}


def _other_invoicing(history: list, today: date, horizon: date, lag: int,
                     season: dict | None, regular: set[str],
                     skip: set[str] = frozenset()) -> tuple[list, dict, dict]:
    """Invoicing to the customers not billed every month: the expected line
    only, at the median month, on the days and terms that invoicing has had.

    Returns the flows, each month's amount still to be invoiced, and what was
    measured: the level, the months it rests on, and the unusual ones.

    A month above UNUSUAL × the median is a one-off, such as a big job, and
    does not come again: it sets neither the level (the median already sees
    to that) nor when the rest is invoiced and on what terms."""
    this = (today.year, today.month)
    closed = [_add_months(*this, -n) for n in range(1, RUN_MONTHS + 1)]
    months = {k: {"amount": 0.0, "parts": []} for k in closed}
    sent = 0.0
    for name, by in _invoice_months(history, skip | regular).items():
        for k, m in by.items():
            if k in months:
                months[k]["amount"] += m["amount"]
                months[k]["parts"] += m["parts"]
            elif k == this:
                sent += m["amount"]
    totals = [months[k]["amount"] for k in closed]
    level = statistics.median(totals) if totals else 0.0
    unusual = [k for k in closed if level > 0 and months[k]["amount"] > UNUSUAL * level]
    parts = (_run_parts([p for k in closed if k not in unusual for p in months[k]["parts"]])
             or _run_parts([p for k in closed for p in months[k]["parts"]]))
    # Grouped by the cost periods of the month, so a stream of small one-offs
    # makes a handful of lines and not one per invoice.
    grouped: dict = {}
    for day, terms, share in parts:
        period = next(i for i, (lo, hi) in enumerate(COST_PERIODS) if lo <= day <= hi)
        g = grouped.setdefault((period, _term_step(terms)), [0.0, []])
        g[0] += share
        g[1].append(day)
    parts = [(int(statistics.median(days)), terms, share)
             for (_, terms), (share, days) in sorted(grouped.items())]
    flows, by_month = [], {}
    for y, mo in (_months_until(*this, horizon) if level > 0 and parts else ()):
        s = (season or {}).get(mo, 1.0)
        left = max(0.0, level * s - (sent if (y, mo) == this else 0.0))
        if left >= 0.5:
            by_month[(y, mo)] = left
            for issued, terms, share in _place_month(parts, y, mo, today, (y, mo) == this):
                pay = workdays.forward(issued + timedelta(days=terms + lag))
                if issued < horizon and round(left * share) > 0:
                    flows.append({"date": pay, "amount": left * share, "kind": FlowKind.NEW_SALES,
                                  "month": (y, mo),
                                  "label": f"Annen fakturering {MONTH_NAMES[mo - 1]} "
                                           f"(ikke sendt), {terms} dager"})
    measured = {"nivaa_mnd": round(level, 2),
                "maneder": [{"month": f"{MONTH_NAMES[k[1] - 1]} {k[0]}",
                             "amount": round(months[k]["amount"], 2)} for k in reversed(closed)],
                "uvanlige": [{"month": f"{MONTH_NAMES[k[1] - 1]} {k[0]}",
                              "amount": round(months[k]["amount"], 2)} for k in unusual]}
    return flows, by_month, measured


def _register_months(history: list, today: date) -> int:
    """How many of the last RUN_MONTHS closed months have any invoicing in the
    register. Counted back until the first empty month, one quiet month in a
    young book sent the whole forecast back to the accounts."""
    have = {(i.year, i.month) for i, _, _, _ in _sales_rows(history)}
    this = (today.year, today.month)
    return sum(1 for n in range(1, RUN_MONTHS + 1) if _add_months(*this, -n) in have)


# The register is read for this many closed months before it is trusted over
# the revenue in the accounts; a younger book keeps the old reading.
RUN_MIN_MONTHS = 3


def _sales_timing(src: Sources, habits: dict) -> tuple[dict, int]:
    """When in the month this company invoices, on what terms, and how late
    its customers pay on top. Returns (profile, lag)."""
    lag = habits["company"] if habits.get("company") is not None else PAY_LAG_DAYS
    return _sales_profile(src.customer_history), lag


def _invoicing(src: Sources, today: date, horizon: date, habits: dict, season: dict,
               risky: dict, ar_due: list, sales_lag: int,
               flows: list) -> Runs:
    """The contract customers' runs on the committed line, and with enough
    register to read, the rest of the invoicing on the expected line.

    The customers on a contract are invoiced whether or not anyone sells
    anything, so the floor carries them, as it carries the rent. Not those in
    trouble with the register, nor those already further behind than ordinary
    lateness: their open invoices are not counted on either."""
    # What each customer has over LATE_DAYS late. It used to be a set of
    # names, and any one invoice in it took the customer out of both lines.
    behind: dict[str, float] = {}
    for i in ar_due:
        if (_days_overdue(i, today) or 0) > LATE_DAYS:
            behind[i["name"]] = behind.get(i["name"], 0.0) + i["amount"]
    run_flows, found, by_month = _invoice_runs(
        src.customer_history, today, horizon, habits, season.get("revenue"),
        set(risky), behind)
    flows += [f for f in run_flows if f["kind"] == FlowKind.RECURRING]
    # With RUN_MIN_MONTHS of invoicing to read, the register is the money
    # coming in, and the revenue in the accounts only a check on it. A book
    # younger than that keeps the accounts.
    from_register = _register_months(src.customer_history, today) >= RUN_MIN_MONTHS
    other_by_month, other_measured = {}, None
    if from_register:
        flows += [f for f in run_flows if f["kind"] == FlowKind.RECURRING_USUAL]
        other_flows, other_by_month, other_measured = _other_invoicing(
            src.customer_history, today, horizon, sales_lag, season.get("revenue"),
            {f["name"] for f in found}, set(risky))
        flows += other_flows
    return Runs(by_month, found, from_register, other_by_month, other_measured)


def _invoiced_this_month(src: Sources, today: date) -> float:
    """Invoicing already issued this month, gross, to net off the month.

    The open invoices issued this month, or everything invoiced this month
    paid ones included, whichever is more: an invoice sent on the 2nd and paid
    on the 9th has its money in the opening balance already. The open list
    stays the floor, for a month whose invoices could not be read."""
    total = 0.0
    for i in src.ar_open:
        issued_on = _iso(i.get("invoiced"))
        if issued_on is None:
            continue
        if (issued_on.year, issued_on.month) == (today.year, today.month):
            total += i["amount"]
    return max(total, src.issued.get("this_month", 0.0))
