import preflight


COLUMNS = ["Inngående balanse"] + preflight.MONTHS[:9] + ["Utgående saldo"]


def _row(path, monthly):
    """A saldobalanse row: opening, nine month-ends, closing."""
    return {"path": path, "cells": [0] + monthly + [monthly[-1]]}


def test_an_accrual_frozen_all_year_is_counted():
    # 2945: last posted 31 December, untouched for nine months.
    row = _row("2945 Periodisering av lønn", [-986108] * 9)
    assert preflight._frozen_months(row, COLUMNS) == 8


def test_an_account_that_moved_last_month_is_not_frozen():
    row = _row("2400 Leverandørgjeld", [-200000] * 8 + [-32968])
    assert preflight._frozen_months(row, COLUMNS) == 0


def test_a_blanked_cell_does_not_shift_the_months():
    """Filtering non-numeric cells before zipping would move every month by one
    the moment one reads #AUTH!, and a moving account would look frozen."""
    row = {"path": "2400 Leverandørgjeld",
           "cells": [0, -100, "#AUTH!", -300, -400, -500, -600, -700, -800, -900, -900]}
    assert preflight._frozen_months(row, COLUMNS) == 0


def test_the_floor_spares_balances_that_are_meant_to_sit_still():
    """2990 at -6 112 and 2991 at -10 000 have not moved all year and nothing
    is wrong with either. Flagging them trains the owner to ignore the check."""
    for amount in (-6112, -10000, -2135):
        row = _row("2990 Annen kortsiktig gjeld", [amount] * 9)
        owed = -row["cells"][-1]
        assert owed < preflight.STALE_MIN_KR, f"{owed} should be under the floor"


def test_a_material_frozen_accrual_clears_the_floor():
    row = _row("2945 Periodisering av lønn", [-986108] * 9)
    owed = -row["cells"][-1]
    assert owed >= preflight.STALE_MIN_KR
    assert preflight._frozen_months(row, COLUMNS) >= preflight.STALE_MONTHS


def test_a_quiet_quarter_is_not_long_enough():
    # Three months still is normal for something settled bimonthly.
    row = _row("2770 Skyldig arbeidsgiveravgift",
               [-100000, -200000, -300000, -400000, -500000, -600000,
                -700000, -700000, -700000])
    assert preflight._frozen_months(row, COLUMNS) == 2 < preflight.STALE_MONTHS


def test_an_account_left_blank_because_it_did_not_move_is_frozen():
    """The report leaves a cell blank when the account did not move that
    month. Dropping the blanks left nothing to compare, and an accrual
    untouched since January was never flagged."""
    row = {"path": "2945 Periodisering av lønn",
           "cells": [-986108, -986108] + [None] * 8 + [-986108]}
    assert preflight._frozen_months(row, COLUMNS) == 8
    # Untouched all year: the opening balance stands before January.
    row = {"path": "2945 Periodisering av lønn", "cells": [-986108] + [None] * 10}
    assert preflight._frozen_months(row, COLUMNS) == 8


def test_a_blank_after_a_move_carries_the_new_figure():
    row = {"path": "2400 Leverandørgjeld",
           "cells": [0, -100, -200, -300, -400, -500, -600, None, None, None, -600]}
    # Moved in June, then still through September: three months frozen.
    assert preflight._frozen_months(row, COLUMNS) == 3


def test_an_unreadable_cell_is_not_counted_as_unchanged():
    row = {"path": "2945 Periodisering av lønn",
           "cells": [-500, -500, -500, -500, -500, -500, "#AUTH!", -500, -500, -500, -500]}
    assert preflight._frozen_months(row, COLUMNS) == 2
