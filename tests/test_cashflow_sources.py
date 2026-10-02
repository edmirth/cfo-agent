"""The forecast is only as good as what it reads.

Every check here guards a defect that was live against the real ledger on
2 October 2026 — found by inspection, confirmed against Tripletex, and each one
pointing the same way: too little money going out.
"""
import asyncio
from datetime import date

import cashflow


COLUMNS = ["Inngående balanse", "Jan", "Feb", "Mars", "April", "Mai", "Juni",
           "Juli", "Aug", "Sept", "Okt", "Utgående saldo"]


def _row(path, monthly):
    """Saldobalanse rows are cumulative; _monthly differences them."""
    cum, running = [], 0.0
    for v in monthly:
        running += v
        cum.append(running)
    return {"path": path, "cells": [0] + cum + [running]}


def _flat(path, value, months=10):
    return _row(path, [value] * months)


# ----------------------------------------------------------- the registers
class _Stub:
    """Stands in for the MCP client, answering in the shape Tripletex uses."""

    def __init__(self, rows):
        self.rows = rows
        self.asked = []

    async def call(self, tool, args):
        self.asked.append(tool)
        # One month's worth, once. _open_invoices walks twelve windows, and a
        # stub that answers them all alike would hand the de-duplication twelve
        # copies to collapse — which is not what any of these checks are about.
        if len(self.asked) > 1 or "supplier" not in tool:
            return {"rows": []}
        # Both registers answer under "rows". The supplier call used to be read
        # as "invoices", a key no response has ever carried.
        return {"rows": self.rows}


def _supplier_rows():
    return [{"voucherId": 1, "supplierName": "A B Matteservice AS",
             "outstandingAmount": 30105.88, "dueDate": "2026-09-30",
             "invoiceDate": "2026-08-31", "invoiceNumber": "28367"},
            {"voucherId": 2, "supplierName": "Pastro AS",
             "outstandingAmount": 23275.0, "dueDate": "2026-09-24",
             "invoiceDate": "2026-08-30", "invoiceNumber": "1921"}]


def _read(rows, id_key="voucherId"):
    stub = _Stub(rows)
    original = cashflow.mcp
    cashflow.mcp = stub
    try:
        return asyncio.run(cashflow._open_invoices(
            date(2026, 10, 2), "search_supplier_invoices", "Leverandørfakturaer",
            id_key, "outstandingAmount", "supplierName"))
    finally:
        cashflow.mcp = original


def test_supplier_invoices_are_actually_read():
    """The bug: the call asked for `invoices`, the response carries `rows`, so
    `.get(...) or []` was empty every single time and every supplier bill was
    dropped before reaching the forecast. The call succeeded, so nothing warned.
    Against the live ledger this showed 0 open bills against 32 969 kr on 2400."""
    bills, warnings = _read(_supplier_rows())
    assert len(bills) == 2, f"supplier register came back empty: {bills}"
    assert abs(sum(b["amount"] for b in bills) - 53380.88) < 0.01
    assert {b["name"] for b in bills} == {"A B Matteservice AS", "Pastro AS"}


def test_a_credit_note_comes_back_as_money_in():
    """outstandingAmount is negative on a credit note, and _schedule_payments
    negates, so it has to end up reducing what leaves."""
    rows = _supplier_rows() + [{"voucherId": 3, "supplierName": "Bimo AS",
                                "outstandingAmount": -22375.0,
                                "dueDate": "2026-09-04",
                                "invoiceDate": "2026-08-21"}]
    bills, _ = _read(rows)
    flows = cashflow._schedule_payments(bills, date(2026, 10, 2))
    credit = next(f for f in flows if "Bimo" in f["label"])
    assert credit["amount"] > 0, "a credit note cannot take money out"


def test_a_row_without_an_id_does_not_swallow_the_next_one():
    """None went into `seen`, so the first id-less row made every later one
    look like a duplicate."""
    rows = [dict(r, voucherId=None) for r in _supplier_rows()]
    bills, _ = _read(rows)
    assert len(bills) == 2, f"one row ate the other: {bills}"


