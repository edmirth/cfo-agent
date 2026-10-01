from datetime import date

import commitments
import company
import workdays


def _with_setting(value):
    """Swap company.setting for the duration of one check."""
    original = company.setting
    company.setting = lambda key, default=None: (value if key == "lonn_utbetalingsdag"
                                                 else original(key, default))
    return original


def test_the_stated_pay_day_is_used():
    original = _with_setting(20)
    try:
        assert commitments.payday(2026, 10) == date(2026, 10, 20)
        assert commitments.payday(2026, 12) == date(2026, 12, 20)
    finally:
        company.setting = original


def test_month_end_is_the_fallback_when_nothing_is_stated():
    original = _with_setting(None)
    try:
        assert commitments.payday(2026, 10) == date(2026, 10, 31)
        assert commitments.payday(2026, 2) == date(2026, 2, 28)
    finally:
        company.setting = original


def test_a_short_month_cannot_overflow():
    original = _with_setting(31)
    try:
        assert commitments.payday(2026, 2) == date(2026, 2, 28)
    finally:
        company.setting = original


def test_a_pay_day_on_a_weekend_is_paid_before_it():
    # 20 December 2026 is a Sunday. Wages are not paid late.
    original = _with_setting(20)
    try:
        assert workdays.backward(commitments.payday(2026, 12)) == date(2026, 12, 18)
    finally:
        company.setting = original


def test_a_thirteen_week_horizon_covers_every_pay_day_in_it():
    """The bug: month end put December's run outside the window while the
    stated 20th puts it inside, so a whole payroll vanished from the forecast."""
    original = _with_setting(20)
    try:
        today, horizon = date(2026, 9, 28), date(2026, 9, 28) + __import__("datetime").timedelta(weeks=13)
        runs, month = [], today
        while True:
            run = workdays.backward(commitments.payday(month.year, month.month))
            if run >= horizon:
                break
            if run >= today:
                runs.append(run)
            month = (date(month.year + 1, 1, 1) if month.month == 12
                     else date(month.year, month.month + 1, 1))
        assert runs == [date(2026, 10, 20), date(2026, 11, 20), date(2026, 12, 18)], runs
    finally:
        company.setting = original


def test_commitments_and_cashflow_share_one_implementation():
    # Not two functions that can drift apart again.
    import cashflow
    assert cashflow.commitments.payday is commitments.payday
