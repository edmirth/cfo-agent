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
from tests._legacy_balance import balance_sheet

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

    cashflow.mcp = balance_sheet(stub)
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


def _october_sales(data):
    return [i for i in _kinds(data, "new_sales") if "oktober" in i["label"]]


def _invoice(amount, invoiced, due, ident=1):
    return {"id": ident, "customerName": "Kunde", "amountOutstanding": amount,
            "invoiceDate": invoiced, "dueDate": due, "invoiceNumber": str(ident)}


def test_invoicing_already_issued_this_month_is_not_forecast_again():
    """The opex leg has always guarded the current month — "this month's bills
    are already in the payables above". The revenue leg never did, so an
    invoice already out, with a due date of its own in the committed line, was
    collected a second time as "Fakturering oktober, betalt"."""
    full = _october_sales(_forecast([REVENUE]))
    assert full and round(full[0]["amount"]) == 500_000, "400 000 kr plus mva"

    issued = [_invoice(500_000.0, "2026-10-01", "2026-10-31")]
    assert not _october_sales(_forecast([REVENUE], ar=issued)), \
        "the whole month was already invoiced, so nothing is left to forecast"


def test_a_part_invoiced_month_forecasts_only_the_remainder():
    issued = [_invoice(200_000.0, "2026-10-01", "2026-10-31")]
    left = _october_sales(_forecast([REVENUE], ar=issued))
    assert left and round(left[0]["amount"]) == 300_000


def test_an_invoice_already_paid_this_month_is_not_forecast_again():
    """Invoiced on the 1st and paid on the 3rd: its money is in the opening
    balance. The open list leaves a paid invoice out, so it was not netted
    off, and the month's invoicing collected the same 200 000 kr again."""
    paid = [{**_invoice(0.0, "2026-10-01", "2026-10-31"), "amount": 200_000.0}]
    left = _october_sales(_forecast([REVENUE], ar=paid))
    assert left and round(left[0]["amount"]) == 300_000


def test_a_cancelled_invoice_and_its_credit_note_net_to_nothing():
    rows = [{**_invoice(0.0, "2026-10-01", "2026-10-31", 1), "amount": 100_000.0,
             "isCredited": True},
            {**_invoice(0.0, "2026-10-02", "2026-10-02", 2), "amount": -100_000.0}]
    left = _october_sales(_forecast([REVENUE], ar=rows))
    assert left and round(left[0]["amount"]) == 500_000


def test_last_months_invoices_do_not_reduce_this_month():
    """September's invoicing is collected in the committed line and says
    nothing about what October will bill."""
    issued = [_invoice(500_000.0, "2026-09-30", "2026-10-30")]
    left = _october_sales(_forecast([REVENUE], ar=issued))
    assert left and round(left[0]["amount"]) == 500_000


# ------------------------------- running costs, as they leave the account
# 400 000 kr a month invoiced, and input VAT measured at 40 % of output VAT:
# 100 000 kr out, 40 000 kr in, both standing on the accounts since January
# so this month has accrued none of its own.
VAT_40 = [_cum("2700 Utgående mva", [-100_000.0] + [0.0] * 9),
          _cum("2710 Inngående mva", [40_000.0] + [0.0] * 9)]


def _rent(booked_this_month=0.0):
    return _cum("6300 Leie lokaler", [100_000.0] * 9 + [booked_this_month])


def _opex(data, month):
    return [i for i in _kinds(data, "opex") if month in i["label"]]


def test_running_costs_are_paid_with_their_vat():
    """The VAT forecast deducts input VAT from what is paid over. The bills
    that VAT sits on were paid at their P&L figure, which has none — so the
    deduction was taken and the VAT it deducts was never paid."""
    data = _forecast([REVENUE, _rent()] + VAT_40)
    nov = _opex(data, "november")
    assert nov and round(nov[0]["amount"]) == -140_000, \
        "100 000 kr of costs plus the 40 000 kr of input VAT the deduction assumes"
    assert "inkl. moms" in nov[0]["label"]
    assert round(data["assumptions"]["mva_paa_kostnader"]) == 40_000


