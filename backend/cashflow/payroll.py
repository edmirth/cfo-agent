"""Pay days and what leaves on them."""
import statistics
from datetime import date

import commitments
import company
import workdays

from .common import MONTH_NAMES, PAID_FROM, PAYROLL_MONTHS, WAGE_ACCOUNTS, _add_months
from .common import AGA_ACCRUED
from .models import FlowKind, Pay, Sources
from .common import _next_month
from .ledger import _accrued_this_month


# **The feriepenger month.** In the month holiday pay goes out, staff draw
# feriepenger instead of ordinary salary and that month's salary is withheld in
# the same run. commitments.py already dates the accrued feriepenger to it; if
# the ordinary salary is also charged there, that month pays the staff twice.
FERIE_WEEKS = 5              # ferieloven gives 4 + 1, most agreements give 5
VIRKEDAGER = 26              # the six-day week holiday and feriepenger run on


def _ferie_withheld() -> tuple[float, int, bool]:
    """How much of one month's ordinary salary the holiday month withholds.

    Holiday is counted in virkedager, six to the week, twenty-six to the month
    — the same convention feriepenger itself is calculated on. Five weeks is
    thirty of them, more than a month, so for staff on a monthly salary the
    whole run is withheld and feriepenger is the only payment. Four weeks
    withholds twenty-four twenty-sixths and a fraction of the salary still
    goes out. Capped at one: nobody pays negative wages.
    """
    stated = company.setting("ferie_uker")
    ok = stated is not None and 0 <= int(stated) <= 10
    weeks = int(stated) if ok else FERIE_WEEKS
    return min(1.0, weeks * 6 / VIRKEDAGER), weeks, bool(ok)


def _pay_days(today: date, horizon: date,
              paid_before: date | None = None) -> list[tuple[int, int, date]]:
    """Every pay day in the window, with the month it pays for.

    Public to the module rather than inlined in `_payroll_runs`, because the
    briefing needs the same answer: its notes about December and the holiday
    month describe what the payroll run does, so they have to be gated on the
    run being in the window — not on the month merely being touched by it,
    which is a different question at both edges of thirteen weeks.

    A pay day before `paid_before`, the first day the bank figure does not
    cover, is in that figure; one after it is not, however the calendar has
    moved on, and is paid in the forecast (in this week). The day after a pay
    day the feed has usually not delivered it yet.
    """
    cutoff = min(paid_before or today, today)
    out, month = [], date(cutoff.year, cutoff.month, 1)
    while True:
        # The same pay day commitments uses — imported, not reimplemented. Two
        # implementations disagreed and the forecast lost a December payroll.
        pay_day = workdays.backward(commitments.payday(month.year, month.month))
        if pay_day >= horizon:
            break
        if pay_day >= cutoff:
            out.append((month.year, month.month, pay_day))
        month = _next_month(month)
    return out


def _payroll_runs(today: date, horizon: date, payroll_cash: float,
                  aga_monthly: float = 0.0, aga_booked: float = 0.0,
                  paid_before: date | None = None) -> list[dict]:
    """Every pay day between now and the horizon, and what leaves on it.

    Gross, not net: from 2026 the trekk goes to Skatteetaten the same day as
    the salary, so the whole of it leaves the account on pay day. December is
    no exception — see HALF_TAX_MONTH above. The feriepenger month is, and it
    is the one month that can produce no flow at all.
    """
    ferie_month = commitments.ferie_month()
    withheld, _, _ = _ferie_withheld()
    flows = []
    for year, month_no, pay_day in _pay_days(today, horizon, paid_before):
        month = date(year, month_no, 1)
        amount, label = payroll_cash, "Lønn og skattetrekk"
        if month.month == ferie_month and withheld:
            amount = payroll_cash * (1 - withheld)
            label = (f"Lønn, {round(withheld * 100)} % holdt igjen mot "
                     f"feriepengene")
        # A fully withheld month is left off the table rather than shown as a
        # zero: the feriepenger line from commitments is the payment that
        # month, and a 0 kr wage line beside it reads like an error.
        if round(amount) > 0:
            flows.append({"date": pay_day, "amount": -amount,
                          "kind": FlowKind.WAGES, "label": label})

        # Arbeidsgiveravgift on that run, due on the term covering the month it
        # is paid in, and added to the 2770 balance commitments already dates
        # rather than repeating it. What keeps the two apart is the ledger, not
        # the pay day: 2770 is credited when the payroll is *journalised*,
        # which is not the same event as the a-melding being filed, so a month
        # already journalised is already on that balance and is skipped here.
        # The pay-day position alone got the right answer only because this
        # bookkeeper posts the run on the day it is paid.
        #
        # Scaled with the wage, so a withheld holiday month carries no
        # employer's contribution either — the feriepenger's own AGA sits on
        # 2785 and commitments dates it to the payout.
        share = (amount / payroll_cash) if payroll_cash else 0.0
        aga = aga_monthly * share
        already = (aga_booked > 0.5
                   and (month.year, month.month) == (today.year, today.month))
        if round(aga) > 0 and not already:
            due = workdays.forward(commitments.term_due(
                month.year, month.month, commitments.SKATT_TERMS))
            if today <= due < horizon:
                flows.append({
                    "date": due, "amount": -aga, "kind": FlowKind.AGA_FUTURE,
                    "label": f"Arbeidsgiveravgift på lønn "
                             f"{MONTH_NAMES[month.month - 1]}"})
    return flows
