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


def test_the_running_term_is_due_on_its_own_deadline():
    # Once Jul-Aug has been paid on 12 October, the next settlement is
    # Sept-Oct's own, on 10 December — not the one after it in February.
    def running(today):
        return commitments._shift("mva_lopende",
                                  commitments._running_due(today, commitments.MVA_TERMS))
    assert running(date(2026, 10, 5)) == date(2026, 12, 10)
    assert running(date(2026, 10, 15)) == date(2026, 12, 10)
    assert running(date(2026, 12, 15)) == date(2027, 2, 10)
    assert running(date(2026, 6, 15)) == date(2026, 8, 31)


def test_a_term_past_its_deadline_is_not_split_off_again():
    # 15 October: Jul-Aug was paid straight off 2700 on the 12th, so the August
    # column still shows it, but all that is left is this term's VAT.
    assert commitments._completed_term(date(2026, 10, 12)) == (8, date(2026, 10, 10))
    assert commitments._completed_term(date(2026, 10, 15)) is None
    cols = COLUMNS[:-1] + ["Okt", "Utgående saldo"]
    rows = [{"path": "2700 Utgående merverdiavgift, høy sats",
             "cells": [0] + [0] * 7 + [-939143.19, -1050000, -200000, -200000]}]
    items = [_running(200000.0)]
    commitments._split_vat(items, rows, cols, date(2026, 10, 15))
    assert [i["id"] for i in items] == ["mva_lopende"]
    assert items[0]["amount"] == 200000.0


# ------------------------------------------------------ paid ahead of time
import asyncio

AUG_PAID_COLS = COLUMNS[:-1] + ["Okt", "Utgående saldo"]
AUG_PAID_ROWS = [{"path": "2700 Utgående merverdiavgift, høy sats",
                  "cells": [0] + [0] * 7 + [-939143.19, -1050000, -200000, -200000]}]


class _Postings:
    def __init__(self, postings=None, fail=False):
        self.postings, self.fail, self.asked = postings or [], fail, []

    async def call(self, tool, args):
        self.asked.append((tool, args))
        if self.fail:
            raise RuntimeError("Tripletex svarte ikke")
        # A hundred at a time, like the real endpoint.
        page = self.postings[args["from"]:args["from"] + args["count"]]
        return {"postings": page,
                "hasMore": args["from"] + args["count"] < len(self.postings)}


def _paid_early(stub, today=date(2026, 10, 8)):
    original = commitments.mcp
    commitments.mcp = stub
    try:
        return asyncio.run(commitments._paid_early(AUG_PAID_ROWS, AUG_PAID_COLS, today))
    finally:
        commitments.mcp = original


def test_a_term_paid_before_its_deadline_is_not_split_off():
    # Jul-Aug paid on 5 October straight against 2700; on the 8th all that is
    # left is Sept-Oct, due 10 December — not 12 October.
    stub = _Postings([{"voucherId": 7, "amount": 939143.19},
                      {"voucherId": 8, "amount": -12500.0}])
    assert _paid_early(stub) is True
    tool, args = stub.asked[0]
    assert tool == "search_ledger_postings"
    assert args["dateFrom"] == "2026-09-01" and args["dateTo"] == "2026-10-09"
    items = [_running(200000.0)]
    commitments._split_vat(items, AUG_PAID_ROWS, AUG_PAID_COLS, date(2026, 10, 8),
                           paid=True)
    assert [(i["id"], i["due"]) for i in items] == [("mva_lopende", "2026-12-10")]


def test_a_payment_split_across_output_and_input_vat_still_counts():
    # One settlement voucher: debit 2700 for the output, credit 2710 for the input.
    stub = _Postings([{"voucherId": 7, "amount": 1100000.0},
                      {"voucherId": 7, "amount": -160856.81}])
    assert _paid_early(stub) is True


def test_unpaid_term_is_still_split():
    stub = _Postings([{"voucherId": 8, "amount": -12500.0},
                      {"voucherId": 9, "amount": 3000.0}])
    assert _paid_early(stub) is False


