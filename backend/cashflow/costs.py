"""Running costs: the fixed bills, and when in the month the rest is paid."""
import statistics
from calendar import monthrange
from datetime import date, timedelta

from .common import BANK_UNKNOWN_MAX, COST_PERIODS, _add_months, _weighted_median


# What makes a supplier's bill a fixed one, for the committed line: billed in
# FIXED_MIN of the last FIXED_LOOKBACK closed months (or FIXED_MIN quarters in
# a row), every amount within FIXED_TOLERANCE of the median. See _fixed_bills.
FIXED_LOOKBACK = 4
FIXED_MIN = 3
FIXED_TOLERANCE = 0.15
PROFILE_MIN_BILLS = 10
PROFILE_WEIGHT_CAP = 3
PROFILE_MIN_PERIOD_BILLS = 3


def _fixed_bills(history: list, today: date,
                 horizon: date) -> tuple[list, list, dict]:
    """The bills that come whether anyone sells anything: rent, leasing,
    insurance, software. Returns the flows, what was found, and the fixed
    amount of each month still to be billed — paid inside the window or not,
    since it is that month's cost all the same and the expected line nets it.

    The committed line is the floor, and it had payroll and the tax dates but
    none of these — they lived only inside the expected line's running costs,
    so the floor the brief's colour rests on stood higher than it is.

    Found by how the bills arrive, not by which account they are booked on:
    6400, 6700 and 7700 hold fixed and variable alike, while a supplier who
    bills the same amount every month is plain to see. Monthly: a bill in at
    least FIXED_MIN of the last FIXED_LOOKBACK closed months. Quarterly: at
    least FIXED_MIN bills three months apart. Every amount within
    FIXED_TOLERANCE of the supplier's median, so materials that follow sales
    stay out — they are not certain, which is what this line is for. Credit
    notes and foreign currency stay out of the reading.

    A month whose bill has arrived is skipped: it is in the payables or paid
    out of the opening balance. One whose usual day has passed without a bill
    is placed anyway, on its usual due date or today, since a bill that is
    late or in the inbox is still owed.
    """
    by_supplier: dict = {}
    for row in history:
        if row.get("isCreditNote") or (row.get("currency") or "NOK").upper() != "NOK":
            continue
        try:
            issued = date.fromisoformat(row["invoiceDate"])
            due = date.fromisoformat(row["dueDate"])
        except (ValueError, TypeError, KeyError):
            continue
        amount = float(row.get("amountCurrency") or row.get("amount") or 0)
        name = row.get("supplierName") or ""
        if amount <= 0 or not name:
            continue
        s = by_supplier.setdefault(row.get("supplierId") or name,
                                   {"name": name, "months": {}})
        m = s["months"].setdefault((issued.year, issued.month),
                                   {"amount": 0.0, "days": [], "terms": [], "last": issued})
        m["amount"] += amount
        m["days"].append(issued.day)
        m["terms"].append((due - issued).days)
        m["last"] = max(m["last"], issued)

    this = (today.year, today.month)
    closed = [_add_months(*this, -n) for n in range(1, FIXED_LOOKBACK + 1)]
    flows, found, by_month = [], [], {}
    for s in by_supplier.values():
        months = s["months"]
        past = sorted(k for k in months if k < this)
        if not past:
            continue

        def stable(keys) -> bool:
            values = [months[k]["amount"] for k in keys]
            mid = statistics.median(values)
            return mid > 0 and all(abs(v - mid) <= FIXED_TOLERANCE * mid for v in values)

        recent = [k for k in closed if k in months]
        gaps = [(b[0] * 12 + b[1]) - (a[0] * 12 + a[1]) for a, b in zip(past, past[1:])]
        if len(recent) >= FIXED_MIN and stable(recent):
            step, cadence, basis = 1, "månedlig", recent
        elif len(past) >= FIXED_MIN and gaps and all(g == 3 for g in gaps) \
                and stable(past) and _add_months(*past[-1], 3) >= this:
            step, cadence, basis = 3, "kvartalsvis", past
        else:
            continue

        latest = max(months, key=lambda k: months[k]["last"])
        amount = months[latest]["amount"]
        day = int(statistics.median([d for k in basis for d in months[k]["days"]]))
        terms = int(statistics.median([t for k in basis for t in months[k]["terms"]]))
        upcoming = []
        y, mo = _add_months(*past[-1], step)
        while True:
            issued = date(y, mo, min(day, monthrange(y, mo)[1]))
            if issued >= horizon:
                break
            pay = max(issued + timedelta(days=terms), today)
            due_now = (y, mo) >= this and (y, mo) not in months
            if due_now:
                by_month[(y, mo)] = by_month.get((y, mo), 0.0) + amount
            if due_now and pay < horizon:
                flows.append({"date": pay, "amount": -amount, "kind": "fixed",
                              "month": (y, mo),
                              "label": f"Fast regning fra {s['name']}"})
                upcoming.append(pay)
            y, mo = _add_months(y, mo, step)
        found.append({"name": s["name"], "amount": round(amount, 2),
                      "cadence": cadence, "day": day, "terms": terms,
                      "next": min(upcoming).isoformat() if upcoming else None})
    found.sort(key=lambda f: -f["amount"])
    return flows, found, by_month


