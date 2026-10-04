"""The opening balance is the bank's, and what the bank has paid is not paid twice.

Pinned to Ullensaker as measured on 4 October 2026: the ledger said
2 625 898,93 kr on 1920, the bank was ahead by everything that had landed
since August and not been posted.
"""
import asyncio
from datetime import date

import bankgap
import cashflow
import company
from tests.test_cashflow_build import COLUMNS, TODAY, _Tripletex, _cum, _kinds, _row


def _period(account, start, status="open"):
    end_month = int(start[5:7]) % 12 + 1
    end_year = int(start[:4]) + (1 if end_month == 1 else 0)
    return {"accountNumber": account, "status": status,
            "period": {"start": start, "end": f"{end_year}-{end_month:02d}-01"},
            "url": f"https://tripletex.no/recon/{account}/{start}"}


def _answer(unmatched=0.0, matched=0.0, postings=0.0, lines=(), count=None,
            truncated=False, inflow=None, outflow=None):
    lines = list(lines)
    return {"truncated": truncated, "unmatched": lines,
            "totals": {
                "unmatched": {"count": count if count is not None else len(lines),
                              "sum": unmatched,
                              "in": inflow if inflow is not None else max(unmatched, 0),
                              "out": outflow if outflow is not None else min(unmatched, 0)},
                "matched": {"sum": matched},
                "awaitingApproval": {"sum": 0.0},
                "unmatchedPostings": {"count": 1 if postings else 0, "sum": postings}}}


PERIODS = {"accounts": [{"number": "1920", "name": "Bedriftskonto"},
                        {"number": "1940", "name": "Bankinnskudd utland"}],
           "periods": [_period("1920", "2026-08-01"), _period("1920", "2026-09-01"),
                       _period("1920", "2026-10-01"),
                       _period("1940", "2026-08-01", "not_started"),
                       _period("1940", "2026-09-01", "not_started"),
                       _period("1940", "2026-10-01", "not_started")]}

# What Tripletex answered for 1920, totals only, and the ledger's own months.
MEASURED = {
    ("1920", "2026-08-01"): _answer(unmatched=-21251.41, matched=-89462.16),
    ("1920", "2026-09-01"): _answer(unmatched=321480.26, matched=536030.40,
                                    postings=41479.0, count=107,
                                    inflow=582901.0, outflow=-261420.74),
    ("1920", "2026-10-01"): _answer(unmatched=134375.44, count=9,
                                    inflow=163761.72, outflow=-29386.28),
}
MOVES = {("1920", 2026, 8): -89462.16, ("1920", 2026, 9): 577509.40,
         ("1920", 2026, 10): 0.0}


# ------------------------------------------------------------------ measuring
def test_the_gap_is_bank_movement_less_ledger_movement_over_every_month():
    """134 375 was October alone. September's unposted receipts were most of it."""
    gap = bankgap.measure(PERIODS, MEASURED, MOVES, {"1920": 2625898.93})
    assert round(gap["adjustment"], 2) == round(-21251.41 + 280001.26 + 134375.44, 2)
    assert gap["lines"] == 107 + 9   # August is stubbed without its lines
    assert gap["unknown"] == []
    assert not gap["approximate"]


def test_a_hidden_salary_posting_does_not_pull_the_balance_down():
    """unmatchedPostings leaves out salary under the privacy setting.

    Payroll of 500 000 booked on the 20th, its bank line not yet matched: the
    bank and the books agree, and the gap is zero. Reading the lists alone
    would see an unmatched -500 000 bank line with no posting against it.
    """
    answer = _answer(unmatched=-500000.0, matched=100000.0, postings=0.0)
    gap = bankgap.measure(
        {"accounts": [], "periods": [_period("1920", "2026-09-01")]},
        {("1920", "2026-09-01"): answer},
        {("1920", 2026, 9): -400000.0}, {"1920": 1.0})
    assert abs(gap["adjustment"]) < 0.01


def test_without_the_ledger_month_it_falls_back_to_the_lists_and_says_so():
    gap = bankgap.measure(
        {"accounts": [], "periods": [_period("1920", "2025-12-01")]},
        {("1920", "2025-12-01"): _answer(unmatched=1000.0, postings=300.0)},
        {}, {"1920": 1.0})
    assert gap["adjustment"] == 700.0
    assert gap["approximate"]