def test_no_vat_goes_on_the_costs_when_none_is_deducted():
    """Unmeasured, the deduction is zero, so is the VAT on the bills."""
    data = _forecast([REVENUE, _rent()])
    nov = _opex(data, "november")
    assert nov and round(nov[0]["amount"]) == -100_000
    assert "moms" not in nov[0]["label"]


def test_the_rest_of_this_month_is_charged():
    """On the 5th most of the month's bills have not arrived. The opex leg
    started next month, so they were in no line at all."""
    data = _forecast([REVENUE, _rent()] + VAT_40)
    october = _opex(data, "oktober")
    assert october and round(october[0]["amount"]) == -140_000
    assert "resten" in october[0]["label"]


def test_only_the_unbooked_part_of_this_month_is_charged():
    """A bill booked this month is in the payables, or paid out of the opening
    balance. Charging the whole month as well paid it twice."""
    data = _forecast([REVENUE, _rent(booked_this_month=60_000.0)] + VAT_40)
    october = _opex(data, "oktober")
    assert october and round(october[0]["amount"]) == -56_000, \
        "40 000 kr still to come, plus its share of the input VAT"
    assert round(data["assumptions"]["kostnader_bokfort_denne_maneden"]) == 60_000


def test_a_heavy_month_already_booked_adds_nothing():
    data = _forecast([REVENUE, _rent(booked_this_month=150_000.0)] + VAT_40)
    assert not _opex(data, "oktober"), "never a negative cost"


def test_next_month_ignores_what_this_month_booked():
    data = _forecast([REVENUE, _rent(booked_this_month=60_000.0)] + VAT_40)
    nov = _opex(data, "november")
    assert nov and round(nov[0]["amount"]) == -140_000


# ------------------------------------ the fixed bills, in the committed line
def _bill(ident, supplier, amount, issued, terms=14, outstanding=0.0):
    from datetime import timedelta
    due = date.fromisoformat(issued) + timedelta(days=terms)
    return {"voucherId": ident, "supplierId": abs(hash(supplier)) % 10_000,
            "supplierName": supplier, "amountCurrency": amount,
            "invoiceDate": issued, "dueDate": due.isoformat(),
            "outstandingAmount": outstanding, "currency": "NOK"}


def _monthly_bills(supplier, amounts, months, day=1, terms=14, first_id=100):
    return [_bill(first_id + i, supplier, a, f"2026-{m:02d}-{day:02d}", terms)
            for i, (m, a) in enumerate(zip(months, amounts))]


RENT = _monthly_bills("Gårdeier AS", [60_000.0] * 4, [6, 7, 8, 9])


def _fixed(data):
    return _kinds(data, "fixed")


def test_a_monthly_rent_is_in_the_committed_line():
    """The floor had payroll and the tax dates and none of the rent. Placed on
    its usual due date, the 15th, through the window's end."""
    data = _forecast([], ap=RENT)
    fixed = _fixed(data)
    assert [round(f["amount"]) for f in fixed] == [-60_000] * 3, \
        "15 October, November and December; January's falls after the window"
    assert all(f["scenario"] == "committed" for f in fixed)
    assert data["fixed_costs"][0]["name"] == "Gårdeier AS"
    assert data["fixed_costs"][0]["cadence"] == "månedlig"


def test_a_bill_that_follows_sales_is_not_fixed():
    swings = _monthly_bills("Byggevare AS", [40_000.0, 60_000.0, 45_000.0, 70_000.0],
                            [6, 7, 8, 9])
    data = _forecast([], ap=swings)
    assert not _fixed(data) and not data["fixed_costs"]


def test_a_bill_already_arrived_this_month_is_not_placed_again():
    """October's rent is in the payables with its own due date."""
    october = _bill(200, "Gårdeier AS", 60_000.0, "2026-10-01", outstanding=60_000.0)
    data = _forecast([], ap=RENT + [october])
    assert len(_fixed(data)) == 2, "November and December only"
    assert _kinds(data, "ap"), "October's own bill pays from the payables"


