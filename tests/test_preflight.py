import preflight


def test_payables_tie_on_their_own_side():
    """Tripletex returns Leverandørreskontro negative, the same side as 2400.

    Negating one of them reported 65 937 kr missing from books that tied to the
    øre, which set the whole preflight to "broken" and told the CFO that no
    payables figure could be quoted.
    """
    assert preflight._tie(-32968.67, -32968.67) == 0.0


def test_receivables_tie_on_their_own_side():
    assert preflight._tie(2007750.0, 2007750.0) == 0.0


def test_tie_still_catches_an_account_on_the_wrong_side():
    # 2400 standing in debit against a credit subledger is a real break, and
    # must not cancel to nothing the way comparing magnitudes would.
    assert abs(preflight._tie(32968.67, -32968.67) - 65937.34) < 1e-6


def test_tie_reports_a_genuine_shortfall():
    assert abs(preflight._tie(-30000.0, -32968.67) - 2968.67) < 1e-6


def test_a_blank_month_cell_means_unchanged_not_zero():
    # Rent is not booked in February, so Saldobalanse leaves its cell blank.
    # The real February cost is the 10 000 on the other account.
    cols = ["Inngående balanse", "Jan", "Feb", "Mars", "Utgående saldo"]
    rows = [{"path": "6300 Husleie", "cells": [0, 12000, None, 24000, 24000]},
            {"path": "6300 Annet", "cells": [0, 5000, 15000, 20000, 20000]}]
    assert preflight._monthly(rows, cols, 6000, 7999) == [
        ("Jan", 17000.0), ("Feb", 10000.0), ("Mars", 17000.0)]


def test_an_account_that_opens_mid_year_starts_from_zero():
    cols = ["Jan", "Feb", "Mars"]
    rows = [{"path": "5000 Lønn", "cells": [None, 40000, 80000]}]
    assert preflight._monthly(rows, cols, 5000, 5999) == [
        ("Jan", 0.0), ("Feb", 40000.0), ("Mars", 40000.0)]


# ------------------------------------------- is the month that matters posted
from datetime import date


def _series(months, values):
    return list(zip(months, values))


MONTHS_TO_OCT = ["Juni", "Juli", "Aug", "Sept", "Okt"]
# A month-end invoicer: 300k invoiced on the last day of each month, 200k payroll.
REVENUE = _series(MONTHS_TO_OCT, [-300000, -300000, -300000, -300000, 0])
PAYROLL = _series(MONTHS_TO_OCT, [200000, 200000, 200000, 200000, 0])


def _by_id(checks):
    return {c["id"]: c for c in checks}


def test_a_month_end_invoicer_is_not_warned_mid_month():
    # 15 October, nothing invoiced yet and payroll not yet run: business as usual.
    checks = _by_id(preflight._completeness(REVENUE, PAYROLL, date(2026, 10, 15)))
    assert checks["revenue_month"]["status"] == "ok"        # September was full
    assert "open_month" not in checks
    assert all(c["status"] in ("ok", "unavailable") for c in checks.values())


def test_payroll_in_and_revenue_out_is_a_note_not_a_card():
    payroll = PAYROLL[:-1] + [("Okt", 200000)]
    checks = _by_id(preflight._completeness(REVENUE, payroll, date(2026, 10, 22)))
    assert checks["open_month"]["status"] == "note"
    assert checks["revenue_month"]["status"] == "ok"        # no invoicing card


def test_a_steady_invoicer_halfway_through_is_fine():
    revenue = REVENUE[:-1] + [("Okt", -140000)]             # 47 % on the 15th
    payroll = PAYROLL[:-1] + [("Okt", 200000)]
    checks = _by_id(preflight._completeness(revenue, payroll, date(2026, 10, 15)))
    assert "open_month" not in checks


def test_a_closed_month_without_its_invoicing_warns_after_the_grace():
    revenue = _series(MONTHS_TO_OCT, [-300000, -300000, -300000, -20000, 0])
    # 2 October 2026 is the 2nd working day: too early to judge September.
    early = _by_id(preflight._completeness(revenue, PAYROLL, date(2026, 10, 2)))
    assert early["revenue_month"]["status"] == "ok"
    # 8 October is the 6th working day.
    late = _by_id(preflight._completeness(revenue, PAYROLL, date(2026, 10, 8)))
    assert late["revenue_month"]["status"] == "warn"
    assert late["revenue_month"]["headline"].startswith("Sept:")


def test_january_has_no_closed_month_to_judge():
    checks = _by_id(preflight._completeness([("Jan", 0)], [("Jan", 0)],
                                            date(2026, 1, 20)))
    assert checks["revenue_month"]["status"] == "unavailable"


# ------------------------------------------- a failure is not a clean bill
import asyncio


class _Tripletex:
    """Answers everything sensibly except what it is told to fail."""

    def __init__(self, fail=()):
        self.fail = set(fail)

    async def call(self, tool, args=None):
        name = (args or {}).get("report_name", tool)
        if name in self.fail:
            raise RuntimeError("503 fra Tripletex")
        if tool == "get_voucher_inbox_count":
            return {"count": 0}
        if tool == "get_supplier_invoices_for_approval":
            return {"invoices": []}
        return {"table": {"rows": [], "columns": []}}


def _build(fail=()):
    original = preflight.mcp
    preflight.mcp = _Tripletex(fail)
    try:
        return asyncio.run(preflight.build(date(2026, 10, 15)))
    finally:
        preflight.mcp = original


def test_a_failed_trial_balance_is_not_clean_books():
    pf = _build(fail={"Saldobalanse per måned"})
    checks = {c["id"]: c for c in pf["checks"]}
    assert pf["condition"] == "incomplete"
    assert pf["failed"] == ["saldobalanse"]
    # Previously "ok": no rows means no frozen accounts were found.
    assert checks["stale_accrual"]["status"] == "unavailable"
    for cid in ("ap_posting", "ar_tie", "ap_tie", "revenue_month", "payroll_month"):
        assert checks[cid]["status"] == "unavailable", cid


def test_one_failed_subledger_makes_the_books_incomplete():
    pf = _build(fail={"Kundereskontro"})
    assert pf["condition"] == "incomplete" and pf["failed"] == ["kundereskontro"]


def test_the_agent_is_told_what_could_not_be_checked():
    text = preflight.briefing(_build(fail={"Saldobalanse per måned"}))
    assert "Ikke alt kunne kontrolleres." in text
    assert "Periodiseringer som står stille" in text.split("Could not be checked")[1]
