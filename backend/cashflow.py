"""Thirteen weeks of cash, week by week.

The deliverable that defines the job. `commitments.py` answers "how much of
this is mine"; this answers the question underneath it — *will I make it to
Christmas, and which week is the tight one*. An owner who knows his low point
is in the week of 12 October can act in September. Told in November, he can
only apologise.

Two lines, never one:

- **Committed** — money already invoiced in or out, plus payroll and the tax
  dates that arrive whether or not anyone sells anything. This is the floor.
- **Expected** — committed plus continued trading: the invoicing that normally
  goes out each month, collected on the terms this company's customers
  actually pay on, less the running costs.

Showing only the first makes a healthy company look dying; showing only the
second hides how much of the comfort is a forecast rather than a fact. A CFO
shows both and says which is which.

Everything modelled is declared in `assumptions` and shown to the owner in the
answer. Nothing here is a black box: he is being asked to make decisions on it.
"""
import asyncio
import logging
import statistics
from calendar import monthrange
from datetime import date, timedelta

import commitments
import company
import freshness
import workdays
from mcp_client import mcp
# Shared with the pre-flight rather than copied: two readings of the monthly
# balance report that drift apart are worse than one import.
from preflight import _account, _monthly, _rows

log = logging.getLogger("cfo.cashflow")

CACHE_SECONDS = 600

WEEKS = 13
AR_MONTHS_BACK = 12          # how far back to look for still-open invoices
LATE_SPREAD_WEEKS = 3        # already-overdue invoices land across this many
PAY_LAG_DAYS = 7             # customers pay this late even when not "late"
# No WITHHOLDING_SHARE any more. Until 2026 the tax withheld from wages was held
# back and settled on a bimonthly term, so only the net left on pay day. From
# 2026 there is no skattetrekkskonto and the trekk goes to Skatteetaten the same
# day as the salary — so what leaves the account on pay day is the gross.
# No TRAILING_MONTHS either: it said the run-rates used a trailing window, and
# they never did — `_run_rates` takes a median over every closed month. A
# constant that documents behaviour the code does not have is worse than none.

# Two Norwegian payroll facts that break the twelve-identical-months assumption.
#
# **Half tax in December.** The tax tables take half the usual trekk from the
# December run, so staff take home more. It does not move the company's cash:
# since 2026 the trekk leaves on pay day with the salary, so net plus trekk is
# the same gross in December as in March — the split between the employee and
# Skatteetaten is all that changes, and the other half is never withheld later.
# Modelled as what it is, a declaration rather than a number, because inflating
# December's outflow would be the old pre-2026 regime in disguise.
#
# **The feriepenger month.** In the month holiday pay goes out, staff draw
# feriepenger instead of ordinary salary and that month's salary is withheld in
# the same run. commitments.py already dates the accrued feriepenger to it; if
# the ordinary salary is also charged there, that month pays the staff twice.
HALF_TAX_MONTH = 12
FERIE_WEEKS = 5              # ferieloven gives 4 + 1, most agreements give 5
VIRKEDAGER = 26              # the six-day week holiday and feriepenger run on

MONTH_NAMES = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
               "august", "september", "oktober", "november", "desember"]

# Taken from commitments.py, which already dates them. Wages and supplier bills
# are excluded there and modelled here instead — counting both would charge the
# same krone twice.
#
# `annen_gjeld` is here because nothing else carries it: 2990/2991 is never
# invoiced, so the payables list cannot see it, and it was leaving the forecast
# entirely. `leverandorgjeld` stays out, being the payables list's own job, and
# `skyldig_lonn` stays out because the pay-day run already pays it.
#
# `ansatte_eiere` is deliberately NOT here. commitments dates it to today, but
# that is an assumption about undated debt, not a fact — money owed to the owner
# is usually not demand debt, and scheduling 38 000 kr out of this week would
# raise an alarm the ledger does not support. Named so the gap is a decision.
STATUTORY_FROM_COMMITMENTS = {
    "mva_oppgjor", "mva_lopende", "mva_forrige_termin", "aga", "aga_ferie",
    "feriepenger", "betalbar_skatt", "arets_skatt", "forskuddstrekk",
    "annen_gjeld",
}


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _month_bounds(anchor: date, back: int) -> tuple[date, date]:
    """First day of the month, and the first day of the next — end EXCLUSIVE.

    search_invoices treats invoiceDateTo as exclusive. Passing the last day of
    the month therefore dropped every invoice dated on it, and this company
    invoices monthly at month end, so most of its receivables were invisible:
    1 215 575 kr of open invoices against 2 539 600 kr on account 1500, and the
    missing half was spread over three weeks as an unexplained residual.
    """
    year, month = anchor.year, anchor.month - back
    while month < 1:
        month += 12
        year -= 1
    first = date(year, month, 1)
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return first, nxt


