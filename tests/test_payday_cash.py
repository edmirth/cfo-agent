from datetime import date

import cashflow


COLUMNS = ["Inngående balanse", "Jan", "Feb", "Mars", "April", "Mai", "Juni",
           "Juli", "Aug", "Sept", "Utgående saldo"]


def _row(path, monthly):
    """Saldobalanse rows are cumulative; _monthly differences them."""
    cum, running = [], 0.0
    for v in monthly:
        running += v
        cum.append(running)
    return {"path": path, "cells": [0] + cum + [running]}


def _rows(wage=900000.0, feriepenger=100000.0, sick=4000.0):
    nine = [wage] * 9
    return [_row("5000 Lønn til ansatte", nine),
            _row("5020 Feriepenger", [feriepenger] * 9),
            _row("5030 Sykepenger", [sick] * 9)]


def test_feriepenger_is_not_monthly_cash():
    """It accrues every month and is paid next summer — commitments already
    dates it to 30 June. Counting it in the monthly run-rate pays it twice."""
    rates, _ = cashflow._run_rates(_rows(), COLUMNS)
    assert rates["wages"] > rates["wages_cash"], "full cost must exceed cash"
    assert abs(rates["wages"] - rates["wages_cash"] - 100000.0) < 1.0
    assert abs(rates["wages_cash"] - 904000.0) < 1.0      # 900 000 + 4 000


def test_the_whole_gross_leaves_on_pay_day():
    """From 2026 the skattetrekk goes to Skatteetaten the same day as the
    salary, so the pay day takes gross, not net. Holding 30 % back modelled a
    settlement term that no longer exists."""
    rates, _ = cashflow._run_rates(_rows(), COLUMNS)
    assert not hasattr(cashflow, "WITHHOLDING_SHARE"), "the old regime is retired"
    # Nothing is scaled down on the way out.
    assert rates["wages_cash"] == rates["wages"] - 100000.0


def test_a_company_with_no_holiday_pay_accrual_is_unaffected():
    rates, _ = cashflow._run_rates(_rows(feriepenger=0.0), COLUMNS)
    assert abs(rates["wages"] - rates["wages_cash"]) < 1.0
