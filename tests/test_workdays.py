from datetime import date

import commitments
import workdays


def test_easter_anchors_the_moving_holidays():
    # Easter Sunday 2026 is 5 April; the seven moving holidays hang off it.
    assert workdays.easter(2026) == date(2026, 4, 5)
    assert workdays.easter(2027) == date(2027, 3, 28)
    h = workdays.holidays(2026)
    for d in (date(2026, 4, 2), date(2026, 4, 3), date(2026, 4, 6),
              date(2026, 5, 14), date(2026, 5, 24), date(2026, 5, 25)):
        assert d in h, d


def test_fixed_holidays_are_holidays():
    h = workdays.holidays(2026)
    for d in (date(2026, 1, 1), date(2026, 5, 1), date(2026, 5, 17),
              date(2026, 12, 25), date(2026, 12, 26)):
        assert d in h, d


def test_christmas_eve_is_a_working_day():
    # Short bank hours, but not a public holiday and not a deadline shift.
    assert workdays.is_working_day(date(2026, 12, 24))


def test_a_saturday_rolls_forward_over_the_weekend():
    # MVA on Sat 10 Oct 2026 is due Mon 12 Oct.
    assert workdays.forward(date(2026, 10, 10)) == date(2026, 10, 12)


def test_a_sunday_rolls_forward():
    # The case that moved the reported low point: AGA on Sun 15 Nov 2026.
    assert workdays.forward(date(2026, 11, 15)) == date(2026, 11, 16)


def test_a_holiday_rolls_forward_past_the_whole_easter_block():
    # Maundy Thursday 2 April 2026 -> the next working day is Tuesday 7 April,
    # because Good Friday, Easter Sunday and Easter Monday follow it.
    assert workdays.forward(date(2026, 4, 2)) == date(2026, 4, 7)


def test_a_working_day_is_left_alone():
    # Thu 10 Dec 2026 is the live MVA date and must not move.
    assert workdays.forward(date(2026, 12, 10)) == date(2026, 12, 10)
    assert workdays.backward(date(2026, 12, 10)) == date(2026, 12, 10)


def test_wages_move_back_not_forward():
    # A pay day on a weekend is paid before it, never after.
    assert workdays.backward(date(2026, 11, 15)) == date(2026, 11, 13)
    assert workdays.backward(date(2026, 5, 17)) == date(2026, 5, 15)


def test_the_shift_direction_is_chosen_per_obligation():
    sunday = date(2026, 11, 15)
    assert commitments._shift("aga", sunday) == date(2026, 11, 16)
    assert commitments._shift("mva_lopende", sunday) == date(2026, 11, 16)
    assert commitments._shift("skyldig_lonn", sunday) == date(2026, 11, 13)
    assert commitments._shift("feriepenger", sunday) == date(2026, 11, 13)


def test_supplier_bills_keep_the_date_the_invoice_gave_them():
    # They carry a real due date; guessing which way a supplier shifts it
    # would be inventing a fact.
    sunday = date(2026, 11, 15)
    assert commitments._shift("leverandorgjeld", sunday) == sunday