def test_the_warning_says_which_register_was_short():
    """Both registers used one sentence, so five truncation warnings on the
    front page told nobody whether sales or purchases were cut off."""
    _, warnings = _read([dict(_supplier_rows()[0], voucherId=i)
                         for i in range(100)])
    assert warnings, "a full page must be reported as possibly truncated"
    assert "leverandørfakturaer" in warnings[0].lower()
    assert "kunde" not in warnings[0].lower()


def test_the_months_are_named_in_norwegian():
    _, warnings = _read([dict(_supplier_rows()[0], voucherId=i)
                         for i in range(100)])
    assert "oktober 2026" in warnings[0], warnings[0]
    for english in ("October", "September", "March", "June"):
        assert english not in warnings[0]


# ------------------------------------------------------------- the rates
def test_a_month_outside_the_window_does_not_crash_the_forecast():
    """Credit notes below half the median and heavy months above double it can
    leave nothing in the keep window. The note quoted the average before it was
    computed, divided by zero, and took the whole forecast down with it."""
    rows = [_row("6000 Driftskostnader", [-10.0, -5.0, 30.0, 40.0, 0.0])]
    rates, notes = cashflow._run_rates(rows, COLUMNS[:6] + COLUMNS[-1:])
    assert rates["opex"] == 12.5, "falls back to the median, and survives"
    assert notes, "and says which months it set aside"


def test_a_month_far_above_the_median_is_named_too():
    """Only the low months were named. A high month was dropped in silence,
    pulling the cost rate down — the dangerous direction."""
    rows = [_row("6000 Driftskostnader", [100.0, 100.0, 100.0, 900.0, 0.0])]
    rates, notes = cashflow._run_rates(rows, COLUMNS[:6] + COLUMNS[-1:])
    assert rates["opex"] == 100.0
    assert any("over de andre" in n for n in notes), notes


def test_cost_of_goods_and_pension_are_in_the_forecast():
    """4000-4999 and 5100-5999 were in no range at all: varekjøp,
    underentreprise, pensjon and yrkesskade did not exist in the forecast.
    Against the live ledger that was 116 463 kr a month missing, against a
    modelled opex of 156 399."""
    rows = [_flat("4300 Innkjøp av varer for videresalg", 80000.0),
            _flat("4500 Fremmedytelse og underentreprise", 10000.0),
            _flat("5945 Pensjonsforsikring for ansatte", 27000.0),
            _flat("5990 Annen personalkostnad", 4000.0),
            _flat("6300 Leie lokale", 23000.0)]
    rates, _ = cashflow._run_rates(rows, COLUMNS)
    assert rates["opex"] == 144000.0, (
        f"only {rates['opex']} of 144 000 kr of monthly cost reached the model")


def test_arbeidsgiveravgift_is_not_charged_twice():
    """5400/5401 stay out of opex: commitments dates them from their own
    balance, and taking them here as well pays them twice."""
    rows = [_flat("5400 Arbeidsgiveravgift", 140000.0),
            _flat("5401 Arbeidsgiveravgift av opptjente feriepenger", 14000.0),
            _flat("6300 Leie lokale", 23000.0)]
    rates, _ = cashflow._run_rates(rows, COLUMNS)
    assert rates["opex"] == 23000.0, "AGA leaked into the operating costs"


def test_feriepenger_still_stays_out_of_the_pay_day_run():
    """The ranges moved; this must not have."""
    rows = [_flat("5000 Lønn til ansatte", 900000.0),
            _flat("5020 Feriepenger", 100000.0),
            _flat("5030 Sykepenger", 4000.0)]
    rates, _ = cashflow._run_rates(rows, COLUMNS)
    assert rates["wages"] - rates["wages_cash"] == 100000.0
    assert rates["wages_cash"] == 904000.0


# ------------------------------------------------- what nothing else carries
def test_annen_gjeld_is_scheduled_by_someone():
    """2990/2991 is never invoiced, so the payables list cannot see it, and it
    was leaving the forecast entirely. Money owed to the owner stays out: that
    due date is an assumption, not a fact."""
    assert "annen_gjeld" in cashflow.STATUTORY_FROM_COMMITMENTS
    assert "ansatte_eiere" not in cashflow.STATUTORY_FROM_COMMITMENTS
    assert "leverandorgjeld" not in cashflow.STATUTORY_FROM_COMMITMENTS
    assert "skyldig_lonn" not in cashflow.STATUTORY_FROM_COMMITMENTS
