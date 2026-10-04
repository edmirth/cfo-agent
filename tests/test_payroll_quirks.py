"""The two months that are not like the other ten.

December takes half the usual tax, and the holiday month pays feriepenger
instead of salary. A forecast of twelve identical payroll runs gets both wrong,
and in opposite directions: it invents a December that is heavier than it is,
and it pays the staff twice in June.
"""
from datetime import date, timedelta

import cashflow
import commitments
import company


WAGES = 904_000.0


def _with_settings(**values):
    """Swap company.setting for the duration of one check."""
    original = company.setting
    company.setting = lambda key, default=None: values.get(key, default)
    return original


def _runs(today, weeks=13, wages=WAGES):
    return cashflow._payroll_runs(today, today + timedelta(weeks=weeks), wages)


def _run_months(today, weeks=13):
    """The months whose pay day falls in the window — what gates the notes.

    A note about the holiday month describes what the payroll *run* does, so
    it follows the run, not the months the thirteen weeks happen to touch.
    The fully withheld month is exactly why this cannot be read back off the
    flows: that month produces no flow at all.
    """
    horizon = today + timedelta(weeks=weeks)
    return [m for _, m, _ in cashflow._pay_days(today, horizon)]


def _by_month(flows):
    return {f["date"].month: f for f in flows}


def test_the_feriepenger_month_pays_no_ordinary_salary():
    """Five weeks of holiday is thirty virkedager against a month of twenty-six,
    so the whole run is withheld and feriepenger is the only payment. Charging
    the salary as well pays the staff twice: commitments already dates the
    accrued feriepenger to this month from account 2940."""
    original = _with_settings(lonn_utbetalingsdag=10, ferie_uker=5)
    try:
        months = _by_month(_runs(date(2026, 4, 1)))
        assert sorted(months) == [4, 5], sorted(months)
        assert 6 not in months, "June drew feriepenger, not salary"
        assert months[4]["amount"] == -WAGES
    finally:
        company.setting = original


def test_four_weeks_holiday_still_pays_part_of_the_month():
    """Twenty-four virkedager of twenty-six: two days of salary still go out,
    and rounding them away would be a different company's assumption."""
    original = _with_settings(lonn_utbetalingsdag=10, ferie_uker=4)
    try:
        june = _by_month(_runs(date(2026, 4, 1)))[6]
        assert abs(june["amount"] + WAGES * 2 / 26) < 1.0, june["amount"]
        assert "holdt igjen" in june["label"]
    finally:
        company.setting = original


def test_december_takes_the_same_gross_as_any_other_month():
    """Half tax raises what the staff take home and lowers what Skatteetaten
    takes, by the same krone, on the same day. Since 2026 both leave on pay
    day, so the company's December outflow is an ordinary gross month. The
    other half is never withheld later — there is no catch-up to date."""
    original = _with_settings(lonn_utbetalingsdag=10, ferie_uker=5)
    try:
        months = _by_month(_runs(date(2026, 10, 1)))
        assert sorted(months) == [10, 11, 12], sorted(months)
        assert months[12]["amount"] == months[11]["amount"] == -WAGES
        assert months[12]["label"] == "Lønn og skattetrekk"
    finally:
        company.setting = original


def test_the_stated_payout_month_moves_the_withholding():
    """A company that pays feriepenger with the July run withholds July's
    salary, not June's — and commitments must date the feriepenger to the same
    month, or the forecast loses a payroll in one week and doubles it in
    another."""
    original = _with_settings(lonn_utbetalingsdag=10, ferie_utbetalingsmnd=7)
    try:
        assert commitments.ferie_month() == 7
        assert commitments.ferie_month_is_stated()
        months = _by_month(_runs(date(2026, 5, 1)))
        assert 6 in months and months[6]["amount"] == -WAGES
        assert 7 not in months, "July drew feriepenger, not salary"
    finally:
        company.setting = original


def test_june_is_the_assumption_when_nothing_is_stated():
    original = _with_settings(lonn_utbetalingsdag=10)
    try:
        assert commitments.ferie_month() == 6
        assert not commitments.ferie_month_is_stated()
        assert cashflow._ferie_withheld() == (1.0, cashflow.FERIE_WEEKS, False)
    finally:
        company.setting = original


def test_feriepenger_and_the_withheld_salary_land_in_the_same_month():
    """One implementation of the payout month, not two. The bug this guards
    against has already happened once with the pay day."""
    original = _with_settings(lonn_utbetalingsdag=10, ferie_utbetalingsmnd=7)
    try:
        payout = commitments._next_ferie(date(2026, 1, 15))
        salary = _by_month(_runs(date(2026, 5, 1)))
        assert (payout.year, payout.month) == (2026, 7), payout
        assert payout.month not in salary, "the withheld month is the payout month"
    finally:
        company.setting = original


