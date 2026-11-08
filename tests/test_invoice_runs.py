"""Money coming in from the invoice register, customer by customer (card 60).

The revenue in the accounts × 1.25 put a whole month's sales on one profile,
and at the first customer the chart read as if invoicing had stopped. Here
every regular customer is invoiced on his own days and terms, the rest of the
invoicing is one stream at its median month, and a one-off big job does not
come back as if it were normal.
"""
from datetime import date, timedelta

import cashflow
from tests.test_cashflow_build import REVENUE, _forecast, _invoice

TODAY = date(2026, 10, 5)
HORIZON = TODAY + timedelta(weeks=13)
MONTHS = [(2026, m) for m in range(3, 10)]          # March to September


def _row(name, issued: date, terms: int, amount: float, n: int) -> dict:
    return {**_invoice(0.0, issued.isoformat(), (issued + timedelta(days=terms)).isoformat(), n),
            "customerName": name, "amount": amount}


def _monthly(name, day, terms, amount, months=MONTHS, start=0):
    return [_row(name, date(y, m, day), terms, amount, start + k)
            for k, (y, m) in enumerate(months)]


def _weeks(flows, kind=None):
    out: dict = {}
    for f in flows:
        if kind and f["kind"] != kind:
            continue
        monday = f["date"] - timedelta(days=f["date"].weekday())
        out[monday.isoformat()] = out.get(monday.isoformat(), 0) + round(f["amount"])
    return sorted(out.items())


# ------------------------------------------------ each customer his own way
def test_each_customer_is_invoiced_on_his_own_days_and_terms():
    """One at month end on 30 days, one on the 15th on 45 days."""
    history = (_monthly("Slutt AS", 30, 30, 100_000.0)
               + _monthly("Midt AS", 15, 45, 50_000.0, start=100))
    flows, found, _ = cashflow._invoice_runs(history, TODAY, HORIZON)
    by = {f["name"]: f for f in found}
    assert (by["Slutt AS"]["day"], by["Slutt AS"]["terms"]) == (30, 30)
    assert (by["Midt AS"]["day"], by["Midt AS"]["terms"]) == (15, 45)
    october = [(f["customer"], f["date"].isoformat()) for f in flows
               if f["month"] == (2026, 10)]
    assert october == [("Slutt AS", "2026-12-07"), ("Midt AS", "2026-12-07")], \
        "30 Oct + 30 + 7 and 15 Oct + 45 + 7 is a Sunday, so the Monday"
    labels = {f["label"] for f in flows if f["month"] == (2026, 10)}
    assert labels == {"Fakturering oktober (ikke sendt), 30 dager",
                      "Fakturering oktober (ikke sendt), 45 dager"}


def test_a_customer_invoiced_through_the_month_is_spread_as_he_is():
    """Invoiced on the 5th, 15th and 25th on 45 days: three landings, not one."""
    history = []
    for day in (5, 15, 25):
        history += _monthly("Løpende AS", day, 45, 30_000.0, start=day * 10)
    flows, _, _ = cashflow._invoice_runs(history, date(2026, 10, 1), HORIZON)
    october = sorted((f["date"].isoformat(), round(f["amount"])) for f in flows
                     if f["month"] == (2026, 10))
    assert october == [("2026-11-26", 30_000), ("2026-12-07", 30_000), ("2026-12-16", 30_000)]


def test_this_month_only_the_days_still_to_come():
    """On the 20th the invoices of the 5th and 15th have gone out; only the
    25th is still to come, and it carries what is left of his month."""
    history = []
    for day in (5, 15, 25):
        history += _monthly("Løpende AS", day, 45, 30_000.0, start=day * 10)
    today = date(2026, 10, 20)
    history += [_row("Løpende AS", date(2026, 10, d), 45, 30_000.0, 900 + d) for d in (5, 15)]
    flows, _, by_month = cashflow._invoice_runs(history, today, today + timedelta(weeks=13))
    october = [(f["date"].isoformat(), round(f["amount"])) for f in flows if f["month"] == (2026, 10)]
    assert october == [("2026-12-16", 30_000)]
    assert by_month[(2026, 10)] == {"low": 30_000.0, "usual": 30_000.0}


def test_usual_is_the_median_and_the_floor_the_lowest_of_three():
    history = _monthly("Kunde AS", 30, 30, 100_000.0)
    history[-2]["amount"] = 250_000.0                 # August: an extra job
    history[-1]["amount"] = 80_000.0                  # September: fewer hours
    _, found, by_month = cashflow._invoice_runs(history, TODAY, HORIZON)
    assert (found[0]["amount"], found[0]["usual"]) == (80_000.0, 100_000.0)
    assert by_month[(2026, 11)] == {"low": 80_000.0, "usual": 100_000.0}


