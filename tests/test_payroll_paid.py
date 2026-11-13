"""What a pay day costs, read off the payroll vouchers.

The wage accounts carry accruals and holiday pay as they are earned; the bank
sees net pay and the withheld tax on the day. Made-up vouchers in the shape
Tripletex books them: one voucher per run, with the wages, the trekk, the net
pay and, when it was booked, the payment from the bank.
"""
from datetime import date

import cashflow
import company
from tests.test_cashflow_build import REVENUE, _forecast, _kinds

TODAY = date(2026, 11, 8)
_ids = iter(range(1, 10_000))


def _run(day: str, gross: float, trekk: float, net: float, paid: bool = True, sign: int = 1):
    """One payroll voucher. `paid` books the payment from the bank in it;
    `sign` -1 is its reversal."""
    v = next(_ids)
    rows = [{"voucherId": v, "date": day, "accountNumber": 5000, "amount": sign * gross},
            {"voucherId": v, "date": day, "accountNumber": 2600, "amount": sign * -trekk},
            {"voucherId": v, "date": day, "accountNumber": 2910, "amount": sign * -net}]
    if paid:
        rows += [{"voucherId": v, "date": day, "accountNumber": 2600, "amount": sign * trekk},
                 {"voucherId": v, "date": day, "accountNumber": 2910, "amount": sign * net},
                 {"voucherId": v, "date": day, "accountNumber": 1920, "amount": sign * -(trekk + net)}]
    return rows


def _paid(postings, payday=10):
    original = company.setting
    company.setting = lambda k, d=None: {"lonn_utbetalingsdag": payday}.get(k, d)
    try:
        return cashflow.payroll_paid(postings, TODAY)
    finally:
        company.setting = original


def test_a_pay_day_is_what_left_the_bank_not_what_the_wage_accounts_say():
    rows = (_run("2026-08-10", 1_000_000, 200_000, 600_000)
            + _run("2026-09-10", 1_050_000, 210_000, 640_000)
            + _run("2026-10-09", 1_100_000, 250_000, 690_000))
    out = _paid(rows)
    assert out["per_run"] == 850_000.0, "the median of 800 000, 850 000 and 940 000"
    assert [m["run"] for m in out["months"]] == [800_000.0, 850_000.0, 940_000.0]


def test_a_payment_not_booked_counts_the_same():
    """October's payment left the bank but was not booked in the voucher."""
    rows = (_run("2026-08-10", 1, 200_000, 600_000) + _run("2026-09-10", 1, 200_000, 600_000)
            + _run("2026-10-09", 1, 250_000, 690_000, paid=False))
    assert [m["run"] for m in _paid(rows)["months"]][-1] == 940_000.0


def test_a_reversed_voucher_cancels_its_original():
    rows = (_run("2026-08-10", 1, 200_000, 600_000)
            + _run("2026-09-10", 1, 200_000, 600_000)
            + _run("2026-09-10", 1, 200_000, 600_000, sign=-1)
            + _run("2026-09-10", 1, 210_000, 620_000)
            + _run("2026-10-09", 1, 200_000, 600_000))
    assert [m["run"] for m in _paid(rows)["months"]] == [800_000.0, 830_000.0, 800_000.0]


def test_an_accrual_on_the_wage_accounts_pays_nothing():
    accrual = [{"voucherId": 9001, "date": "2026-08-31", "accountNumber": 5000, "amount": 500_000},
               {"voucherId": 9001, "date": "2026-08-31", "accountNumber": 2945, "amount": -500_000}]
    rows = (_run("2026-08-10", 1, 200_000, 600_000) + accrual
            + _run("2026-09-10", 1, 200_000, 600_000) + _run("2026-10-09", 1, 200_000, 600_000))
    assert _paid(rows)["per_run"] == 800_000.0


def test_an_extra_run_is_kept_apart_from_the_pay_day():
    """A second run mid-month, after a one-off job, is not a normal pay day."""
    rows = (_run("2026-08-10", 1, 200_000, 600_000)
            + _run("2026-09-10", 1, 200_000, 600_000) + _run("2026-09-17", 1, 100_000, 400_000)
            + _run("2026-10-09", 1, 200_000, 600_000))
    out = _paid(rows)
    assert out["per_run"] == 800_000.0
    assert out["months"][1] == {"month": "september 2026", "run": 800_000.0, "extra": 500_000.0}


