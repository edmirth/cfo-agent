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
import time
from calendar import monthrange
from datetime import date, timedelta

import commitments
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
WITHHOLDING_SHARE = 0.30     # of gross wages, held back and paid on term dates
TRAILING_MONTHS = 3          # basis for the recurring run-rates

# Taken from commitments.py, which already dates them. Wages and supplier bills
# are excluded there and modelled here instead — counting both would charge the
# same krone twice.
STATUTORY_FROM_COMMITMENTS = {
    "mva_oppgjor", "mva_lopende", "mva_forrige_termin", "aga", "aga_ferie",
    "feriepenger", "betalbar_skatt", "arets_skatt", "forskuddstrekk",
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


async def _open_invoices(today: date, tool: str, rows_key: str,
                         outstanding_key: str, name_key: str) -> tuple[list, list]:
    """Open invoices with their due dates.

    The search caps at 100 rows per call and offers no paging, so the range is
    walked a month at a time. A month that comes back exactly full may have
    been truncated, and that is reported rather than quietly under-counting.
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
        if isinstance(r, Exception):
            start, _ = _month_bounds(today, back)
            warnings.append(f"Fakturaer for {start:%B %Y} kunne ikke hentes "
                            f"({r}). Tallene under er ufullstendige.")
            continue
        rows = r.get(rows_key) or []
        if len(rows) >= 100:
            start, _ = _month_bounds(today, back)
            warnings.append(f"Det er minst 100 fakturaer i {start:%B %Y}; "
                            f"lista kan være avkortet.")
        for row in rows:
            if row.get("id") in seen:
                continue
            seen.add(row.get("id"))
            amount = row.get(outstanding_key) or 0
            if not amount or not row.get("dueDate"):
                continue
            out.append({"id": row.get("id"), "name": row.get(name_key) or "",
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

    def rate(low, high, flip, name):
        series = [(m, v * flip) for m, v in _monthly(rows, columns, low, high)][:-1]
        values = [v for _, v in series]
        if not values:
            return 0.0
        mid = statistics.median(values)
        if mid <= 0:
            return sum(values) / len(values)
        kept = [(m, v) for m, v in series if 0.5 * mid <= v <= 2 * mid]
        dropped = [m for m, v in series if v < 0.5 * mid]
        if dropped:
            # Format the number on its own: the sentence has commas of its own.
            notes.append(
                f"{name} er lagt inn med {_kr(sum(v for _, v in kept) / len(kept))} "
                f"kr i måneden. {', '.join(dropped)} er holdt utenfor — de ligger "
                f"langt under de andre månedene, og det betyr nesten alltid at "
                f"bilag ikke er bokført, ikke at kostnaden forsvant.")
        return (sum(v for _, v in kept) / len(kept)) if kept else mid

    rates = {"revenue": rate(3000, 3999, -1, "Omsetning"),
             "wages": rate(5000, 5099, 1, "Lønn"),
             "opex": rate(6000, 7999, 1, "Driftskostnader")}
    return rates, notes


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
        _open_invoices(today, "search_invoices", "rows",
                       "amountOutstanding", "customerName"),
        _open_invoices(today, "search_supplier_invoices", "invoices",
                       "outstandingAmount", "supplierName"),
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

    for item in com["items"]:
        if item["id"] not in STATUTORY_FROM_COMMITMENTS:
            continue
        try:
            due = date.fromisoformat(item["due"])
        except (ValueError, TypeError):
            continue
        committed.append({"date": max(due, today), "amount": -item["amount"],
                          "kind": "statutory", "label": item["label"]})

    # Net wages leave on the last working day of each month; what is withheld
    # leaves later, on the term dates already counted above.
    net_wages = rates["wages"] * (1 - WITHHOLDING_SHARE)
    month = today
    while True:
        # The same pay day commitments uses — imported, not reimplemented. Two
        # implementations disagreed and the forecast lost a December payroll.
        pay_day = workdays.backward(commitments.payday(month.year, month.month))
        if pay_day >= horizon:
            break
        if pay_day >= today:
            committed.append({"date": pay_day, "amount": -net_wages,
                              "kind": "wages", "label": "Netto lønn"})
        month = (date(month.year + 1, 1, 1) if month.month == 12
                 else date(month.year, month.month + 1, 1))

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
                             "label": f"Fakturering {month:%B}, betalt"})
        cost_day = month_end
        if month > date(today.year, today.month, 1) and today <= cost_day < horizon:
            expected.append({"date": cost_day, "amount": -rates["opex"],
                             "kind": "opex", "label": f"Driftskostnader {month:%B}"})
        month = (date(month.year + 1, 1, 1) if month.month == 12
                 else date(month.year, month.month + 1, 1))

    data = _assemble(today, week0, opening, committed, expected,
                     rates, credit_days, warnings, ar_open, ap_open)
    data["ar_open"] = ar_open
    return data


def _assemble(today, week0, opening, committed, expected, rates, credit_days,
              warnings, ar_open, ap_open) -> dict:
    """Bucket the flows into weeks and walk the balance down both lines."""
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
            "withholding_share": WITHHOLDING_SHARE,
            # Said out loud because it moves which week is the tight one.
            "working_day_shift": ("statutory dues roll forward to the next "
                                  "working day, wages back to the last"),
            # Which it is matters: month end is our guess, the 20th is theirs.
            "pay_day": ("fra company.md" if commitments.payday_is_stated()
                        else "månedsslutt, antatt — ikke oppgitt i company.md"),
            "monthly_revenue": round(rates["revenue"], 2),
            "monthly_wages": round(rates["wages"], 2),
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