def test_both_quirks_are_declared_to_the_owner():
    """He is being asked to make decisions on this. A month modelled
    differently from the other eleven and not said out loud is a black box."""
    original = _with_settings(lonn_utbetalingsdag=10, ferie_uker=5)
    try:
        today = date(2026, 4, 1)
        data = cashflow._assemble(
            today, today - timedelta(days=today.weekday()), 1_000_000.0,
            _runs(today), [],
            {"revenue": 2_000_000.0, "wages": 1_004_000.0,
             "wages_cash": WAGES, "opex": 300_000.0},
            30, [], [], [], payroll_months=_run_months(today))
        a = data["assumptions"]
        assert a["feriepenger_maned"].startswith("juni")
        assert a["feriepenger_maned_oppgitt"] is False, "an assumption says so"
        assert a["ferie_lonn_holdt_igjen"] == 1.0
        assert a["ferie_uker"] == 5
        assert "samme dag" in a["halv_skatt_i_desember"]

        text = cashflow.briefing(data)
        assert "Feriemåneden ligger i perioden" in text
        assert "Halv skatt i desember" not in text, "December is outside this window"
    finally:
        company.setting = original


def test_december_is_explained_only_when_it_is_in_the_window():
    original = _with_settings(lonn_utbetalingsdag=10, ferie_uker=5)
    try:
        today = date(2026, 10, 1)
        data = cashflow._assemble(
            today, today - timedelta(days=today.weekday()), 1_000_000.0,
            _runs(today), [],
            {"revenue": 2_000_000.0, "wages": 1_004_000.0,
             "wages_cash": WAGES, "opex": 300_000.0},
            30, [], [], [], payroll_months=_run_months(today))
        text = cashflow.briefing(data)
        assert "Halv skatt i desember" in text
        assert "Feriemåneden" not in text, "June is outside this window"
    finally:
        company.setting = original


def test_feriepenger_is_dated_to_the_payroll_run_not_month_end():
    """The payout and the withheld salary are one event. Dating the money to
    the last of the month put it two forecast weeks away from the salary it
    replaces, and the week of the run then showed no staff cost at all."""
    original = _with_settings(lonn_utbetalingsdag=10)
    try:
        payout = commitments._next_ferie(date(2026, 1, 15))
        withheld_on = commitments.payday(2026, 6)
        assert payout == withheld_on == date(2026, 6, 10), payout
    finally:
        company.setting = original


def test_month_end_is_still_the_fallback_for_the_payout():
    original = _with_settings()
    try:
        assert commitments._next_ferie(date(2026, 1, 15)) == date(2026, 6, 30)
    finally:
        company.setting = original


def test_a_payout_already_run_is_dated_to_next_year():
    """What sits on 2940 the day after the run is next year's accrual, not an
    unpaid balance — but only after the run, not for the whole month. The old
    code rolled the entire month forward, dating a balance owed on 5 June
    twelve months out."""
    original = _with_settings(lonn_utbetalingsdag=10)
    try:
        assert commitments._next_ferie(date(2026, 6, 5)) == date(2026, 6, 10)
        assert commitments._next_ferie(date(2026, 6, 25)) == date(2027, 6, 10)
    finally:
        company.setting = original


def test_a_window_that_only_clips_december_gets_no_december_note():
    """The note describes what December's payroll run does. A window that
    reaches into December without reaching its pay day contains no such run,
    and a note about a run that is not in the table is noise — which is what
    gets the real notes skimmed past.
    """
    original = _with_settings(lonn_utbetalingsdag=10, ferie_uker=5)
    try:
        today = date(2026, 9, 10)
        week0 = today - timedelta(days=today.weekday())
        horizon = week0 + timedelta(weeks=13)
        months = [m for _, m, _ in cashflow._pay_days(today, horizon)]
        assert 12 not in months, "December's pay day is past the horizon"

        data = cashflow._assemble(
            today, week0, 1_000_000.0, _runs(today), [],
            {"revenue": 2_000_000.0, "wages": 1_004_000.0,
             "wages_cash": WAGES, "opex": 300_000.0},
            30, [], [], [], payroll_months=months)
        # The thirteen weeks do touch December — the last one ends 6 December.
        assert any(w["end"].startswith("2026-12") for w in data["weeks"])
        assert "Halv skatt i desember" not in cashflow.briefing(data)
    finally:
        company.setting = original
