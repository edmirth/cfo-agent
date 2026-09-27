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