def _kr(v) -> str:
    if v is None:
        return "—"
    return f"{round(v):,}".replace(",", " ")


async def _open_invoices(today: date, tool: str, what: str, id_key: str,
                         outstanding_key: str, name_key: str) -> tuple[list, list]:
    """Open invoices with their due dates.

    The search caps at 100 rows per call and offers no paging, so the range is
    walked a month at a time. A month that comes back exactly full may have
    been truncated, and that is reported rather than quietly under-counting.

    Both registers answer under `rows`. They did not always appear to: the
    supplier call read `invoices`, a key the response has never carried, so
    `r.get(...) or []` was empty every time and every supplier bill was dropped
    before it reached the forecast — silently, because the call itself
    succeeded. `what` names the register in the warnings, since two sources
    sharing one sentence left nobody able to tell which one was short.
    """
    calls = []
    for back in range(AR_MONTHS_BACK):
        start, end = _month_bounds(today, back)
        calls.append(mcp.call(tool, {"invoiceDateFrom": start.isoformat(),
                                     "invoiceDateTo": end.isoformat(),
                                     "count": 100}))
    results = await asyncio.gather(*calls, return_exceptions=True)

    seen, out, warnings = set(), [], []
    for back, r in enumerate(results):
        start, _ = _month_bounds(today, back)
        when = f"{MONTH_NAMES[start.month - 1]} {start.year}"
        if isinstance(r, Exception):
            warnings.append(f"{what} for {when} kunne ikke hentes ({r}). "
                            f"Tallene under er ufullstendige.")
            continue
        rows = r.get("rows") or []
        if len(rows) >= 100:
            warnings.append(f"Det er minst 100 {what.lower()} i {when}; lista "
                            f"kan være avkortet.")
        for row in rows:
            # A row with no id is not a duplicate of the last row with no id.
            # Putting None in `seen` made the first one swallow every one after.
            key = row.get(id_key)
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            amount = row.get(outstanding_key) or 0
            if not amount or not row.get("dueDate"):
                continue
            out.append({"id": key, "name": row.get(name_key) or "",
                        "due": row["dueDate"], "invoiced": row.get("invoiceDate"),
                        "amount": float(amount),
                        # Carried for the reminder drafts in cards.py: a chase
                        # letter without invoice numbers is not a chase letter.
                        "number": row.get("invoiceNumber"),
                        "email": row.get("customerEmail") or "",
                        "url": row.get("url") or ""})
    return out, warnings


def _schedule_receipts(invoices: list, today: date) -> list:
    """When the money actually lands.

    An invoice that is already overdue will not arrive the day you notice it,
    and one that is not yet due will not arrive on the dot either. Overdue
    invoices are spread over the next few weeks; the rest are dated from their
    due date plus the lag customers take anyway.
    """
    flows, overdue = [], []
    for inv in invoices:
        try:
            due = date.fromisoformat(inv["due"])
        except (ValueError, TypeError):
            continue
        if due < today:
            overdue.append(inv)
        else:
            flows.append({"date": due + timedelta(days=PAY_LAG_DAYS),
                          "amount": inv["amount"], "kind": "ar",
                          "label": f"Faktura til {inv['name']}"})
    if overdue:
        total = sum(i["amount"] for i in overdue)
        per = total / LATE_SPREAD_WEEKS
        for w in range(LATE_SPREAD_WEEKS):
            flows.append({"date": today + timedelta(days=7 * (w + 1)),
                          "amount": per, "kind": "ar_late",
                          "label": f"Forfalte fakturaer ({len(overdue)} stk), "
                                   f"fordelt over {LATE_SPREAD_WEEKS} uker"})
    return flows