def _bill_rows(history: list):
    """(issued, due, gross, supplier) for every readable NOK bill in the
    supplier history. Credit notes and foreign currency are left out."""
    for row in history:
        if row.get("isCreditNote") or (row.get("currency") or "NOK").upper() != "NOK":
            continue
        try:
            issued = date.fromisoformat(row["invoiceDate"])
            due = date.fromisoformat(row["dueDate"])
        except (ValueError, TypeError, KeyError):
            continue
        amount = float(row.get("amountCurrency") or row.get("amount") or 0)
        if amount > 0:
            yield issued, due, amount, row.get("supplierName") or ""


def _cost_profile(history: list, fixed_names: set[str]) -> dict:
    """When in the month the variable bills are dated, and how long after they
    are paid — measured on this company's own supplier history.

    The running costs used to leave in one lump on the last day of the month.
    Materials dated the 6th on fourteen days' terms are paid on the 20th, and
    a bill dated the 25th on thirty days is paid next month; the lump was
    wrong both ways, and the week it put the low point in is the week the
    brief names. Split into COST_PERIODS: each period's share of the amount,
    and the amount-weighted median of its terms. The fixed suppliers are
    left out: their bills are placed on their own dates already.

    Each bill weighs by its amount, but no more than PROFILE_WEIGHT_CAP times
    the median bill: one machine bought on 65 days' terms otherwise set the
    pattern for every month's cleaning supplies.

    Too few bills to read a pattern off, and the month-end lump is kept and
    said to be kept.
    """
    return _profile([(i, d, a) for i, d, a, who in _bill_rows(history)
                     if who not in fixed_names])


def _profile(bills: list[tuple[date, date, float]]) -> dict:
    """Shares and terms by COST_PERIODS from (issued, due, amount) rows."""
    sums = [0.0] * len(COST_PERIODS)
    terms: list[list] = [[] for _ in COST_PERIODS]
    # The day within the period the money is usually dated, not its middle:
    # a company invoicing on the last workday was placed on the 26th, five
    # days early, and five days decide which week the money lands in.
    days: list[list] = [[] for _ in COST_PERIODS]
    cap = (PROFILE_WEIGHT_CAP * statistics.median([b[2] for b in bills])
           if bills else 0.0)
    count = 0
    for issued, due, gross in bills:
        amount = min(gross, cap)
        i = next(n for n, (_, last) in enumerate(COST_PERIODS) if issued.day <= last)
        sums[i] += amount
        terms[i].append((max(0, (due - issued).days), amount))
        days[i].append((issued.day, amount))
        count += 1
    total = sum(sums)
    if count < PROFILE_MIN_BILLS or total <= 0:
        return {"measured": False, "bills": count, "periods": []}
    # A period with a bill or two says little about its terms, and a lone
    # one-off set them on its own: it takes the terms of all the bills.
    overall = int(_weighted_median([t for ts in terms for t in ts]))
    return {"measured": True, "bills": count, "periods": [
        {"from": first, "to": last, "share": round(sums[i] / total, 4),
         "day": int(_weighted_median(days[i])),
         "terms": (int(_weighted_median(terms[i]))
                   if len(terms[i]) >= PROFILE_MIN_PERIOD_BILLS else overall)}
        for i, (first, last) in enumerate(COST_PERIODS) if sums[i] > 0]}


def _bank_costs(cats: dict | None) -> dict | None:
    """The bank's running costs, when they can carry the forecast: read,
    at least `bankcat.COST_MIN_MONTHS` closed months, and no more than
    BANK_UNKNOWN_MAX of the money out without a category."""
    costs = (cats or {}).get("costs")
    if not costs or costs["level"] <= 0:
        return None
    if cats.get("unknown_share_out", 1.0) > BANK_UNKNOWN_MAX:
        return None
    return costs


def _cost_parts(profile: dict, month: date, today: date,
                current: bool) -> list[tuple[date, float, str]]:
    """(pay day, share, which days) for one month's variable costs.

    The current month's remainder is what has not been booked yet, so it is
    spread over the periods not yet over, and nothing is paid before today.
    """
    last_day = monthrange(month.year, month.month)[1]
    month_end = date(month.year, month.month, last_day)
    if not profile.get("measured"):
        return [(max(month_end, today), 1.0, "")]
    periods = [p for p in profile["periods"]
               if not current or min(p["to"], last_day) >= today.day]
    if not periods:
        return [(max(month_end, today), 1.0, "")]
    total = sum(p["share"] for p in periods)
    out = []
    for p in periods:
        to = min(p["to"], last_day)
        # The usual day where measured; an older profile without one, the middle.
        mid = date(month.year, month.month,
                   min(max(p.get("day") or (p["from"] + to) // 2, p["from"]), to))
        pay = max(mid + timedelta(days=p["terms"]), today)
        out.append((pay, p["share"] / total, f"fakturert {p['from']}.–{to}."))
    return out