def test_an_empty_month_without_its_ledger_is_not_called_approximate():
    gap = bankgap.measure(
        {"accounts": [], "periods": [_period("1920", "2025-12-01", "closed")]},
        {("1920", "2025-12-01"): _answer(matched=162573.65)}, {}, {"1920": 1.0})
    assert gap["adjustment"] == 0.0 and not gap["approximate"]


# ------------------------------------------------------- unknown is not zero
def test_an_account_never_reconciled_with_money_on_it_is_unknown():
    gap = bankgap.measure(PERIODS, MEASURED, MOVES,
                          {"1920": 2625898.93, "1940": 12000.0})
    assert any("1940" in u and "aldri avstemt" in u for u in gap["unknown"])


def test_an_empty_account_never_reconciled_is_not_a_finding():
    gap = bankgap.measure(PERIODS, MEASURED, MOVES, {"1920": 1.0, "1940": 0.0})
    assert gap["unknown"] == []


def test_a_month_skipped_in_the_middle_is_unknown():
    periods = {"accounts": [], "periods": [
        _period("1920", "2026-08-01"), _period("1920", "2026-09-01", "not_started"),
        _period("1920", "2026-10-01")]}
    gap = bankgap.measure(periods, MEASURED, MOVES, {"1920": 1.0})
    assert any("sept 2026" in u for u in gap["unknown"])


def test_a_failed_or_truncated_month_is_unknown_and_adds_nothing():
    answers = dict(MEASURED)
    answers[("1920", "2026-09-01")] = RuntimeError("503")
    answers[("1920", "2026-10-01")] = _answer(unmatched=99.0, truncated=True)
    gap = bankgap.measure(PERIODS, answers, MOVES, {"1920": 1.0})
    assert len(gap["unknown"]) == 2
    assert round(gap["adjustment"], 2) == -21251.41


# ------------------------------------------------------------- ledger months
def test_january_is_measured_from_the_opening_balance_and_blanks_carry():
    cols = ["Inngående balanse", "Jan", "Feb", "Mars", "Utgående saldo"]
    rows = [_row("1920 Bedriftskonto", [1000.0, 1500.0, None, 1200.0, 1200.0]),
            _row("3000 Salgsinntekt", [0, -5, -9, -12, -12])]
    moves = bankgap.ledger_moves(rows, cols, 2026)
    assert moves == {("1920", 2026, 1): 500.0, ("1920", 2026, 2): 0.0,
                     ("1920", 2026, 3): -300.0}


# ------------------------------------------------------------------- settling
AR = [{"name": "As Bækkelagshallen", "number": 6747, "due": "2026-10-30", "amount": 48813.0},
      {"name": "As Bækkelagshallen", "number": 6623, "due": "2026-09-30", "amount": 48813.0},
      {"name": "Skanska Norge AS", "number": 1, "due": "2026-09-01", "amount": 30000.0},
      {"name": "Skanska Norge AS", "number": 2, "due": "2026-09-15", "amount": 20000.0},
      {"name": "Stø Entreprenør AS", "number": 3, "due": "2026-09-20", "amount": 10459.0}]


def _line(name, amount, when="2026-09-30"):
    return {"account": "1920", "date": when, "name": name, "amount": amount}


def test_an_exact_payment_settles_the_oldest_invoice_of_that_amount():
    left, paid = bankgap.settle(AR, [_line("AS BÆKKELAGSHALLEN", 48813)], +1)
    assert [p["number"] for p in paid] == [6623]
    assert {i["number"] for i in left} == {6747, 1, 2, 3}


def test_a_lump_payment_settles_that_customer_oldest_first():
    left, paid = bankgap.settle(AR, [_line("SKANSKA NORGE AS", 43084)], +1)
    assert [(p["number"], p["amount"]) for p in paid] == [(1, 30000.0), (2, 13084.0)]
    assert next(i for i in left if i["number"] == 2)["amount"] == 6916.0