def _schedule_payments(bills: list, today: date) -> list:
    """When our own bills leave. A bill not yet due goes on its due date; one
    already overdue goes this week. The customer scheduler above must not be
    reused here — it adds the lag customers take, and spreads the overdue
    book over weeks, both of which understate what leaves the account soon."""
    flows = []
    for bill in bills:
        try:
            due = date.fromisoformat(bill["due"])
        except (ValueError, TypeError):
            continue
        flows.append({"date": max(due, today), "amount": -bill["amount"],
                      "kind": "ap", "label": f"Regning fra {bill['name']}"})
    return flows


def _run_rates(rows: list, columns: list) -> tuple[dict, list[str]]:
    """Monthly run-rates that a posting backlog cannot poison.

    Costs in this ledger read 122k, 223k, 114k, then 48k, 14k, 13k. Nothing got
    cheaper — supplier invoices stopped being booked. A trailing average takes
    those months at face value and forecasts a third of the real cost, which is
    the most dangerous direction to be wrong in.

    So: median of the closed months, keep those within half to double of it,
    average those. A month that is a fraction of every other month is not a
    cheap month, it is an unposted one — and it is named, not silently dropped.
    The current month is excluded outright, being part-posted by definition.
    """
    notes: list[str] = []

    def series_for(ranges) -> list:
        """One monthly series across several account ranges.

        Summed before the outlier filter runs, never after. Filtering each
        range on its own and adding the results lets a quiet month in one range
        be judged against that range's own median, which is not the question —
        the question is what the whole cost base does in a month.
        """
        merged: dict = {}
        order: list = []
        for low, high in ranges:
            for m, v in _monthly(rows, columns, low, high):
                if m not in merged:
                    merged[m] = 0.0
                    order.append(m)
                merged[m] += v
        return [(m, merged[m]) for m in order]

    def rate(ranges, flip, name):
        series = [(m, v * flip) for m, v in series_for(ranges)][:-1]
        values = [v for _, v in series]
        if not values:
            return 0.0
        mid = statistics.median(values)
        if mid <= 0:
            return sum(values) / len(values)
        kept = [v for _, v in series if 0.5 * mid <= v <= 2 * mid]
        low_months = [m for m, v in series if v < 0.5 * mid]
        high_months = [m for m, v in series if v > 2 * mid]
        # Computed once, and before it is quoted. Quoting it inside the note
        # while `kept` was empty divided by zero and took the whole forecast
        # down with it — reachable whenever credit notes put some months below
        # half the median and others above double it.
        average = (sum(kept) / len(kept)) if kept else mid
        # Format the number on its own: the sentence has commas of its own.
        said = f"{name} er lagt inn med {_kr(average)} kr i måneden."
        if low_months:
            notes.append(
                f"{said} {', '.join(low_months)} er holdt utenfor — de ligger "
                f"langt under de andre månedene, og det betyr nesten alltid at "
                f"bilag ikke er bokført, ikke at kostnaden forsvant.")
        if high_months:
            # Said for the same reason the low ones are. A month at several
            # times the median pulls the rate down when it is dropped, and a
            # rate quietly lowered is the dangerous direction to be wrong in.
            notes.append(
                f"{said} {', '.join(high_months)} er holdt utenfor — de ligger "
                f"langt over de andre månedene. Det er som regel etterslep som "
                f"ble bokført på én gang, eller noe som bare skjedde denne ene "
                f"gangen, men sjekk det før du stoler på snittet.")
        return average

    # Every krone that leaves the account has to be in exactly one of these.
    # 4000-4999 and 5100-5999 were in none of them: varekjøp, underentreprise,
    # pensjon and yrkesskade simply did not exist in the forecast, about
    # 116 000 kr a month against a modelled opex of 156 000.
    OPEX_RANGES = [(4000, 4999),      # varekjøp og underentreprise
                   (5100, 5399),      # andre lønnsposter som ikke er kontant
                   (5402, 5999),      # pensjon, yrkesskade, personalkostnad
                   (6000, 7999)]      # ordinære driftskostnader
    # 5400/5401 are the gap in that list: arbeidsgiveravgift is dated by
    # commitments from its own balance, and taking it here as well would pay it
    # twice.
    rates = {"revenue": rate([(3000, 3999)], -1, "Omsetning"),
             # The full wage cost, accrual and all — what the P&L carries.
             "wages": rate([(5000, 5099)], 1, "Lønn"),
             # What actually leaves on pay day. Feriepenger (5020) is excluded:
             # it accrues monthly but is paid next summer, and commitments
             # already dates it there, so counting it here pays it twice.
             "wages_cash": rate([(5000, 5019), (5030, 5099)], 1, "Lønn"),
             "opex": rate(OPEX_RANGES, 1, "Driftskostnader")}
    return rates, notes


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


