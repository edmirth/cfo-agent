"""The company's profile for the forecast (card 70): every former constant,
where each value came from, and what company.md can state."""
import company
from cashflow import profile


def _with_settings(settings: dict):
    real = company.setting
    company.setting = lambda k, d=None: settings.get(k, d)
    return real


def test_the_defaults_are_the_forecast_as_it_was():
    p = profile.DEFAULT
    assert (p.vat_rate, p.vat_ratio_min, p.vat_input_cap) == (0.25, 50_000, 0.5)
    assert (p.late_days, p.doubtful_days, p.slow_weeks, p.late_spread_weeks,
            p.pay_lag_days) == (30, 90, (3, 8), 3, 7)
    assert (p.recurring_months, p.run_months, p.run_active, p.run_min_months) == (3, 6, 5, 3)
    assert (p.behind_min, p.behind_share, p.stall_days, p.unusual) == (5_000, 0.25, 10, 1.5)
    assert (p.min_closed_months, p.level_months, p.season_weight,
            p.season_limits) == (3, 6, 0.5, (0.5, 1.5))
    assert (p.fixed_lookback, p.fixed_min, p.fixed_tolerance) == (4, 3, 0.15)
    assert p.cost_periods == ((1, 7), (8, 14), (15, 21), (22, 31))
    assert (p.profile_min_bills, p.profile_weight_cap, p.profile_min_period_bills) == (10, 3, 3)
    assert (p.bank_unknown_max, p.register_check) == (0.10, 0.35)
    assert (p.ar_residual_min, p.ap_residual_min) == (1000, 1000)
    assert (p.ferie_weeks, p.payroll_months, p.payroll_min, p.payday_window) == (5, 6, 3, 3)


def test_nothing_stated_is_every_value_at_its_default():
    real = _with_settings({})
    try:
        p = profile.resolve()
    finally:
        company.setting = real
    assert p == profile.DEFAULT
    assert p.sources and {r.source for r in p.sources.values()} == {"default"}
    assert p.source("late_days") == "default"


def test_holiday_weeks_stated_in_company_md_are_used_and_said():
    real = _with_settings({"ferie_uker": 4})
    try:
        p = profile.resolve()
    finally:
        company.setting = real
    assert p.ferie_weeks == 4 and p.source("ferie_weeks") == "stated"
    assert p.source("vat_rate") == "default"


def test_holiday_weeks_out_of_range_are_not_taken():
    real = _with_settings({"ferie_uker": 40})
    try:
        p = profile.resolve()
    finally:
        company.setting = real
    assert p.ferie_weeks == 5 and p.source("ferie_weeks") == "default"
