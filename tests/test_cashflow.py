from datetime import date, timedelta

import cashflow


def test_payables_are_not_lagged_or_spread():
    today = date(2026, 9, 27)
    bills = [{"name": "Leverandør", "due": "2026-10-10", "amount": 100.0},
             {"name": "Gammel", "due": "2026-08-01", "amount": 50.0}]
    flows = cashflow._schedule_payments(bills, today)
    assert flows[0]["date"] == date(2026, 10, 10) and flows[0]["amount"] == -100.0
    assert flows[1]["date"] == today and flows[1]["amount"] == -50.0
    assert flows[0]["label"].startswith("Regning fra")


def test_receipts_get_the_customer_lag():
    today = date(2026, 9, 27)
    flows = cashflow._schedule_receipts(
        [{"name": "Kunde", "due": "2026-10-01", "amount": 10.0, "number": 1, "email": "", "url": ""}], today)
    assert flows[0]["date"] == date(2026, 10, 1) + timedelta(days=cashflow.PAY_LAG_DAYS)


def test_month_window_ends_exclusive():
    """search_invoices treats invoiceDateTo as exclusive.

    Passing the last day of the month dropped every invoice dated on it. This
    company invoices monthly at month end, so that hid more than half its
    receivables — 1 215 575 kr visible against 2 539 600 kr on account 1500.
    """
    start, end = cashflow._month_bounds(date(2026, 9, 30), 0)
    assert start == date(2026, 9, 1)
    assert end == date(2026, 10, 1), "end must be the first of the next month"
    # An invoice dated the last day of the month falls inside the window.
    assert start <= date(2026, 9, 30) < end


def test_month_window_rolls_over_the_year():
    start, end = cashflow._month_bounds(date(2026, 3, 15), 3)
    assert (start, end) == (date(2025, 12, 1), date(2026, 1, 1))
    assert start <= date(2025, 12, 31) < end


def test_every_month_in_the_lookback_is_covered_without_gaps():
    """Consecutive windows must meet exactly: no day in, or out, twice."""
    today = date(2026, 9, 30)
    windows = [cashflow._month_bounds(today, b)
               for b in range(cashflow.AR_MONTHS_BACK)]
    for newer, older in zip(windows, windows[1:]):
        assert older[1] == newer[0], f"{older} does not meet {newer}"


# ---------------------------------------------- which line goes in minus

RATES = {"revenue": 0.0, "wages": 0.0, "wages_cash": 0.0, "opex": 0.0,
         "aga": 0.0}


def _assembled(committed, expected, opening=100_000.0):
    today = date(2026, 10, 5)
    return cashflow._assemble(today, cashflow._monday(today), opening,
                              committed, expected, RATES, 30, [], [], [])


def _flow(day, amount, kind="x"):
    return {"date": date(2026, 10, 5) + timedelta(days=day), "amount": amount,
            "kind": kind, "label": "testpost"}


def test_the_committed_line_going_dry_is_reported():
    """The floor is what the owner is asked to decide on.

    goes_negative was measured on the expected line alone, so a committed
    line 800 000 kr under water was reported to the agent as "kontoen går
    ikke i minus i perioden" — with the dashboard card, which reads
    committed_close, saying the opposite at the same time.
    """
    data = _assembled([_flow(7, -900_000)], [_flow(8, 1_200_000, "new_sales")])
    assert data["low_committed"]["amount"] < 0
    assert data["low_expected"]["amount"] > 0
    assert data["goes_negative"] is None, "the expected line holds up"
    assert data["goes_negative_committed"], "the committed line does not"

    said = cashflow.briefing(data)
    assert "går ikke i minus" not in said
    assert "bundne linjen går i minus" in said


def test_neither_line_going_dry_is_still_said_plainly():
    data = _assembled([_flow(7, -10_000)], [_flow(8, 5_000, "new_sales")])
    assert data["goes_negative"] is None
    assert data["goes_negative_committed"] is None
    assert "Ingen av de to linjene går i minus" in cashflow.briefing(data)


def test_both_lines_going_dry_leads_with_the_committed_week():
    data = _assembled([_flow(7, -900_000)], [_flow(40, -100_000, "opex")])
    assert data["goes_negative"] and data["goes_negative_committed"]
    said = cashflow.briefing(data)
    assert "begge linjene" in said
    assert data["goes_negative_committed"]["label"] in said
