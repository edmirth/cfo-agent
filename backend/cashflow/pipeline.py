"""The forecast assembled: every source read, every flow scheduled."""
import logging
from datetime import date, timedelta

from .assemble import _assemble, _bank_payload
from .common import MVA_RATE, WEEKS, _monday
from .costs import _bank_costs_or_say, _booked_opex, _fixed, _known_by_month
from .declare import (_declare_costs, _declare_pay, _declare_receivables, _declare_sales,
                      _keep)
from .invoicing import _invoiced_this_month, _invoicing, _sales_timing
from .ledger import _run_rates
from .payables import _schedule_payments
from .payroll import _payroll
from .receivables import _credit_days, _expected_items, _receivables
from .reconcile import _ap_residual, _ar_residual, _opening, _settle
from .sources import _habits, _last_year, _read
from .tax import _booked_vat, _settled, _statutory, _vat_input_share
from .trading import _opex_in, _trading, _Trading

log = logging.getLogger("cfo.cashflow")


# No WITHHOLDING_SHARE any more. Until 2026 the tax withheld from wages was held
# back and settled on a bimonthly term, so only the net left on pay day. From
# 2026 there is no skattetrekkskonto and the trekk goes to Skatteetaten the same
# day as the salary — so what leaves the account on pay day is the gross.
# No TRAILING_MONTHS either: it said the run-rates used a trailing window, and
# they never did — `_run_rates` takes a median over every closed month. A
# constant that documents behaviour the code does not have is worse than none.


async def build(today: date | None = None) -> dict:
    """Thirteen weeks of cash on two lines, from the books as they stand.

    Each stage below adds its flows to the committed or the expected line and
    its warnings to the one list, in a fixed order: the weeks list them in
    the order they were added, so the order is part of the answer."""
    today = today or date.today()
    week0 = _monday(today)
    horizon = week0 + timedelta(weeks=WEEKS)
    src = await _read(today)
    warnings = src.warnings
    rows, columns = src.rows, src.columns

    prior_months, history, season = _last_year(src, today, warnings)
    habits, bank_categories = await _habits(src, today, warnings)
    rates, rate_notes = _run_rates(rows, columns, prior_months, season,
                                   (*history, today.year - 1) if history else None)
    warnings += rate_notes
    gap, booked, opening = _opening(src.com, warnings)
    ar_due, ar_paid, ap_due, ap_paid, risky, ar_at_risk = _settle(src, gap)
    ar_residual, residual_counted = _ar_residual(src, warnings)

    committed: list[dict] = []
    expected: list[dict] = []
    ar_doubtful, ages = _receivables(ar_due, today, habits, ar_residual,
                                     residual_counted, committed, expected)
    committed += _schedule_payments(ap_due, today)
    fixed_found, fixed_by_month, profile = _fixed(src, today, horizon, committed)
    sales_profile, sales_lag = _sales_timing(src, habits)
    runs = _invoicing(src, today, horizon, habits, season, risky, ar_due, sales_lag,
                      committed, expected)
    _ap_residual(src, today, committed, warnings)
    committed += _statutory(src.com, today)
    vat_settled, aga_paid = _settled(src.tax_posts)
    pay = _payroll(src, rates, today, horizon, aga_paid, committed, warnings)

    credit_days, credit_source = _credit_days(src.ar_open)
    vat_share, vat_measured = _vat_input_share(rows)
    booked_vat = _booked_vat(rows, columns, vat_settled)
    invoiced_this_month = _invoiced_this_month(src, today)
    opex_vat = rates["revenue"] * MVA_RATE * vat_share
    booked_opex = _booked_opex(rows, columns)
    bank_costs = _bank_costs_or_say(bank_categories, warnings)
    trade = _Trading(
        today=today, horizon=horizon, rates=rates, season=season,
        vat_share=vat_share, booked_vat=booked_vat,
        invoiced_this_month=invoiced_this_month, runs=runs,
        sales_profile=sales_profile, sales_lag=sales_lag, credit_days=credit_days,
        bank_costs=bank_costs, known_by_month=_known_by_month(committed),
        fixed_by_month=fixed_by_month, profile=profile,
        opex_left=max(0.0, _opex_in(rates, season, today.month) - booked_opex))
    months = _trading(trade, committed, expected)
    if not vat_measured:
        warnings.append(
            "Forholdet mellom utgående og inngående merverdiavgift lot seg "
            "ikke måle — konto 2700 er tom eller nettopp gjort opp. Prognosen "
            "legger derfor ut hele den utgående momsen på ny fakturering, uten "
            "fradrag for moms på det dere selv kjøper. Det er for strengt, ikke "
            "for snilt, men det er verdt å vite.")

    data = _assemble(today, week0, opening, committed, expected,
                     rates, credit_days, warnings, ar_due, ap_due,
                     vat_share, vat_measured, booked_vat,
                     invoiced_this_month, pay.months)
    _declare_pay(data, credit_source, pay)
    _declare_costs(data, rates, opex_vat, booked_opex, bank_costs, fixed_found, profile)
    _declare_sales(data, runs, sales_profile, sales_lag, season, months, warnings)
    data["bank"] = _bank_payload(booked, gap, ar_paid, ap_paid)
    data["items"] = _expected_items(ar_due, ap_due, today, habits)
    data["betalingsvaner"] = habits
    data["bank_categories"] = bank_categories
    _declare_receivables(data, src, ar_due, ar_at_risk, ar_doubtful, ages,
                         ar_residual, residual_counted)
    _keep(data, rows, today)
    return data


# ------------------------------------------------------------------ reading


# ------------------------------------------------------- opening and the bank


# ------------------------------------------------------- money in, and out


# ------------------------------------------- what this month has booked