def _payroll_runs(today: date, horizon: date, payroll_cash: float) -> list[dict]:
    """Every pay day between now and the horizon, and what leaves on it.

    Gross, not net: from 2026 the trekk goes to Skatteetaten the same day as
    the salary, so the whole of it leaves the account on pay day. December is
    no exception — see HALF_TAX_MONTH above. The feriepenger month is, and it
    is the one month that can produce no flow at all.
    """
    ferie_month = commitments.ferie_month()
    withheld, _, _ = _ferie_withheld()
    flows, month = [], today
    while True:
        # The same pay day commitments uses — imported, not reimplemented. Two
        # implementations disagreed and the forecast lost a December payroll.
        pay_day = workdays.backward(commitments.payday(month.year, month.month))
        if pay_day >= horizon:
            break
        if pay_day >= today:
            amount, label = payroll_cash, "Lønn og skattetrekk"
            if month.month == ferie_month and withheld:
                amount = payroll_cash * (1 - withheld)
                label = (f"Lønn, {round(withheld * 100)} % holdt igjen mot "
                         f"feriepengene")
            # A fully withheld month is left off the table rather than shown as
            # a zero: the feriepenger line from commitments is the payment that
            # month, and a 0 kr wage line beside it reads like an error.
            if round(amount) > 0:
                flows.append({"date": pay_day, "amount": -amount,
                              "kind": "wages", "label": label})
        month = (date(month.year + 1, 1, 1) if month.month == 12
                 else date(month.year, month.month + 1, 1))
    return flows