def test_a_bill_late_this_month_is_placed_now():
    """Due on the 3rd, today is the 5th, and nothing has come: still owed."""
    rent = _monthly_bills("Gårdeier AS", [60_000.0] * 4, [6, 7, 8, 9], terms=2)
    data = _forecast([], ap=rent)
    assert any(i["kind"] == "fixed" for i in data["weeks"][0]["items"])


def test_a_quarterly_bill_lands_only_in_its_own_months():
    insurance = _monthly_bills("Forsikring AS", [30_000.0] * 3, [1, 4, 7],
                               day=10, terms=30)
    data = _forecast([], ap=insurance)
    fixed = _fixed(data)
    assert [round(f["amount"]) for f in fixed] == [-30_000], \
        "October's bill, paid 9 November; January's is after the window"
    assert data["fixed_costs"][0]["cadence"] == "kvartalsvis"


def test_two_months_of_four_is_not_a_pattern():
    data = _forecast([], ap=_monthly_bills("Ny AS", [10_000.0] * 2, [8, 9]))
    assert not _fixed(data)


def test_the_expected_line_does_not_move():
    """The same rent is inside the running costs. Counted in both lines it
    would leave twice; the expected line must end where it did."""
    costs = [_cum("6300 Leie lokaler", [60_000.0] * 9 + [0.0])]
    without = _forecast(costs)
    with_rent = _forecast(costs, ap=RENT)
    assert _fixed(with_rent)
    assert round(with_rent["weeks"][-1]["expected_close"]) == \
        round(without["weeks"][-1]["expected_close"])
    assert with_rent["weeks"][-1]["committed_close"] < \
        without["weeks"][-1]["committed_close"], "the floor carries the rent now"


def test_fixed_bills_above_the_rate_never_give_money_back():
    costs = [_cum("6300 Leie lokaler", [20_000.0] * 9 + [0.0])]
    data = _forecast(costs, ap=RENT)
    assert all(i["amount"] <= 0 for i in _kinds(data, "opex"))
    assert not _opex(data, "november"), "the rent covers the whole rate"


# ----------------------------- when the running costs leave, through the month
MATERIALS = [_cum("4000 Varekjøp", [100_000.0] * 9 + [0.0])]


def _variable_bills(day, terms, n=12):
    """Bills that swing too much to be fixed, all dated on `day`."""
    return [_bill(300 + i, "Byggevare AS", 40_000.0 if i % 2 else 70_000.0,
                  f"2026-{1 + i % 9:02d}-{day:02d}", terms) for i in range(n)]


def _week_of(data, label_part):
    return [w["start"] for w in data["weeks"]
            for i in w["items"] if i["kind"] == "opex" and label_part in i["label"]]


def test_bills_early_in_the_month_are_paid_mid_month():
    """Dated around the 6th on fourteen days: paid around the 18th, not in a
    lump on the last day of the month."""
    data = _forecast(MATERIALS, ap=_variable_bills(6, 14))
    assert _week_of(data, "november, fakturert 1.–7.") == ["2026-11-16"]
    nov = _opex(data, "november")
    assert len(nov) == 1 and round(nov[0]["amount"]) == -100_000
    assert data["assumptions"]["kostnadsprofil"]["measured"] is True


def test_bills_late_in_the_month_are_paid_the_next():
    """Dated the 25th on thirty days: November's costs leave in December, and
    December's after the window — as sales collected after it do."""
    data = _forecast(MATERIALS, ap=_variable_bills(25, 30))
    assert _week_of(data, "november") == ["2026-12-21"]
    assert not _opex(data, "desember"), "paid 25 January, after the window"


def test_spreading_moves_the_costs_not_the_amount():
    lump = _forecast(MATERIALS)
    spread = _forecast(MATERIALS, ap=_variable_bills(6, 14))
    total = lambda d: round(sum(i["amount"] for i in _kinds(d, "opex")))
    assert total(lump) == total(spread) == -300_000


def test_too_few_bills_keep_the_month_end():
    data = _forecast(MATERIALS, ap=_variable_bills(6, 14, n=5))
    assert not any("fakturert" in i["label"] for i in _kinds(data, "opex"))
    assert data["assumptions"]["kostnadsprofil"]["measured"] is False