def test_the_feed_spelling_of_aeoa_still_matches():
    left, paid = bankgap.settle(AR, [_line("St! Entrepren!r AS", 10459)], +1)
    assert [p["number"] for p in paid] == [3]


def test_money_from_nobody_on_the_list_settles_nothing():
    left, paid = bankgap.settle(AR, [_line("NAV", 44304), _line("Varekjøp", -900)], +1)
    assert paid == [] and len(left) == len(AR)


def test_outgoing_lines_settle_supplier_bills_not_customer_invoices():
    ap = [{"name": "Alpha Revisjon AS", "number": None, "due": "2026-09-28",
           "amount": 76375.0}]
    lines = [_line("Alpha Revisjon AS", -76375), _line("ALPHA REVISJON AS", 5000)]
    left, paid = bankgap.settle(ap, lines, -1)
    assert left == [] and paid[0]["amount"] == 76375.0


# ---------------------------------------------------------- through the forecast
class _WithBank(_Tripletex):
    def __init__(self, rows, ar=(), periods=None, answers=None):
        super().__init__(rows, ar)
        self.periods, self.answers = periods or {}, answers or {}

    async def call(self, tool, args=None):
        if tool == "get_bank_reconciliation_periods":
            return self.periods
        if tool == "get_unmatched_bank_transactions":
            return self.answers[(args["accountNumber"], args["date"])]
        return await super().call(tool, args)


def _build(stub, bank):
    old_mcp, old_cached, old_setting = cashflow.mcp, cashflow.commitments.cached, company.setting

    async def cached():
        return {"bank": bank, "items": []}

    cashflow.mcp, cashflow.commitments.cached = stub, cached
    company.setting = lambda k, d=None: {"lonn_utbetalingsdag": 10}.get(k, d)
    try:
        return asyncio.run(cashflow.build(TODAY))
    finally:
        cashflow.mcp, cashflow.commitments.cached, company.setting = old_mcp, old_cached, old_setting


def test_the_forecast_opens_on_the_bank_and_does_not_collect_a_paid_invoice_twice():
    rows = [_cum("1920 Bedriftskonto", [0] * 10),
            _cum("1500 Kundefordringer", [0] * 8 + [48813, 0]),
            _cum("3000 Salgsinntekt", [-100000] * 10)]
    ar = [{"id": 1, "customerName": "As Bækkelagshallen", "invoiceNumber": 6623,
           "dueDate": "2026-09-30", "invoiceDate": "2026-09-01",
           "amountOutstanding": 48813.0}]
    periods = {"accounts": [{"number": "1920", "name": "Bedriftskonto"}],
               "periods": [_period("1920", "2026-10-01")]}
    answers = {("1920", "2026-10-01"): _answer(
        unmatched=48813.0, lines=[{"postedDate": "2026-10-01", "amountCurrency": 48813.0,
                                   "description": "AS BÆKKELAGSHALLEN"}])}
    data = _build(_WithBank(rows, ar, periods, answers), bank=1_000_000.0)

    assert data["opening"] == 1_048_813.0
    assert data["bank"]["booked"] == 1_000_000.0
    assert data["bank"]["settled_ar_count"] == 1
    assert not _kinds(data, "ar") and not _kinds(data, "ar_late")
    # The ledger still has the invoice on 1500, the register still lists it:
    # settling it in the forecast must not read as a gap between the two.
    assert not _kinds(data, "ar_unmatched")
    assert data["ar_open"] == []
    note = cashflow._opening_note(data["bank"])
    assert "1 transaksjoner" in note and "2026-10-01" in note and "1 000 000" in note


def test_an_unreadable_reconciliation_opens_on_the_books_and_says_so():
    class _Broken(_Tripletex):
        async def call(self, tool, args=None):
            if tool == "get_bank_reconciliation_periods":
                raise RuntimeError("503")
            return await super().call(tool, args)

    rows = [_cum("1920 Bedriftskonto", [0] * 10)]
    data = _build(_Broken(rows), bank=500_000.0)
    assert data["opening"] == 500_000.0
    assert data["bank"]["adjustment"] is None
    assert any("Bankavstemmingen" in w for w in data["warnings"])
    assert "ukjent" in cashflow._opening_note(data["bank"])
