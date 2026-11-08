"""What the bank figure has paid, by its own date and not the calendar's.

The feed arrives a banking day late. On the 11th the figure is often the
9th's, so the pay day and the VAT of the 10th are in neither the figure nor,
if the forecast goes by the calendar, the forecast.
"""
import asyncio
from datetime import date, timedelta

import cashflow
import commitments
import company
from tests.test_cashflow_build import REVENUE, _cum
from tests.test_settled_terms import _credit, _debit, _dated


# ------------------------------------------------------------- the cut-off
def test_the_bank_figure_covers_up_to_its_last_line():
    assert commitments.paid_by(date(2026, 12, 11), {"latest": "2026-12-09"}) == date(2026, 12, 10)


def test_a_current_feed_or_none_leaves_today():
    assert commitments.paid_by(date(2026, 12, 11), {"latest": "2026-12-11"}) == date(2026, 12, 11)
    assert commitments.paid_by(date(2026, 12, 11), None) == date(2026, 12, 11)
    assert commitments.paid_by(date(2026, 12, 11), {"latest": None}) == date(2026, 12, 11)


# ------------------------------------------------------ taxes, in commitments
def _dated_before(gid, amount, postings, today, account, paid_before, opening=0.0):
    from tests.test_settled_terms import _item, _rows, COLUMNS
    stub_out = {}

    class _Stub:
        async def call(self, tool, args):
            page = postings[args["from"]:args["from"] + args["count"]]
            return {"postings": page, "hasMore": args["from"] + args["count"] < len(postings)}

    original = commitments.mcp
    commitments.mcp = _Stub()
    try:
        stub_out["r"] = asyncio.run(commitments._date_by_term(
            _item(gid, amount), _rows(account, opening), COLUMNS, today, paid_before))
    finally:
        commitments.mcp = original
    parts, paid = stub_out["r"]
    return [(p["due"], p["amount"]) for p in parts], paid


def test_vat_due_yesterday_is_owed_while_the_feed_has_not_shown_it_paid():
    """11 December, the feed at the 9th: the VAT of the 10th is still owed,
    today."""
    parts = _dated_before("mva_oppgjor", 700_000.0, [_credit("2026-11-03", 700_000.0)],
                          date(2026, 12, 11), "2740", date(2026, 12, 10))
    assert parts == ([("2026-12-11", 700_000.0)], 0.0)


def test_once_the_feed_has_the_day_it_counts_as_paid():
    parts = _dated_before("mva_oppgjor", 700_000.0, [_credit("2026-11-03", 700_000.0)],
                          date(2026, 12, 11), "2740", date(2026, 12, 11))
    assert parts == ([], 700_000.0)


# ---------------------------------------------------------- the company tax
def test_company_tax_falls_due_in_two_halves():
    """Booked at year end, paid on 15 February and 15 April. 15 February 2026
    is a Sunday."""
    out, _ = _dated("betalbar_skatt", 200_000.0, [], date(2026, 1, 20), "2500", opening=200_000.0)
    assert [(p["due"], p["amount"]) for p in out[0]] == [("2026-02-16", 100_000.0),
                                                       ("2026-04-15", 100_000.0)]


def test_the_february_half_paid_but_not_booked_is_not_paid_again():
    """The same rule as the VAT on 2740: past its deadline, paid. Read as one
    balance it rolled to April and was paid a second time."""
    out, _ = _dated("betalbar_skatt", 200_000.0, [], date(2026, 3, 1), "2500", opening=200_000.0)
    assert ([(p["due"], p["amount"]) for p in out[0]], out[1]) == ([("2026-04-15", 100_000.0)], 100_000.0)


def test_a_booked_payment_settles_the_february_half():
    out, _ = _dated("betalbar_skatt", 100_000.0, [_debit("2026-02-16", 100_000.0)],
                    date(2026, 3, 1), "2500", opening=200_000.0)
    assert ([(p["due"], p["amount"]) for p in out[0]], out[1]) == ([("2026-04-15", 100_000.0)], 0.0)


def test_instalments_from_the_day_the_tax_is_booked():
    assert commitments._tax_instalments(date(2025, 12, 31)) == [date(2026, 2, 15), date(2026, 4, 15)]
    assert commitments._tax_instalments(date(2026, 3, 1)) == [date(2026, 4, 15), date(2026, 4, 15)]
    assert commitments._tax_instalments(date(2026, 5, 1)) == [date(2027, 2, 15), date(2027, 4, 15)]


# --------------------------------------------------------- the pay day too
def test_a_pay_day_the_feed_has_not_shown_is_still_paid():
    original = company.setting
    company.setting = lambda k, d=None: {"lonn_utbetalingsdag": 10}.get(k, d)
    try:
        today = date(2026, 12, 11)
        horizon = today + timedelta(weeks=13)
        late = [d for _, _, d in cashflow._pay_days(today, horizon, date(2026, 12, 10))]
        current = [d for _, _, d in cashflow._pay_days(today, horizon, today)]
    finally:
        company.setting = original
    assert late[0] == date(2026, 12, 10) and current[0] == date(2027, 1, 8)


def test_the_forecast_pays_the_pay_day_the_feed_has_not_shown():
    """Monday 12 October, the bank figure true up to the 8th: the pay day of
    Friday the 9th is paid in this week, not lost between the two."""
    from tests import test_cashflow_build as b
    import payment_habits

    async def cached():
        return {"bank": 1_000_000.0, "items": [], "paid_before": "2026-10-09"}

    stub = b._Tripletex([REVENUE, _cum("5000 Lønn til ansatte", [100_000.0] * 9)])
    old = cashflow.mcp, cashflow.commitments.cached, company.setting
    cashflow.mcp = b.balance_sheet(stub)
    cashflow.commitments.cached = cached
    company.setting = lambda k, d=None: {"lonn_utbetalingsdag": 10}.get(k, d)
    payment_habits._cache.clear()
    cashflow._payroll_cache.clear()
    try:
        data = asyncio.run(cashflow.build(date(2026, 10, 12)))
    finally:
        cashflow.mcp, cashflow.commitments.cached, company.setting = old
        cashflow._payroll_cache.clear()
    wages = [w["start"] for w in data["weeks"] for i in w["items"] if i["kind"] == "wages"]
    assert wages[0] == "2026-10-12", "the 9th's pay day, in this week"


# ------------------------------------------------------- credited invoices
def test_a_credited_invoice_and_its_credit_note_count_once():
    rows = [{"id": 1, "customerName": "Kunde", "invoiceDate": "2026-08-07", "dueDate": "2026-09-06",
             "amount": 5_200.0, "amountOutstanding": -5_200.0, "isCredited": True},
            {"id": 2, "customerName": "Kunde", "invoiceDate": "2026-08-19", "dueDate": "2026-08-19",
             "amount": -5_200.0, "amountOutstanding": -5_200.0, "isCredited": False}]

    class _Register:
        async def call(self, tool, args):
            first = args["invoiceDateFrom"] == "2026-08-01"
            return {"rows": rows if first and not args.get("from") else []}

    original = cashflow.mcp
    cashflow.mcp = _Register()
    try:
        out, _, _ = asyncio.run(cashflow._open_invoices(
            date(2026, 11, 8), "search_invoices", "Kundefakturaer", "id",
            "amountOutstanding", "customerName", in_kroner=True))
    finally:
        cashflow.mcp = original
    assert [(i["id"], i["amount"]) for i in out] == [(2, -5_200.0)]