# ----------------------------------------------- the rest, and its one-offs
def test_a_big_job_does_not_come_back_as_normal():
    """At the first customer August had a big one-off job. Averaged in, it
    would come back every month; the median leaves it out, and it is named."""
    history = _monthly("Fast AS", 30, 30, 100_000.0)
    for k, (y, m) in enumerate(MONTHS[1:]):          # April to September
        history.append(_row(f"Kunde {k}", date(y, m, 12), 14, 40_000.0, 500 + k))
    history.append(_row("Storjobb AS", date(2026, 8, 20), 30, 1_300_000.0, 700))
    flows, by_month, measured = cashflow._other_invoicing(
        history, TODAY, HORIZON, 7, None, {"Fast AS"})
    assert measured["nivaa_mnd"] == 40_000.0
    assert measured["uvanlige"] == [{"month": "august 2026", "amount": 1_340_000.0}]
    assert by_month[(2026, 11)] == 40_000.0
    assert {f["label"] for f in flows} >= {"Annen fakturering november (ikke sendt), 14 dager"}, \
        "timed like the ordinary months, not on the big job's 30 days"
    assert all("30 dager" not in f["label"] for f in flows)


def test_the_other_invoicing_is_in_the_expected_line_only():
    history = _monthly("Fast AS", 30, 30, 100_000.0)
    for k, (y, m) in enumerate(MONTHS[1:]):
        history.append(_row(f"Kunde {k}", date(y, m, 12), 14, 40_000.0, 500 + k))
    flows, _, _ = cashflow._other_invoicing(history, TODAY, HORIZON, 7, None, {"Fast AS"})
    assert {f["kind"] for f in flows} == {"new_sales"}


def test_what_is_invoiced_this_month_comes_off_the_other_invoicing():
    history = _monthly("Fast AS", 30, 30, 100_000.0)
    for k, (y, m) in enumerate(MONTHS[1:]):
        history.append(_row(f"Kunde {k}", date(y, m, 12), 14, 40_000.0, 500 + k))
    history.append(_row("Ny AS", date(2026, 10, 2), 14, 15_000.0, 800))
    _, by_month, _ = cashflow._other_invoicing(history, TODAY, HORIZON, 7, None, {"Fast AS"})
    assert by_month[(2026, 10)] == 25_000.0


# ------------------------------------------------- the register and the accounts
def test_a_young_register_keeps_the_accounts():
    history = _monthly("Kunde AS", 10, 30, 10_000.0, months=[(2026, 8), (2026, 9)])
    assert cashflow._register_months(history, TODAY) == 2
    data = _forecast([REVENUE], ar=history)
    assert data["assumptions"]["fakturering_fra"] == "regnskapet"


def test_the_accounts_are_a_check_on_the_register():
    """500 000 kr a month in the accounts, 100 000 kr invoiced: said, not chosen."""
    data = _forecast([REVENUE], ar=_monthly("Kunde AS", 10, 30, 100_000.0))
    assert data["assumptions"]["fakturering_fra"] == "fakturaregisteret"
    nov = data["assumptions"]["fakturering_per_maned"][1]
    assert (nov["month"], nov["fast_vanlig"], nov["regnskapet"]) == ("november", 100_000.0, 500_000.0)
    assert any("Fakturaene sier 100 000 kr i november" in w for w in data["warnings"])


def test_a_month_with_no_invoice_days_past_its_usual_day_leaves_the_committed_line():
    """Usually invoiced on the 15th; on the 28th nothing has gone out. Perhaps
    late, perhaps the contract has ended: the expected line keeps it, the
    committed line does not stand on it."""
    history = _monthly("Midt AS", 15, 45, 50_000.0)
    flows, found, _ = cashflow._invoice_runs(history, date(2026, 10, 28), HORIZON)
    assert (found[0]["committed"], found[0]["why"]) == (
        False, "ingen faktura ennå denne måneden, vanligvis den 15.")
    assert {f["kind"] for f in flows} == {"recurring_usual"}


def test_money_due_on_a_weekend_lands_on_the_monday():
    history = _monthly("Lørdag AS", 30, 30, 10_000.0)
    flows, _, _ = cashflow._invoice_runs(history, TODAY, HORIZON)
    october = [f["date"] for f in flows if f["month"] == (2026, 10)]
    assert october == [date(2026, 12, 7)], "30 Oct + 30 + 7 = Sunday 6 December"