async def build(today: date | None = None) -> dict:
    today = today or date.today()
    week0 = _monday(today)
    horizon = week0 + timedelta(weeks=WEEKS)
    start_year = f"{today.year}-01-01"

    balance, com, ar, ap = await asyncio.gather(
        mcp.call("fetch_report", {"report_name": "Saldobalanse per måned",
                                  "period_start": start_year,
                                  "period_end": today.isoformat(), "limit": 0}),
        commitments.cached(),
        _open_invoices(today, "search_invoices", "Kundefakturaer", "id",
                       "amountOutstanding", "customerName"),
        # Supplier rows are keyed by voucherId, not id.
        _open_invoices(today, "search_supplier_invoices", "Leverandørfakturaer",
                       "voucherId", "outstandingAmount", "supplierName"),
        return_exceptions=True,
    )
    if isinstance(balance, Exception):
        raise RuntimeError(f"Kunne ikke lese saldobalansen: {balance}")
    warnings: list[str] = []
    if isinstance(com, Exception):
        raise RuntimeError(f"Kunne ikke lese forpliktelsene: {com}")
    ar_open, ar_warn = ([], ["Kundefakturaer kunne ikke hentes."]) \
        if isinstance(ar, Exception) else ar
    ap_open, ap_warn = ([], ["Leverandørfakturaer kunne ikke hentes."]) \
        if isinstance(ap, Exception) else ap
    warnings += ar_warn + ap_warn

    rows = _rows(balance)
    columns = [c.get("name") for c in balance.get("table", {}).get("columns", [])]
    rates, rate_notes = _run_rates(rows, columns)
    warnings += rate_notes
    opening = com["bank"]

    # The open ledger should agree with the invoice list. Where it does not,
    # the forecast is built on the invoices and the gap is declared.
    gl_ar = next((r["cells"][-1] for r in rows if _account(r) == 1500
                  and isinstance((r.get("cells") or [None])[-1], (int, float))), None)
    ar_total = sum(i["amount"] for i in ar_open)
    ar_residual = 0.0
    if gl_ar and gl_ar - ar_total > 1000:
        # The invoice list is short of the ledger, and the ledger is the figure
        # that ties to the general ledger. Dropping the difference would
        # forecast money in that never arrives; keeping it undated would put it
        # in the wrong week. It is carried at the ledger's amount, spread like
        # the overdue book, and declared.
        ar_residual = gl_ar - ar_total
        warnings.append(
            f"Konto 1500 viser {_kr(gl_ar)} kr i kundefordringer, men de åpne "
            f"fakturaene summerer bare til {_kr(ar_total)} kr. De resterende "
            f"{_kr(ar_residual)} kr er tatt med, fordelt over de nærmeste "
            f"ukene, men uten forfallsdato å feste dem til. Noen bør finne ut "
            f"hva de består av.")

    committed: list[dict] = []
    expected: list[dict] = []

    committed += _schedule_receipts(ar_open, today)
    if ar_residual:
        per = ar_residual / LATE_SPREAD_WEEKS
        for w in range(LATE_SPREAD_WEEKS):
            committed.append({"date": today + timedelta(days=7 * (w + 1)),
                              "amount": per, "kind": "ar_unmatched",
                              "label": "Kundefordringer uten kjent faktura"})
    committed += _schedule_payments(ap_open, today)

    # The same check as on 1500 above, which 2400 never had — and the asymmetry
    # was backwards. Being short on receivables flatters the forecast; being
    # short on payables hides money going out, and that is the side nobody
    # noticed was empty for as long as the supplier search read the wrong key.
    # A liability is a credit balance, so what is owed is the balance negated.
    gl_ap = next((-r["cells"][-1] for r in rows if _account(r) == 2400
                  and isinstance((r.get("cells") or [None])[-1], (int, float))), None)
    ap_total = sum(b["amount"] for b in ap_open)
    if gl_ap and gl_ap - ap_total > 1000:
        residual = gl_ap - ap_total
        # Dated to this week, not spread like the receivables. An undated bill
        # is already late more often than it is early, and the overdue book
        # must not be made to look further away than it is.
        committed.append({"date": today, "amount": -residual,
                          "kind": "ap_unmatched",
                          "label": "Leverandørgjeld uten kjent faktura"})
        warnings.append(
            f"Konto 2400 viser {_kr(gl_ap)} kr i leverandørgjeld, men de åpne "
            f"leverandørfakturaene summerer bare til {_kr(ap_total)} kr. De "
            f"resterende {_kr(residual)} kr er lagt inn denne uka, uten "
            f"forfallsdato å feste dem til. Noen bør finne ut hva de består av.")
    elif gl_ap is not None and ap_total - gl_ap > 1000:
        # The other direction, and it is not symmetrical. Here the register
        # claims more is outstanding than the ledger says is owed, so the
        # forecast pays bills the books consider settled. It is NOT trimmed to
        # the ledger: the invoices carry real due dates and the difference has
        # no one invoice to take it from, so capping would mean choosing which
        # supplier to stop paying. Said out loud instead, and left standing —
        # paying too early is the survivable mistake of the two.
        warnings.append(
            f"De åpne leverandørfakturaene summerer til {_kr(ap_total)} kr, "
            f"men konto 2400 viser bare {_kr(gl_ap)} kr i leverandørgjeld. "
            f"Prognosen betaler ut hele {_kr(ap_total)} kr, altså "
            f"{_kr(ap_total - gl_ap)} kr mer enn bøkene sier dere skylder. "
            f"Som regel er det fakturaer som er betalt uten at restbeløpet ble "
            f"nullet i reskontroen. Verdt å rydde i.")

    for item in com["items"]:
        if item["id"] not in STATUTORY_FROM_COMMITMENTS:
            continue
        try:
            due = date.fromisoformat(item["due"])
        except (ValueError, TypeError):
            continue
        committed.append({"date": max(due, today), "amount": -item["amount"],
                          "kind": "statutory", "label": item["label"]})

    committed += _payroll_runs(today, horizon, rates["wages_cash"])

    # Trading that has not happened yet: invoicing goes out at month end and is
    # collected on the terms this company's customers actually take. Running
    # costs are charged from next month, since this month's bills are already
    # in the payables above.
    terms = [(date.fromisoformat(i["due"]) - date.fromisoformat(i["invoiced"])).days
             for i in ar_open if i.get("invoiced") and i.get("due")]
    credit_days = int(statistics.median(terms)) if terms else 30
    month = date(today.year, today.month, 1)
    for _ in range(6):
        month_end = date(month.year, month.month, monthrange(month.year, month.month)[1])
        landing = month_end + timedelta(days=credit_days + PAY_LAG_DAYS)
        if today <= landing < horizon:
            expected.append({"date": landing, "amount": rates["revenue"] * 1.25,
                             "kind": "new_sales",
                             "label": f"Fakturering {MONTH_NAMES[month.month - 1]}"
                                      f", betalt"})
        cost_day = month_end
        if month > date(today.year, today.month, 1) and today <= cost_day < horizon:
            expected.append({"date": cost_day, "amount": -rates["opex"],
                             "kind": "opex",
                             "label": f"Driftskostnader "
                                      f"{MONTH_NAMES[month.month - 1]}"})
        month = (date(month.year + 1, 1, 1) if month.month == 12
                 else date(month.year, month.month + 1, 1))

    data = _assemble(today, week0, opening, committed, expected,
                     rates, credit_days, warnings, ar_open, ap_open)
    data["ar_open"] = ar_open
    return data


