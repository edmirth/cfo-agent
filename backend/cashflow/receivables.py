"""Customer invoices: when their money is expected to land."""
from datetime import date, timedelta

import payment_habits
import workdays

from .common import DOUBTFUL_DAYS, LATE_DAYS, LATE_SPREAD_WEEKS, PAY_LAG_DAYS, SLOW_WEEKS
from .payables import _payment_parts


def _receipt_parts(inv: dict, today: date,
                   habits: dict | None = None) -> list[tuple[date, float]] | None:
    """When one customer invoice's money is expected to land: (date, amount).

    An invoice that is already overdue will not arrive the day you notice it,
    and one that is not yet due will not arrive on the dot either. Overdue
    invoices are spread over the next few weeks; the rest are dated from their
    due date plus the lag customers take anyway. None for an invoice with no
    usable due date. The schedule below and the invoice list kept with each
    forecast both come from here, so a miss is measured against what the
    forecast actually said.
    """
    late = _days_overdue(inv, today)
    if late is None:
        return None
    due = date.fromisoformat(inv["due"])
    if late > DOUBTFUL_DAYS:
        return []
    if late > LATE_DAYS:
        first, last = SLOW_WEEKS
        per = inv["amount"] / (last - first + 1)
        return [(today + timedelta(days=7 * w), per) for w in range(first, last + 1)]
    if late > 0:
        # A customer who always pays three weeks late and is one week late now
        # is not late by his own lights: his money comes when it usually does.
        usual = payment_habits.own(habits, inv.get("name") or "")
        if usual is not None and late < usual:
            return [(workdays.forward(due + timedelta(days=usual)), inv["amount"])]
        per = inv["amount"] / LATE_SPREAD_WEEKS
        return [(today + timedelta(days=7 * (w + 1)), per)
                for w in range(LATE_SPREAD_WEEKS)]
    # Not yet due: the customer's own lateness, the company's where he has too
    # little history, and the old seven days where there is none at all.
    # On a banking day: a customer cannot pay on a Saturday, and money due on
    # Christmas Eve lands after the holiday, often in the next week.
    lag = payment_habits.lag(habits, inv.get("name") or "", PAY_LAG_DAYS)
    return [(workdays.forward(due + timedelta(days=lag)), inv["amount"])]


def _days_overdue(inv: dict, today: date) -> int | None:
    """Days past due, 0 for one not yet due, None without a due date."""
    try:
        due = date.fromisoformat(inv["due"])
    except (ValueError, TypeError, KeyError):
        return None
    return max(0, (today - due).days)


def _schedule_receipts(invoices: list, today: date,
                       habits: dict | None = None) -> list:
    """Customer invoices as flows. Not-yet-due ones keep their own line;
    overdue ones are pooled into one line a week, since the spread is ours and
    a line per invoice per week would bury the table.

    Those 31-90 days late come back as `ar_slow`, which belongs in the
    expected line only; the caller splits them off. Those later still have no
    flow at all."""
    flows, overdue, slow = [], [], []
    for inv in invoices:
        parts = _receipt_parts(inv, today, habits)
        if not parts:
            continue
        if (_days_overdue(inv, today) or 0) > LATE_DAYS:
            slow.append(parts)
            continue
        if len(parts) > 1:
            overdue.append((inv, parts))
            continue
        for when, amount in parts:
            flows.append({"date": when, "amount": amount, "kind": "ar",
                          "label": f"Faktura til {inv['name']}"})
    if overdue:
        for w in range(LATE_SPREAD_WEEKS):
            flows.append({"date": today + timedelta(days=7 * (w + 1)),
                          "amount": sum(p[w][1] for _, p in overdue),
                          "kind": "ar_late",
                          "label": f"Forfalte fakturaer ({len(overdue)} stk), "
                                   f"fordelt over {LATE_SPREAD_WEEKS} uker"})
    if slow:
        first, last = SLOW_WEEKS
        for n, w in enumerate(range(first, last + 1)):
            flows.append({"date": today + timedelta(days=7 * w),
                          "amount": sum(p[n][1] for p in slow),
                          "kind": "ar_slow",
                          "label": f"Fakturaer {LATE_DAYS + 1}–{DOUBTFUL_DAYS} "
                                   f"dager på overtid ({len(slow)} stk), "
                                   f"fordelt over uke {first}–{last}"})
    return flows


def _expected_items(invoices: list, bills: list, today: date,
                    habits: dict | None = None) -> dict:
    """Every open invoice and bill, with when this forecast expects it.

    Kept with the saved forecast, so that when it is scored a miss can be put
    down to who paid later than expected — the pooled overdue line cannot say.
    """
    def items(rows, parts_of):
        out = []
        for r in rows:
            parts = parts_of(r, today)
            if parts:
                out.append({"number": r.get("number"), "name": r.get("name") or "",
                            "amount": round(r["amount"], 2),
                            "parts": [[d.isoformat(), round(a, 2)] for d, a in parts]})
        return out
    return {"ar": items(invoices, lambda r, t: _receipt_parts(r, t, habits)),
            "ap": items(bills, _payment_parts)}