def test_unreadable_postings_assume_unpaid():
    assert _paid_early(_Postings(fail=True)) is False


def test_postings_are_only_asked_for_while_a_term_awaits_its_deadline():
    stub = _Postings()
    assert _paid_early(stub, today=date(2026, 10, 15)) is False   # deadline passed
    assert stub.asked == []


def test_a_term_ends_in_the_year_before_a_february_deadline():
    assert commitments._term_end(12, date(2027, 2, 10)) == date(2026, 12, 31)
    assert commitments._term_end(8, date(2026, 10, 10)) == date(2026, 8, 31)


def test_the_payment_is_found_past_the_first_page():
    # 250 invoice lines before the payment voucher, as in a busy month.
    lines = [{"voucherId": 1000 + n, "amount": -1127.5} for n in range(250)]
    stub = _Postings(lines + [{"voucherId": 7, "amount": 939143.19}])
    assert _paid_early(stub) is True
    assert [a["from"] for _, a in stub.asked] == [0, 100, 200]
    assert all(a["count"] == 100 for _, a in stub.asked)


def test_too_many_postings_to_read_assumes_unpaid():
    lines = [{"voucherId": 7, "amount": 939143.19}] + [
        {"voucherId": n, "amount": -1.0} for n in range(2100)]
    assert _paid_early(_Postings(lines)) is False


# ------------------------------------------------------- corporation tax
def test_this_years_tax_is_due_next_year_all_year_round():
    for today in (date(2027, 1, 10), date(2027, 3, 1), date(2027, 4, 20),
                  date(2027, 10, 4), date(2027, 12, 31)):
        assert commitments._this_years_tax_due(today) == date(2028, 2, 15), today


def test_booked_tax_keeps_this_years_instalments():
    # Last year's tax on 2500 is still due in this February and April.
    assert commitments._tax_due(date(2027, 1, 10)) == date(2027, 2, 15)
    assert commitments._tax_due(date(2027, 3, 1)) == date(2027, 4, 15)


def test_unbooked_profit_tax_is_not_in_the_forecast_in_january():
    class _Reports:
        async def call(self, tool, args):
            if args["report_name"] == "Resultatrapport":
                return {"table": {"rows": [
                    {"path": "Ordinært resultat før skattekostnad", "cells": [500000]}]}}
            return {"table": {"rows": [{"path": "1920 Bank", "cells": [2000000]}],
                              "columns": [{"name": "Utgående saldo"}]}}
    original = commitments.mcp
    commitments.mcp = _Reports()
    try:
        out = asyncio.run(commitments.build(date(2027, 1, 10)))
    finally:
        commitments.mcp = original
    tax = next(i for i in out["items"] if i["id"] == "arets_skatt")
    assert tax["due"] == "2028-02-15" and tax["amount"] == 110000.0
    assert out["totals"]["within_90"] == 0 and out["totals"]["later"] == 110000.0


# ------------------------------------------- a deadline on a weekend
def test_a_weekend_deadline_is_still_owed_on_the_monday_it_moves_to():
    """15 November 2026 is a Sunday, so the employer's contribution is due
    Monday the 16th. Compared on the literal date it had passed by then, and
    the money due that day was dated two months on, to 15 January."""
    due = commitments._next_due(date(2026, 11, 16), commitments.SKATT_TERMS)
    assert commitments._shift("aga", due) == date(2026, 11, 16)
    # 10 October 2026 is a Saturday: settled VAT is due Monday the 12th.
    due = commitments._next_due(date(2026, 10, 12), commitments.MVA_TERMS)
    assert commitments._shift("mva_oppgjor", due) == date(2026, 10, 12)
    # The day after, it has gone and the next term is the one owed.
    assert commitments._next_due(date(2026, 10, 13), commitments.MVA_TERMS) \
        == date(2026, 12, 10)


def test_booked_tax_due_on_a_weekend_is_owed_on_the_monday():
    # 15 February 2026 is a Sunday.
    assert commitments._tax_due(date(2026, 2, 16)) == date(2026, 2, 15)
    assert commitments._tax_due(date(2026, 2, 17)) == date(2026, 4, 15)