def _assemble(today, week0, opening, committed, expected, rates, credit_days,
              warnings, ar_open, ap_open) -> dict:
    """Bucket the flows into weeks and walk the balance down both lines."""
    ferie_withheld, ferie_weeks, ferie_weeks_stated = _ferie_withheld()

    def bucket(flow) -> int | None:
        idx = (flow["date"] - week0).days // 7
        if idx < 0:
            idx = 0          # anything already past lands in the current week
        return idx if idx < WEEKS else None

    weeks = []
    for i in range(WEEKS):
        start = week0 + timedelta(weeks=i)
        weeks.append({"index": i, "start": start.isoformat(),
                      "end": (start + timedelta(days=6)).isoformat(),
                      "label": f"Uke {start.isocalendar().week}",
                      "in": 0.0, "out": 0.0, "expected_in": 0.0,
                      "expected_out": 0.0, "items": []})

    for flow in committed:
        i = bucket(flow)
        if i is None:
            continue
        key = "in" if flow["amount"] >= 0 else "out"
        weeks[i][key] += abs(flow["amount"])
        weeks[i]["items"].append({"label": flow["label"], "kind": flow["kind"],
                                  "amount": round(flow["amount"], 2),
                                  "scenario": "committed"})
    for flow in expected:
        i = bucket(flow)
        if i is None:
            continue
        key = "expected_in" if flow["amount"] >= 0 else "expected_out"
        weeks[i][key] += abs(flow["amount"])
        weeks[i]["items"].append({"label": flow["label"], "kind": flow["kind"],
                                  "amount": round(flow["amount"], 2),
                                  "scenario": "expected"})

    c_balance = e_balance = opening
    for w in weeks:
        w["committed_open"] = round(c_balance, 2)
        w["expected_open"] = round(e_balance, 2)
        c_balance += w["in"] - w["out"]
        e_balance += w["in"] - w["out"] + w["expected_in"] - w["expected_out"]
        w["committed_close"] = round(c_balance, 2)
        w["expected_close"] = round(e_balance, 2)
        for k in ("in", "out", "expected_in", "expected_out"):
            w[k] = round(w[k], 2)

    low_c = min(weeks, key=lambda w: w["committed_close"])
    low_e = min(weeks, key=lambda w: w["expected_close"])
    first_negative = next((w for w in weeks if w["expected_close"] < 0), None)

    return {
        "as_of": today.isoformat(),
        "opening": round(opening, 2),
        "weeks": weeks,
        "low_committed": {"label": low_c["label"], "start": low_c["start"],
                          "amount": low_c["committed_close"]},
        "low_expected": {"label": low_e["label"], "start": low_e["start"],
                         "amount": low_e["expected_close"]},
        "goes_negative": ({"label": first_negative["label"],
                           "start": first_negative["start"]}
                          if first_negative else None),
        "open_invoices": {"receivable": len(ar_open), "payable": len(ap_open),
                          "receivable_total": round(sum(i["amount"] for i in ar_open), 2),
                          "payable_total": round(sum(i["amount"] for i in ap_open), 2)},
        "assumptions": {
            "credit_days": credit_days,
            "pay_lag_days": PAY_LAG_DAYS,
            "late_spread_weeks": LATE_SPREAD_WEEKS,
            "skattetrekk": ("betales til Skatteetaten samme dag som lønnen, "
                            "så hele bruttolønnen går ut på lønningsdagen"),
            "feriepenger_i_lonnsraten": False,
            # The two months that are not like the other ten.
            "halv_skatt_i_desember": ("nettolønnen i desember er høyere, men "
                                      "trekket går ut samme dag, så beløpet "
                                      "ut av kontoen er det samme bruttoet "
                                      "som en vanlig måned"),
            # Values, not sentences: the briefing builds the prose. A month
            # name with "antatt" glued onto it reads fine in a key-value list
            # and wrecks any sentence it is dropped into.
            "feriepenger_maned": MONTH_NAMES[commitments.ferie_month() - 1],
            "feriepenger_maned_oppgitt": commitments.ferie_month_is_stated(),
            "ferie_uker": ferie_weeks,
            "ferie_uker_oppgitt": ferie_weeks_stated,
            "ferie_lonn_holdt_igjen": round(ferie_withheld, 3),
            # Carried rather than recomputed from the rounded share above —
            # 2/26 of a month's wages is not 7.7 % of them, and a figure in
            # the prose that disagrees with the table costs more trust than
            # both are worth.
            "ferie_lonn_utbetalt": round(
                rates["wages_cash"] * (1 - ferie_withheld), 2),
            # Said out loud because it moves which week is the tight one.
            "working_day_shift": ("statutory dues roll forward to the next "
                                  "working day, wages back to the last"),
            # Which it is matters: month end is our guess, the 20th is theirs.
            "pay_day": ("fra company.md" if commitments.payday_is_stated()
                        else "månedsslutt, antatt — ikke oppgitt i company.md"),
            "monthly_revenue": round(rates["revenue"], 2),
            "monthly_wages": round(rates["wages"], 2),
            "monthly_wages_cash": round(rates["wages_cash"], 2),
            "monthly_opex": round(rates["opex"], 2),
        },
        "warnings": warnings,
    }