def test_the_holiday_pay_month_is_left_out():
    rows = (_run("2026-06-10", 1, 800_000, 3_000_000) + _run("2026-07-10", 1, 200_000, 600_000)
            + _run("2026-08-10", 1, 200_000, 600_000) + _run("2026-09-10", 1, 200_000, 600_000))
    out = _paid(rows)
    assert "juni 2026" not in [m["month"] for m in out["months"]]


def test_too_few_months_are_not_trusted():
    rows = _run("2026-09-10", 1, 200_000, 600_000) + _run("2026-10-09", 1, 200_000, 600_000)
    assert _paid(rows) is None


def test_other_postings_are_not_payroll():
    """A customer payment or an owner's expense on 2910 is not a pay day."""
    rows = (_run("2026-08-10", 1, 200_000, 600_000) + _run("2026-09-10", 1, 200_000, 600_000)
            + _run("2026-10-09", 1, 200_000, 600_000)
            + [{"voucherId": 9100, "date": "2026-10-09", "accountNumber": 2910, "amount": -50_000},
               {"voucherId": 9100, "date": "2026-10-09", "accountNumber": 6800, "amount": 50_000},
               {"date": "2026-10-09", "amount": -12_000}])
    assert _paid(rows)["per_run"] == 800_000.0


def test_the_forecast_pays_the_measured_pay_day():
    original = cashflow.sources._payroll_measured

    async def measured(today):
        return {"per_run": 850_000.0, "months": []}

    cashflow.sources._payroll_measured = measured
    try:
        data = _forecast([REVENUE, _wages()])
    finally:
        cashflow.sources._payroll_measured = original
    assert {round(i["amount"]) for i in _kinds(data, "wages")} == {-850_000}
    assert data["assumptions"]["lonn_per_lonningsdag"]["kilde"] == "lønnsbilagene"


def test_without_the_vouchers_the_wage_accounts_stay():
    data = _forecast([REVENUE, _wages()])
    assert data["assumptions"]["lonn_per_lonningsdag"]["kilde"] == "lønnskontoene"


def _wages():
    from tests.test_cashflow_build import _cum
    return _cum("5000 Lønn til ansatte", [1_000_000.0] * 10)


class _Ledger:
    """Answers search_ledger_postings from a list, counting the calls."""

    def __init__(self, rows, fail=False):
        self.rows, self.fail, self.calls = rows, fail, 0

    async def call(self, tool, args):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Tripletex svarte ikke")
        lo, hi = args["accountNumberFrom"], args["accountNumberTo"]
        hits = [r for r in self.rows if lo <= r["accountNumber"] <= hi]
        return {"postings": hits if not args.get("from") else [], "hasMore": False}


def _measure(ledger):
    import asyncio
    original_mcp, original_setting = cashflow.sources.mcp, company.setting
    cashflow.sources.mcp = ledger
    company.setting = lambda k, d=None: {"lonn_utbetalingsdag": 10}.get(k, d)
    try:
        return asyncio.run(cashflow.sources._payroll_measured(TODAY))
    finally:
        cashflow.sources.mcp, company.setting = original_mcp, original_setting


def test_the_pay_day_is_read_once_a_day_not_on_every_rebuild():
    cashflow._payroll_cache.clear()
    ledger = _Ledger(_run("2026-08-10", 1, 200_000, 600_000) + _run("2026-09-10", 1, 200_000, 600_000)
                     + _run("2026-10-09", 1, 200_000, 600_000))
    first = _measure(ledger)
    calls = ledger.calls
    assert first["per_run"] == 800_000.0 and calls == 4
    assert _measure(ledger) == first and ledger.calls == calls
    cashflow._payroll_cache.clear()


def test_an_unread_ledger_is_said_and_asked_again():
    cashflow._payroll_cache.clear()
    ledger = _Ledger([], fail=True)
    assert "unread" in _measure(ledger)
    calls = ledger.calls
    _measure(ledger)
    assert ledger.calls > calls, "a failure is not kept"
    original = cashflow.sources._payroll_measured

    async def unread(today):
        return {"unread": "Tripletex svarte ikke"}

    cashflow.sources._payroll_measured = unread
    try:
        data = _forecast([REVENUE, _wages()])
    finally:
        cashflow.sources._payroll_measured = original
    assert any("Lønnsbilagene kunne ikke leses" in w for w in data["warnings"])
    assert data["assumptions"]["lonn_per_lonningsdag"]["kilde"] == "lønnskontoene"
    cashflow._payroll_cache.clear()
