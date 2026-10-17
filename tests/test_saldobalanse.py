"""The monthly trial balance, rebuilt from get_balance_sheet one month at a time.

Tripletex removed «Saldobalanse per måned»; four modules read its shape. These
pin that the rebuild gives the same shape: the columns, cumulative cells, a
blank where an account did not move, and no table at all when a month is
missing or cut short.
"""
import asyncio

import saldobalanse


def _month(rows):
    return {"table": {"columns": [{"name": "Inngående balanse"}, {"name": "Endring"},
                                  {"name": "Utgående balanse"}],
                      "rows": rows, "omitted_row_count": 0}}


def _acc(number, name, ib, out, moved=True):
    return {"path": [f"{number} {name}"], "cells": [ib, out - ib, out],
            "account": {"accountNumber": number, "accountName": name,
                        "hasPostingsInPeriod": moved}}


class _Ledger:
    """Answers get_balance_sheet by month; records what was asked."""

    def __init__(self, by_month, fail=(), cut=()):
        self.by_month, self.fail, self.cut, self.asked = by_month, set(fail), set(cut), []

    async def call(self, tool, args=None):
        assert tool == "get_balance_sheet", tool
        assert args["showAccountsWithoutTransactionsInPeriod"] is True
        self.asked.append((args["dateFrom"], args["dateToExclusive"]))
        month = int(args["dateFrom"][5:7])
        if month in self.fail:
            raise RuntimeError("HTTP 500")
        answer = _month(self.by_month.get(month, []))
        if month in self.cut:
            answer["table"]["omitted_row_count"] = 3
        return answer


def _run(ledger, start="2026-01-01", end="2026-03-17"):
    return asyncio.run(saldobalanse.monthly(ledger, start, end))


def test_one_call_per_month_and_the_last_ends_the_day_after_the_period():
    ledger = _Ledger({})
    _run(ledger)
    assert ledger.asked == [("2026-01-01", "2026-02-01"), ("2026-02-01", "2026-03-01"),
                            ("2026-03-01", "2026-03-18")]


def test_the_shape_is_the_old_reports():
    ledger = _Ledger({1: [_acc(1920, "Bank", 100, 150)],
                      2: [_acc(1920, "Bank", 150, 120)],
                      3: [_acc(1920, "Bank", 120, 200)]})
    t = _run(ledger)["table"]
    assert [c["name"] for c in t["columns"]] == [
        "Inngående balanse", "Jan", "Feb", "Mars", "Utgående saldo"]
    assert t["rows"] == [{"path": "1920 Bank", "cells": [100, 150, 120, 200, 200]}]


def test_a_month_without_postings_is_blank_as_the_report_left_it():
    ledger = _Ledger({1: [_acc(6300, "Husleie", 0, 12000)],
                      2: [_acc(6300, "Husleie", 12000, 12000, moved=False)],
                      3: [_acc(6300, "Husleie", 12000, 24000)]})
    assert _run(ledger)["table"]["rows"][0]["cells"] == [0, 12000, None, 24000, 24000]


def test_an_account_that_appears_mid_year_has_nothing_before_it():
    ledger = _Ledger({1: [_acc(1920, "Bank", 0, 10)],
                      2: [_acc(1920, "Bank", 10, 10, moved=False), _acc(5000, "Lønn", 0, 40000)],
                      3: [_acc(1920, "Bank", 10, 10, moved=False), _acc(5000, "Lønn", 40000, 80000)]})
    rows = {r["path"]: r["cells"] for r in _run(ledger)["table"]["rows"]}
    assert rows["5000 Lønn"] == [None, None, 40000, 80000, 80000]
    # The bank closes on its last balance though it did not move after January.
    assert rows["1920 Bank"] == [0, 10, None, None, 10]


def test_a_month_that_cannot_be_read_fails_the_whole_table():
    # A gap would read as a month without movement: the one error that looks right.
    try:
        _run(_Ledger({}, fail={2}))
    except saldobalanse.Incomplete as e:
        assert "Feb" in str(e)
    else:
        raise AssertionError("a missing month gave a table")


def test_a_month_cut_short_fails_the_whole_table():
    try:
        _run(_Ledger({}, cut={1}))
    except saldobalanse.Incomplete as e:
        assert "avkortet" in str(e)
    else:
        raise AssertionError("a cut table was taken as whole")


def test_a_period_inside_one_month_is_one_call():
    ledger = _Ledger({10: [_acc(1920, "Bank", 5, 7)]})
    t = _run(ledger, "2026-10-01", "2026-10-17")["table"]
    assert ledger.asked == [("2026-10-01", "2026-10-18")]
    assert [c["name"] for c in t["columns"]] == ["Inngående balanse", "Okt", "Utgående saldo"]


def test_a_whole_year_ends_on_the_first_of_january():
    ledger = _Ledger({})
    _run(ledger, "2025-01-01", "2025-12-31")
    assert len(ledger.asked) == 12 and ledger.asked[-1] == ("2025-12-01", "2026-01-01")