def test_fixed_bills_do_not_shape_the_profile():
    """Rent on the 1st is placed on its own date; it says nothing about when
    the materials come."""
    data = _forecast(MATERIALS, ap=RENT + _variable_bills(6, 14, n=8))
    assert data["assumptions"]["kostnadsprofil"]["bills"] == 8
    assert data["assumptions"]["kostnadsprofil"]["measured"] is False


def test_one_large_bill_does_not_set_the_pattern():
    """A machine bought once on long terms is not when the supplies are paid."""
    machine = _bill(900, "Maskin AS", 1_250_000.0, "2026-09-18", terms=65)
    data = _forecast(MATERIALS, ap=_variable_bills(6, 14) + [machine])
    periods = data["assumptions"]["kostnadsprofil"]["periods"]
    early = next(p for p in periods if p["from"] == 1)
    assert early["share"] > 0.75 and early["terms"] == 14
    lone = next(p for p in periods if p["from"] == 15)
    assert lone["terms"] == 14, "one bill alone does not set its period's terms"


def test_the_rest_of_this_month_falls_in_the_days_still_to_come():
    profile = {"measured": True, "bills": 20, "periods": [
        {"from": 1, "to": 7, "share": 0.5, "terms": 0},
        {"from": 22, "to": 31, "share": 0.5, "terms": 0}]}
    parts = cashflow._cost_parts(profile, date(2026, 10, 1), date(2026, 10, 20), True)
    assert parts == [(date(2026, 10, 26), 1.0, "fakturert 22.–31.")], \
        "the first week is over; what is not booked yet comes late in the month"
    later = cashflow._cost_parts(profile, date(2026, 11, 1), date(2026, 10, 20), False)
    assert [p[1] for p in later] == [0.5, 0.5]


# --------------------------------------- a half-read forecast expires early
class _Broken(_Tripletex):
    """Answers the reports and drops one register, the way a 503 does."""

    def __init__(self, rows, fail="search_supplier_invoices"):
        super().__init__(rows)
        self.failing = fail

    async def call(self, tool, args=None):
        if tool == self.failing:
            raise RuntimeError("503 fra Tripletex")
        return await super().call(tool, args)


def _forecast_with(stub):
    old_mcp, old_cached = cashflow.mcp, cashflow.commitments.cached
    old_setting = company.setting

    async def cached():
        return {"bank": 1_000_000.0, "items": []}

    cashflow.mcp = balance_sheet(stub)
    cashflow.commitments.cached = cached
    company.setting = lambda k, d=None: {"lonn_utbetalingsdag": 10}.get(k, d)
    try:
        return asyncio.run(cashflow.build(TODAY))
    finally:
        cashflow.mcp, cashflow.commitments.cached = old_mcp, old_cached
        company.setting = old_setting


def test_a_whole_forecast_is_not_marked_partial():
    assert _forecast([REVENUE])["partial"] is False


def test_a_dropped_register_marks_the_forecast_partial():
    """So that `Cached` expires it in 45 seconds instead of ten minutes. An
    empty supplier book reads exactly like a company that owes nobody."""
    data = _forecast_with(_Broken([REVENUE]))
    assert data["partial"] is True
    assert cashflow._flight._ttl(data) == cashflow._flight._degraded_seconds


def test_a_whole_forecast_keeps_the_full_cache_life():
    data = _forecast([REVENUE])
    assert cashflow._flight._ttl(data) == cashflow.CACHE_SECONDS


# --------------------------------------------- what the register itself says
def test_a_partly_read_register_is_not_a_whole_one():
    """search_supplier_invoices answers partially rather than failing when one
    of its two registers is unreadable, and says so in `complete`. Only an
    exception counted as incomplete, so a half-read book passed for a whole
    one — and a half-empty supplier book reads like a company that owes less
    than it does."""
    class _Partial(_Tripletex):
        async def call(self, tool, args=None):
            out = await super().call(tool, args)
            if tool == "search_supplier_invoices":
                out["complete"] = False
                out["degradedNote"] = "det nye fakturaflytregisteret svarte ikke"
            return out

    data = _forecast_with(_Partial([REVENUE]))
    assert data["partial"] is True
    assert any("delvis lest" in w for w in data["warnings"])