_flight = freshness.Cached(build, CACHE_SECONDS)


async def cached() -> dict:
    return await _flight.get()


def briefing(data: dict | None) -> str:
    """The forecast block injected into the system prompt."""
    if not data or not data.get("weeks"):
        return ""
    low_c, low_e = data["low_committed"], data["low_expected"]
    a = data["assumptions"]

    out = ["## De neste 13 ukene\n",
           f"Built {data.get('as_of')} from open invoices, the tax calendar and "
           f"this company's own run-rates. No model was involved in the "
           f"arithmetic, but the second line is a forecast and must always be "
           f"presented as one.\n",
           f"- Starter på **{_kr(data['opening'])} kr**",
           f"- **Bundet linje** — bare det som allerede er fakturert inn og ut, "
           f"lønn og skattedatoer: lavest **{_kr(low_c['amount'])} kr** i "
           f"{low_c['label']} ({low_c['start']}).",
           f"- **Forventet linje** — med vanlig drift og fakturering: lavest "
           f"**{_kr(low_e['amount'])} kr** i {low_e['label']} "
           f"({low_e['start']}).\n"]

    if data.get("goes_negative"):
        g = data["goes_negative"]
        out.append(f"**Kontoen går i minus i {g['label']} ({g['start']}).** That "
                   f"is the finding. Lead with it, say what it would take to "
                   f"avoid it, and do not bury it in the table.\n")
    else:
        out.append("Kontoen går ikke i minus i perioden. Say that plainly when "
                   "asked; do not manufacture alarm from a low point that is "
                   "still comfortably positive.\n")

    out.append("| Uke | Fra | Inn | Ut | Bundet saldo | Forventet saldo |")
    out.append("|---|---|---:|---:|---:|---:|")
    for w in data["weeks"]:
        out.append(f"| {w['label']} | {w['start']} | {_kr(w['in'] + w['expected_in'])} | "
                   f"{_kr(-(w['out'] + w['expected_out']))} | "
                   f"{_kr(w['committed_close'])} | {_kr(w['expected_close'])} |")
    out.append("")
    out.append(f"**Forutsetningene** — these are his to change, and saying them "
               f"out loud is what separates a forecast from a guess: fakturering "
               f"{_kr(a['monthly_revenue'])} kr i måneden, lønn "
               f"{_kr(a['monthly_wages'])} kr, driftskostnader "
               f"{_kr(a['monthly_opex'])} kr, kredittid {a['credit_days']} dager "
               f"pluss {a['pay_lag_days']} dagers forsinkelse, forfalte fakturaer "
               f"fordelt over {a['late_spread_weeks']} uker.\n")

    # The two months that do not behave like the other ten. Only said when one
    # of them is actually inside the window: a note about December in February
    # is noise, and noise is what gets the real notes skimmed past.
    months = {int(w["start"][5:7]) for w in data["weeks"]}
    months |= {int(w["end"][5:7]) for w in data["weeks"]}
    ferie = a.get("feriepenger_maned", "")
    ferie_month = next((i + 1 for i, n in enumerate(MONTH_NAMES) if n == ferie),
                       None)
    if ferie_month in months and a.get("ferie_lonn_holdt_igjen"):
        held = a["ferie_lonn_holdt_igjen"]
        run = (f"holdt helt tilbake — feriepengene er hele utbetalingen"
               if held >= 1 else
               f"satt ned til {_kr(a['ferie_lonn_utbetalt'])} kr fra "
               f"{_kr(a['monthly_wages_cash'])} kr")
        # Whether this rests on their word or on ours decides how hard he is
        # allowed to lean on it, so it is said either way, not only when weak.
        source = ("Både måneden og de "
                  f"{a['ferie_uker']} ukene ferie står i company.md."
                  if a.get("feriepenger_maned_oppgitt")
                  and a.get("ferie_uker_oppgitt") else
                  f"Måneden er antatt til {ferie} og ferien til "
                  f"{a['ferie_uker']} uker — det står ikke i company.md, og "
                  f"det flytter en hel månedslønn mellom to uker, så det er "
                  f"verdt å få bekreftet.")
        out.append(
            f"**Feriemåneden ligger i perioden.** I {ferie} tar de ansatte ut "
            f"feriepenger i stedet for vanlig lønn, og lønnskjøringen den "
            f"måneden er derfor {run}. Feriepengene selv ligger i den bundne "
            f"linjen, med beløpet fra konto 2940. {source}\n")
    if HALF_TAX_MONTH in months:
        out.append(
            f"**Halv skatt i desember.** De ansatte får mer netto i desember, "
            f"men trekket betales til Skatteetaten samme dag som lønnen, så "
            f"beløpet ut av bedriftens konto er den samme bruttolønnen som i "
            f"en vanlig måned. Si det hvis han venter en tyngre desember av "
            f"den grunn — desember er tung av andre grunner, ikke denne.\n")

    if data.get("warnings"):
        out.append("**Det som svekker prognosen** — say these in the owner's "
                   "words whenever you quote a figure that rests on them:\n")
        out += [f"- {w}" for w in data["warnings"]]
        out.append("")

    out.append("How to use it. The low point and its week are the answer to "
               "\"will I make it\" — give the week by name and date, not a "
               "reassurance. Any question about spending, hiring or buying is "
               "answered against the low point, not against today's balance. "
               "Always say which of the two lines you are quoting.")
    return "\n".join(out)
