"""The forecast assembled end to end, with Tripletex and the commitments stubbed.

The reconciliations against the general ledger, and the double counts between
what commitments already dates and what this module schedules itself, only
exist inside `build`. Testing the helpers around them leaves exactly the gaps
these checks were written for.
"""
import asyncio
from datetime import date

import cashflow
import company

TODAY = date(2026, 10, 5)
COLUMNS = ["Inngående balanse", "Jan", "Feb", "Mars", "April", "Mai", "Juni",
           "Juli", "Aug", "Sept", "Okt", "Utgående saldo"]


def _row(path, cells):
    return {"path": path, "cells": cells}


def _cum(path, monthly):
    """Saldobalanse rows are cumulative; `_monthly` differences them back."""
    cells, running = [0], 0.0
    for v in monthly:
        running += v
        cells.append(running)
    return _row(path, cells + [running])


class _Tripletex:
    def __init__(self, rows, ar=(), ap=()):
        self.rows, self.ar, self.ap = rows, list(ar), list(ap)
        self.asked = []

    async def call(self, tool, args=None):
        self.asked.append(tool)
        if tool == "fetch_report":
            return {"table": {"rows": self.rows,
                              "columns": [{"name": c} for c in COLUMNS]}}
        if tool == "search_invoices":
            return {"rows": self.ar if self.asked.count("search_invoices") == 1 else []}
        if tool == "search_supplier_invoices":
            return {"rows": self.ap if self.asked.count("search_supplier_invoices") == 1 else []}
        return {}


def _forecast(rows, ar=(), ap=(), bank=1_000_000.0, items=(), settings=None):
    """Run `build` against a stubbed ledger. Returns the payload."""
    stub = _Tripletex(rows, ar, ap)
    old_mcp, old_cached = cashflow.mcp, cashflow.commitments.cached
    old_setting = company.setting
    conf = {"lonn_utbetalingsdag": 10, **(settings or {})}

    async def cached():
        return {"bank": bank, "items": list(items)}

    cashflow.mcp = stub
    cashflow.commitments.cached = cached
    company.setting = lambda k, d=None: conf.get(k, d)
    try:
        return asyncio.run(cashflow.build(TODAY))
    finally:
        cashflow.mcp, cashflow.commitments.cached = old_mcp, old_cached
        company.setting = old_setting


def _kinds(data, kind):
    return [i for w in data["weeks"] for i in w["items"] if i["kind"] == kind]


# ------------------------------------- the ledger reconciliations run at all
def test_a_blank_closing_cell_does_not_switch_off_the_1500_check():
    """A blank cell means the account did not move, not that it went to zero.

    The check required the *last* cell to be numeric, so in any month where
    1500 had not moved yet the whole reconciliation skipped silently: no
    residual in the forecast, no warning in the answer. `_monthly` says as
    much in as many words, and `_closing_range` beside it already read it
    correctly.
    """
    rows = [_row("1500 Kundefordringer", [0, 2_539_600, None])]
    data = _forecast(rows)
    assert _kinds(data, "ar_unmatched"), "the ledger's receivables went missing"
    assert any("Konto 1500" in w for w in data["warnings"])


def test_receivables_outside_1500_are_part_of_the_same_reconciliation():
    rows = [_row("1505 Kundefordringer, utland", [0, 400_000, 400_000])]
    data = _forecast(rows)
    assert _kinds(data, "ar_unmatched")


def test_an_absent_payables_account_raises_no_warning():
    """None and zero are different answers. A company that keeps no 2400 is
    not a company whose register is overstated, and inventing a zero there
    sends someone looking for a gap that does not exist."""
    ap = [{"voucherId": 1, "supplierName": "Leverandør",
           "outstandingAmount": 50_000.0, "dueDate": "2026-10-20",
           "invoiceDate": "2026-09-20"}]
    data = _forecast([], ap=ap)
    assert not any("2400" in w for w in data["warnings"])


# ------------------------- what commitments already dates, and this re-dates
REVENUE = _cum("3000 Salgsinntekt", [-400_000.0] * 10)


def _october_vat(data):
    return [i for i in _kinds(data, "vat_future") if "oktober" in i["label"]]


def test_vat_already_accrued_this_month_is_not_scheduled_twice():
    """commitments dates the 2700-2739 balance to the running term's deadline.

    The expected loop then added a full month's VAT for the current month on
    that same date, so everything already booked went out twice — a margin
    that grows through the month to nearly a whole month's VAT. Only the part
    still to be invoiced belongs to the forecast.
    """
    accrued = _cum("2700 Utgående mva", [0.0] * 9 + [-100_000.0])
    full = _october_vat(_forecast([REVENUE]))
    assert full, "a month with nothing booked still owes its own VAT"
    assert round(full[0]["amount"]) == -100_000

    netted = _october_vat(_forecast([REVENUE, accrued]))
    assert not netted, "the whole month was already booked, so nothing is left"


def test_a_part_booked_month_schedules_only_the_remainder():
    accrued = _cum("2700 Utgående mva", [0.0] * 9 + [-60_000.0])
    left = _october_vat(_forecast([REVENUE, accrued]))
    assert left and round(left[0]["amount"]) == -40_000


def test_later_months_keep_their_whole_vat():
    """Only the current month overlaps the running balance."""
    accrued = _cum("2700 Utgående mva", [0.0] * 9 + [-100_000.0])
    data = _forecast([REVENUE, accrued])
    nov = [i for i in _kinds(data, "vat_future") if "november" in i["label"]]
    assert not nov or round(nov[0]["amount"]) == -100_000