def test_a_foreign_currency_invoice_is_declared_not_silently_taken_as_kroner():
    """outstandingAmount is in the invoice's own currency. There is no rate
    here, so the money stays in the forecast and the error is said out loud."""
    ap = [{"voucherId": 9, "supplierName": "Cleaning Supplies GmbH",
           "outstandingAmount": 10_000.0, "currency": "EUR",
           "dueDate": "2026-10-20", "invoiceDate": "2026-09-20"}]
    data = _forecast([REVENUE], ap=ap)
    assert any("EUR" in w and "ikke kroner" in w for w in data["warnings"])
    assert _kinds(data, "ap"), "the money must not be dropped either"


def test_a_customer_invoice_in_euro_is_already_in_kroner():
    """The customer register's amountOutstanding is in kroner even for an
    invoice in euro. Warning that it was not told the CEO, and the
    regnskapsfører through the clean-up list, that a correct forecast was
    wrong by the exchange rate."""
    ar = [{**_invoice(115_000.0, "2026-09-20", "2026-10-20"), "currency": "EUR"}]
    data = _forecast([REVENUE], ar=ar)
    assert not any("EUR" in w for w in data["warnings"])
    assert round(sum(i["amount"] for i in _kinds(data, "ar"))) == 115_000


# ------------------------------- the employer's contribution, exactly once
def test_a_payroll_already_on_2770_owes_no_forecast_contribution():
    """2770 is credited when the payroll is journalised, not when the
    a-melding is filed. A month already journalised is already on the balance
    commitments dates, so forecasting it again pays it twice. Against this
    ledger the pay-day test happened to agree, because the run is posted on
    the day it is paid — the ledger is the thing that actually decides it."""
    wages = _cum("5000 Lønn til ansatte", [800_000.0] * 10)
    aga = _cum("5400 Arbeidsgiveravgift", [112_000.0] * 10)
    # October's own AGA has reached the liability account.
    posted = _cum("2770 Skyldig arbeidsgiveravgift", [0.0] * 9 + [-112_000.0])
    october = [i for i in _kinds(_forecast([wages, aga, posted]), "aga_future")
               if "oktober" in i["label"]]
    assert not october, october

    unposted = _cum("2770 Skyldig arbeidsgiveravgift", [0.0] * 10)
    still = [i for i in _kinds(_forecast([wages, aga, unposted]), "aga_future")
             if "oktober" in i["label"]]
    assert still, "a run not yet journalised still owes its contribution"


def test_the_withholding_is_not_paid_on_pay_day_and_again_at_the_term():
    """From 2026 the trekk leaves with the salary, and `_payroll_runs` pays
    the gross. Scheduling the 2600-2619 balance as well paid it twice. 2600
    has stood at 0 all year, so this was latent — and stays that way."""
    assert "forskuddstrekk" not in cashflow.STATUTORY_FROM_COMMITMENTS
    items = [{"id": "forskuddstrekk", "label": "Forskuddstrekk",
              "amount": 434_347.0, "due": "2026-11-16", "kind": "holding"}]
    data = _forecast([REVENUE], items=items)
    assert not [i for i in _kinds(data, "statutory")
                if "rskuddstrekk" in i["label"]]


# ---------------------------------------------- the company's stated terms
def test_stated_payment_terms_are_used_when_no_invoice_shows_them():
    """kredittid_dager was listed as a setting that moves numbers, and moved
    none: the forecast measured the terms from the invoices, or assumed 30."""
    a = _forecast([REVENUE], settings={"kredittid_dager": 45})["assumptions"]
    assert (a["credit_days"], a["credit_days_source"]) == (45, "fra company.md")
    a = _forecast([REVENUE])["assumptions"]
    assert (a["credit_days"], a["credit_days_source"]) == (30, "antatt")
    # What the invoices show wins over what is written down.
    ar = [_invoice(100_000.0, "2026-09-20", "2026-10-04")]
    a = _forecast([REVENUE], ar=ar, settings={"kredittid_dager": 45})["assumptions"]
    assert (a["credit_days"], a["credit_days_source"]) == (14, "målt på fakturaene")
