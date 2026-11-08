"""Statutory amounts on the settlement accounts, dated by the term they are for.

A term past its deadline has been paid (the company pays its VAT and payroll
taxes on time). Read as one balance and dated to the next settlement, a term
paid but not yet booked as paid was paid a second time.
"""
import asyncio
from datetime import date

import commitments
import company

COLUMNS = ["Inngående balanse", "Jan", "Utgående saldo"]


class _Postings:
    def __init__(self, postings=None, fail=False):
        self.postings, self.fail, self.asked = postings or [], fail, []

    async def call(self, tool, args):
        self.asked.append((tool, args))
        if self.fail:
            raise RuntimeError("Tripletex svarte ikke")
        page = self.postings[args["from"]:args["from"] + args["count"]]
        return {"postings": page,
                "hasMore": args["from"] + args["count"] < len(self.postings)}


def _item(gid: str, amount: float) -> dict:
    g = next(g for g in commitments.GROUPS if g.id == gid)
    return {"id": gid, "label": g.label, "plain": g.plain, "amount": amount,
            "kind": g.kind, "due": "2099-01-01", "days": 0, "accounts": [],
            "estimated": False, "assumed_due": False}


def _rows(account: str, opening: float = 0.0) -> list[dict]:
    return [{"path": f"{account} Konto", "cells": [-opening, 0, 0]}]


def _credit(day: str, amount: float) -> dict:
    return {"date": day, "amount": -amount}


def _debit(day: str, amount: float) -> dict:
    return {"date": day, "amount": amount}


def _dated(gid, amount, postings, today, account, opening=0.0, fail=False):
    stub = _Postings(postings, fail=fail)
    original = commitments.mcp
    commitments.mcp = stub
    try:
        out = asyncio.run(commitments._date_by_term(
            _item(gid, amount), _rows(account, opening), COLUMNS, today))
    finally:
        commitments.mcp = original
    return out, stub


def _parts(out):
    parts, paid = out
    return [(p["due"], p["amount"]) for p in parts], paid


# ------------------------------------------------------------------- VAT, 2740
def test_vat_paid_on_its_deadline_but_not_booked_is_not_paid_again():
    """17 October 2026, the case that was seen: Jul-Aug moved to 2740 with the return,
    paid on Monday 12 October, the payment not booked. It was forecast to
    leave again on 10 December."""
    out, _ = _dated("mva_oppgjor", 800_000.0,
                    [_credit("2026-07-01", 640_000.0), _debit("2026-08-31", 640_000.0),
                     _credit("2026-10-09", 800_000.0)],
                    date(2026, 10, 17), "2740")
    assert _parts(out) == ([], 800_000.0)


def test_a_transfer_dated_the_last_day_of_the_term_is_that_term():
    out, _ = _dated("mva_oppgjor", 800_000.0, [_credit("2026-08-31", 800_000.0)],
                    date(2026, 10, 17), "2740")
    assert _parts(out) == ([], 800_000.0)


def test_before_its_deadline_the_term_is_still_owed_on_the_monday():
    """10 October 2026 is a Saturday, so it is owed on the 12th."""
    out, _ = _dated("mva_oppgjor", 800_000.0, [_credit("2026-10-09", 800_000.0)],
                    date(2026, 10, 11), "2740")
    assert _parts(out) == ([("2026-10-12", 800_000.0)], 0.0)


def test_the_next_term_keeps_its_own_deadline_beside_an_unbooked_payment():
    """5 November: Sep-Oct moved to 2740 on top of the paid Jul-Aug."""
    out, _ = _dated("mva_oppgjor", 1_500_000.0,
                    [_credit("2026-10-09", 800_000.0), _credit("2026-11-03", 700_000.0)],
                    date(2026, 11, 5), "2740")
    assert _parts(out) == ([("2026-12-10", 700_000.0)], 800_000.0)


def test_a_booked_payment_settles_the_oldest_term():
    out, _ = _dated("mva_oppgjor", 700_000.0,
                    [_credit("2026-10-09", 800_000.0), _debit("2026-10-12", 800_000.0),
                     _credit("2026-11-03", 700_000.0)],
                    date(2026, 11, 5), "2740")
    assert _parts(out) == ([("2026-12-10", 700_000.0)], 0.0)


def test_last_years_closing_term_is_owed_in_february():
    """Nov-Dec 2025 carried into 2026 on 2740, owed on 10 February."""
    out, _ = _dated("mva_oppgjor", 500_000.0, [], date(2026, 1, 20), "2740",
                    opening=500_000.0)
    assert _parts(out) == ([("2026-02-10", 500_000.0)], 0.0)
    out, _ = _dated("mva_oppgjor", 500_000.0, [], date(2026, 2, 15), "2740",
                    opening=500_000.0)
    assert _parts(out) == ([], 500_000.0)


def test_postings_that_cannot_be_read_leave_the_item_as_it_was():
    out, _ = _dated("mva_oppgjor", 800_000.0, [], date(2026, 10, 17), "2740", fail=True)
    assert out is None


def test_postings_that_do_not_explain_the_balance_leave_it_as_it_was():
    out, _ = _dated("mva_oppgjor", 800_000.0, [_credit("2026-10-09", 500_000.0)],
                    date(2026, 10, 17), "2740")
    assert out is None


def test_the_postings_are_read_for_the_settlement_account_this_year():
    _, stub = _dated("mva_oppgjor", 800_000.0, [_credit("2026-10-09", 800_000.0)],
                     date(2026, 10, 17), "2740")
    tool, args = stub.asked[0]
    assert tool == "search_ledger_postings"
    assert (args["accountNumberFrom"], args["accountNumberTo"]) == (2740, 2749)
    assert args["dateFrom"] == "2026-01-01" and args["dateTo"] == "2026-10-18"


# ------------------------------------------- employer's contribution, 2770
def test_employers_contribution_follows_its_own_term():
    """Sep-Oct is owed on 15 November 2026, a Sunday, so on the 16th."""
    posts = [_credit("2026-09-30", 120_000.0), _credit("2026-10-31", 125_000.0)]
    out, _ = _dated("aga", 245_000.0, posts, date(2026, 11, 10), "2770")
    assert _parts(out) == ([("2026-11-16", 245_000.0)], 0.0)
    out, _ = _dated("aga", 245_000.0, posts, date(2026, 11, 20), "2770")
    assert _parts(out) == ([], 245_000.0)


# ----------------------------------------------------- withheld tax, 2600
def test_withheld_tax_is_paid_with_its_salary():
    original = company.setting
    company.setting = lambda k, d=None: {"lonn_utbetalingsdag": 20}.get(k, d)
    try:
        posts = [_credit("2026-10-20", 300_000.0), _credit("2026-11-05", 310_000.0)]
        out, _ = _dated("forskuddstrekk", 610_000.0, posts, date(2026, 11, 8), "2600")
        assert _parts(out) == ([("2026-11-20", 310_000.0)], 300_000.0)
    finally:
        company.setting = original