PAYROLL_MIN = 3              # months measured before the vouchers are trusted
PAYDAY_WINDOW = 3            # days either side of the pay day that are its run


def payroll_paid(postings: list[dict], today: date) -> dict | None:
    """What each month's pay day paid out, from the payroll vouchers.

    A payroll voucher is one that touches the wage accounts. What it pays is
    the money leaving the bank in it, net pay plus the withheld tax; where the
    payment was not booked in it, what it leaves owing on the trekk and net-pay
    accounts instead. Both are the same sum, so one figure covers the two:
    minus everything the voucher puts on PAID_FROM. A reversed voucher cancels
    its original, and an accrual booked to the wage accounts touches none of
    them.

    The pay day's own run is the vouchers within PAYDAY_WINDOW days of it.
    Everything else that month is an extra run, kept apart: September's at the
    first customer followed a one-off job in August. The holiday-pay month is
    left out. Returns the median pay day over the months measured, or None
    with fewer than PAYROLL_MIN of them."""
    def acct(p):
        try:
            return int(str(p.get("accountNumber"))[:4])
        except (TypeError, ValueError):
            return None
    wage_vouchers = {p.get("voucherId") for p in postings
                     if p.get("voucherId") is not None and acct(p) is not None
                     and WAGE_ACCOUNTS[0] <= acct(p) <= WAGE_ACCOUNTS[1]}
    paid: dict = {}
    for p in postings:
        n = acct(p)
        if p.get("voucherId") not in wage_vouchers or n is None:
            continue
        if not any(lo <= n <= hi for lo, hi in PAID_FROM):
            continue
        try:
            when = date.fromisoformat(str(p.get("date"))[:10])
        except ValueError:
            continue
        paid[when] = paid.get(when, 0.0) - float(p.get("amount") or 0)
    ferie = commitments.ferie_month()
    months: dict = {}
    for when, amount in paid.items():
        m = months.setdefault((when.year, when.month), {"run": 0.0, "extra": 0.0})
        day = workdays.backward(commitments.payday(when.year, when.month))
        m["run" if abs((when - day).days) <= PAYDAY_WINDOW else "extra"] += amount
    this = (today.year, today.month)
    closed = [_add_months(*this, -n) for n in range(1, PAYROLL_MONTHS + 1)]
    runs = [(k, months[k]) for k in closed
            if k in months and k[1] != ferie and months[k]["run"] > 0.5]
    if len(runs) < PAYROLL_MIN:
        return None
    return {"per_run": round(statistics.median(m["run"] for _, m in runs), 2),
            "months": [{"month": f"{MONTH_NAMES[k[1] - 1]} {k[0]}",
                        "run": round(m["run"], 2), "extra": round(m["extra"], 2)}
                       for k, m in reversed(runs)]}


def _payroll(src: Sources, rates: dict, today: date, horizon: date, aga_paid: float,
             flows: list, warnings: list[str]) -> Pay:
    """Every pay day in the window, and its employer's contribution."""
    # What this month's payroll has already put on 2770, if it has been run
    # and posted. A liability is a credit balance, so an accrual is negative,
    # and a term paid this month comes off the movement first (card 68).
    aga_booked = _accrued_this_month(src.rows, src.columns, AGA_ACCRUED, aga_paid)
    # What a pay day really pays, where the payroll vouchers say so; the wage
    # accounts otherwise.
    wages_paid = src.wages_paid
    if isinstance(wages_paid, dict) and "unread" in wages_paid:
        warnings.append(
            "Lønnsbilagene kunne ikke leses, så lønningsdagen er regnet fra "
            "lønnskontoene i stedet for det tidligere lønningsdager har betalt. "
            "Det kan være for mye, fordi kontoene også har periodisering og "
            "feriepenger i seg.")
    measured = wages_paid if isinstance(wages_paid, dict) and "per_run" in wages_paid else None
    per_day = measured["per_run"] if measured else rates["wages_cash"]
    # The bank figure is as of its last line, not today: a pay day after it is
    # still to go out, as commitments dates the taxes.
    try:
        paid_before = date.fromisoformat(src.com.get("paid_before") or "")
    except ValueError:
        paid_before = today
    flows += _payroll_runs(today, horizon, per_day,
                               rates["aga"], aga_booked, paid_before)
    months = [m for _, m, _ in _pay_days(today, horizon, paid_before)]
    return Pay(per_day, measured, months)
