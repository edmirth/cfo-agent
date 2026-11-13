"""Our own bills: when they leave the account."""
from datetime import date



def _payment_parts(bill: dict, today: date) -> list[tuple[date, float]] | None:
    """When one of our own bills leaves: on its due date, or this week if it
    is already overdue. As `_receipt_parts`, but without the lag or the spread
    — both would understate what leaves the account soon."""
    try:
        due = date.fromisoformat(bill["due"])
    except (ValueError, TypeError, KeyError):
        return None
    return [(max(due, today), bill["amount"])]


def _schedule_payments(bills: list, today: date) -> list:
    """Our own bills as flows. The customer scheduler above must not be reused
    here — it adds the lag customers take, and spreads the overdue book over
    weeks, both of which understate what leaves the account soon."""
    flows = []
    for bill in bills:
        for when, amount in _payment_parts(bill, today) or []:
            flows.append({"date": when, "amount": -amount,
                          "kind": "ap", "label": f"Regning fra {bill['name']}"})
    return flows
