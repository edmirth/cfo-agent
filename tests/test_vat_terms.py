from datetime import date

import commitments


COLUMNS = ["Inngående balanse", "Jan", "Feb", "Mars", "April", "Mai", "Juni",
           "Juli", "Aug", "Sept", "Utgående saldo"]


def _rows(aug: float, now: float):
    """2700 and 2710 as the monthly saldobalanse reports them. Only the August
    column and the closing balance matter to the split."""
    pad = [0] * 7
    return [{"path": "2700 Utgående merverdiavgift, høy sats",
             "cells": [0] + pad + [aug, now, now]},
            {"path": "2710 Inngående merverdiavgift, høy sats",
             "cells": [0] + pad + [0, 0, 0]}]


def _running(amount: float) -> dict:
    return {"id": "mva_lopende", "label": "Merverdiavgift, inneværende termin",
            "plain": "", "amount": amount, "kind": "holding",
            "due": "2026-12-10", "days": 71, "accounts": ["2700"],
            "estimated": False, "assumed_due": False}


def test_the_completed_term_is_dated_to_its_own_deadline():
    # Ullensaker's real shape: Jul-Aug never transferred, September on top.
    items = [_running(1011911.02)]
    commitments._split_vat(items, _rows(-939143.19, -1156938.25), COLUMNS,
                           date(2026, 9, 30))
    done = next(i for i in items if i["id"] == "mva_forrige_termin")
    run = next(i for i in items if i["id"] == "mva_lopende")
    # 10 October 2026 is a Saturday, so the deadline is Monday the 12th.
    assert done["due"] == "2026-10-12"
    assert abs(done["amount"] - 939143.19) < 0.01
    assert abs(run["amount"] - (1011911.02 - 939143.19)) < 0.01
    assert run["due"] == "2026-12-10"
    assert run["accruing"] is True
    # Nothing invented and nothing lost.
    assert abs(done["amount"] + run["amount"] - 1011911.02) < 0.01


def test_a_transferred_term_is_not_counted_twice():
    # Bookkeeper moved Jul-Aug to 2740 on 31 August, so the August column is
    # zero and everything left is the running term.
    items = [_running(214339.52)]
    commitments._split_vat(items, _rows(0, -214339.52), COLUMNS,
                           date(2026, 9, 30))
    assert [i["id"] for i in items] == ["mva_lopende"]
    assert abs(items[0]["amount"] - 214339.52) < 0.01


def test_a_term_with_nothing_accrued_since_leaves_no_running_item():
    # Term ended, nothing booked in the new one yet: one item, one date.
    items = [_running(939143.19)]
    commitments._split_vat(items, _rows(-939143.19, -939143.19), COLUMNS,
                           date(2026, 9, 30))
    assert [i["id"] for i in items] == ["mva_forrige_termin"]
    assert items[0]["due"] == "2026-10-12"


def test_terms_settle_two_months_after_they_end():
    assert commitments._completed_term(date(2026, 9, 30)) == (8, date(2026, 10, 10))
    assert commitments._completed_term(date(2026, 11, 1)) == (10, date(2026, 12, 10))
    assert commitments._completed_term(date(2026, 3, 5)) == (2, date(2026, 4, 10))


def test_a_missing_month_column_changes_nothing():
    items = [_running(500.0)]
    commitments._split_vat(items, _rows(-400, -500), ["Utgående saldo"],
                           date(2026, 9, 30))
    assert [i["id"] for i in items] == ["mva_lopende"]
