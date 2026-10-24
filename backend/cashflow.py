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

import bankgap
import brreg
import commitments
import company
import forecasts
import scoring
import freshness
import payment_habits
import workdays
from mcp_client import mcp
import saldobalanse
# Shared with the pre-flight rather than copied: two readings of the monthly
# balance report that drift apart are worse than one import.
from preflight import _account, _monthly, _rows

log = logging.getLogger("cfo.cashflow")

CACHE_SECONDS = 600

WEEKS = 13
AR_MONTHS_BACK = 12          # how far back to look for still-open invoices
LATE_SPREAD_WEEKS = 3        # already-overdue invoices land across this many
# How late an overdue invoice is decides how far it is counted on. Up to
# LATE_DAYS is ordinary lateness: in both lines, over the next three weeks.
# Up to DOUBTFUL_DAYS it usually pays, but not reliably and not soon: in the
# expected line only, over SLOW_WEEKS. Beyond that it is not counted on at all
# — money that in practice comes back through debt collection or not at all —
# and is named instead, so it is chased rather than forecast.
LATE_DAYS = 30
DOUBTFUL_DAYS = 90
SLOW_WEEKS = (3, 8)
PAY_LAG_DAYS = 7             # customers pay this late even when not "late"
# No WITHHOLDING_SHARE any more. Until 2026 the tax withheld from wages was held
# back and settled on a bimonthly term, so only the net left on pay day. From
# 2026 there is no skattetrekkskonto and the trekk goes to Skatteetaten the same
# day as the salary — so what leaves the account on pay day is the gross.
# No TRAILING_MONTHS either: it said the run-rates used a trailing window, and
# they never did — `_run_rates` takes a median over every closed month. A
# constant that documents behaviour the code does not have is worse than none.
# The fewest closed months a run-rate is allowed to rest on. Before April this
# year has fewer, and the gap is made up from the end of last year.
MIN_CLOSED_MONTHS = 3

# What makes a supplier's bill a fixed one, for the committed line: billed in
# FIXED_MIN of the last FIXED_LOOKBACK closed months (or FIXED_MIN quarters in
# a row), every amount within FIXED_TOLERANCE of the median. See _fixed_bills.
FIXED_LOOKBACK = 4
FIXED_MIN = 3
FIXED_TOLERANCE = 0.15

# The months are not alike. Sales and running costs get a seasonal pattern
# from last year — each month against last year's average, held within
# SEASON_LIMITS and taken at SEASON_WEIGHT, since one year is a thin basis —
# and a level from the last LEVEL_MONTHS closed months with the season taken
# out, which carries the trend without drawing a line into the future.
LEVEL_MONTHS = 6
SEASON_LIMITS = (0.5, 1.5)
SEASON_WEIGHT = 0.5

# The running costs that are not fixed bills are spread over the month by
# when this company's variable bills are dated and paid. See _cost_profile.
COST_PERIODS = ((1, 7), (8, 14), (15, 21), (22, 31))
PROFILE_MIN_BILLS = 10
PROFILE_WEIGHT_CAP = 3
PROFILE_MIN_PERIOD_BILLS = 3

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

# Invoicing that has not happened yet brings in gross cash and creates a
# liability on the same krone. The forecast used to take the first and not the
# second: 1 950 013 kr landing in the window with 390 003 kr of VAT inside it
# that never left again, and the inflow landed in the tightest week. Money
# leaves before it arrives — October's VAT falls due 10 December while October's
# invoicing is collected around 22 December — so having neither side overstated
# comfort in exactly the weeks that were already the problem.
MVA_RATE = 0.25
# Below this the output-VAT balance is too small to read a ratio off, which
# happens for a few days after every settlement clears both accounts.
VAT_RATIO_MIN = 50_000

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
    "feriepenger", "betalbar_skatt", "arets_skatt",
    "annen_gjeld",
}
# `forskuddstrekk` is deliberately NOT here, and that is a change of mind.
# Until 2026 the trekk sat on a restricted account and was settled on its own
# term, so scheduling the 2600-2619 balance was right. From 2026 it leaves
# with the salary, and `_payroll_runs` pays the gross — so taking the balance
# as well paid the same krone twice, once on pay day and once at the term.
# Latent rather than live: 2600 has stood at 0 every month of 2026 and 1950
# was closed, which is the regime change showing up in the ledger. Left out so
# it cannot come back the day someone posts to 2600 again.


# Every krone that leaves the account has to be in exactly one of these.
# 4000-4999 and 5100-5999 were in none of them: varekjøp, underentreprise,
# pensjon and yrkesskade simply did not exist in the forecast, about
# 116 000 kr a month against a modelled opex of 156 000.
#
# And no krone that never leaves it. A cost booked against a balance sheet
# account rather than the bank is a P&L figure, not a payment: counting it
# took the depreciation on three cars — about 19 000 kr a month in Q1 —
# out of the account every month as if it were a bill.
OPEX_RANGES = [(4000, 4999),      # varekjøp og underentreprise
               (5100, 5199),
               (5300, 5399),      # annen opplysningspliktig godtgjørelse
               (5402, 5999),      # pensjon, yrkesskade, personalkostnad
               (6100, 7799),      # ordinære driftskostnader
               (7900, 7999)]
# The gaps in that list, each on purpose:
# - 5200-5299 fordel i arbeidsforhold: a benefit in kind, taxed through
#   payroll and booked against its own contra account. No money moves.
# - 5400/5401 arbeidsgiveravgift: dated by commitments from its own
#   balance; taking it here as well would pay it twice.
# - 6000-6099 avskrivning og nedskrivning: the cost of an asset already
#   paid for, spread over its life.
# - 7800-7899 tap på fordringer og ved avgang: money that did not come in,
#   or an asset written off. Neither is a payment.


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
                         outstanding_key: str, name_key: str,
                         issued: dict | None = None,
                         in_kroner: bool = False,
                         history: list | None = None) -> tuple[list, list, bool]:
    """Open invoices with their due dates, the warnings, and whether every
    window answered — an empty list from failed calls is not an empty book.

    The search caps at 100 rows per call, so the range is walked a month at a
    time. A month that comes back exactly full may have been truncated, and
    that is reported rather than quietly under-counting. It does take a `from`
    offset — so the truncation could be paged through instead of warned about,
    which is a card of its own and not done here.

    Both registers answer under `rows`. They did not always appear to: the
    supplier call read `invoices`, a key the response has never carried, so
    `r.get(...) or []` was empty every time and every supplier bill was dropped
    before it reached the forecast — silently, because the call itself
    succeeded. `what` names the register in the warnings, since two sources
    sharing one sentence left nobody able to tell which one was short.

    `issued`, when given, gets `this_month`: everything invoiced this month,
    paid or not, from the same rows. The open list leaves out what is paid,
    and what was invoiced and paid this month is invoicing all the same. It
    also gets `truncated` when a month came back full, which is the one known
    reason the ledger can hold more receivables than the list shows.

    `in_kroner` says the outstanding amount is already in kroner whatever
    the invoice's currency, as the customer register's `amountOutstanding`
    is. The supplier register's `outstandingAmount` is in the invoice's own.

    `history`, when given, gets every row, paid ones too: the fixed bills are
    read off how a supplier has billed, and most of those bills are paid.
    """
    calls = []
    for back in range(AR_MONTHS_BACK):
        start, end = _month_bounds(today, back)
        calls.append(mcp.call(tool, {"invoiceDateFrom": start.isoformat(),
                                     "invoiceDateTo": end.isoformat(),
                                     "count": 100}))
    results = await asyncio.gather(*calls, return_exceptions=True)

    seen, out, warnings = set(), [], []
    complete = not any(isinstance(r, Exception) for r in results)
    for back, r in enumerate(results):
        start, _ = _month_bounds(today, back)
        when = f"{MONTH_NAMES[start.month - 1]} {start.year}"
        if isinstance(r, Exception):
            warnings.append(f"{what} for {when} kunne ikke hentes ({r}). "
                            f"Tallene under er ufullstendige.")
            continue
        # The search answers partially rather than failing when one of the two
        # registers is unreadable, and says so in `complete` with a note about
        # what is missing. Only an exception was being counted as incomplete,
        # so a half-read register passed for a whole one — and an empty half
        # reads exactly like a company that owes nobody.
        if r.get("complete") is False:
            complete = False
            note = r.get("degradedNote") or "en av registrene svarte ikke"
            warnings.append(f"{what} for {when} ble bare delvis lest "
                            f"({note}). Tallene under er ufullstendige.")
        rows = r.get("rows") or []
        if back == 0 and issued is not None:
            # In kroner: `amount` is the base currency, 0 for an invoice in
            # another currency not yet converted, which then counts at face.
            # A cancelled invoice and its credit note are both rows, and net
            # to nothing together.
            issued["this_month"] = sum(
                float(row.get("amount") or row.get("amountCurrency") or 0)
                for row in rows)
        if len(rows) >= 100:
            warnings.append(f"Det er minst 100 {what.lower()} i {when}; lista "
                            f"kan være avkortet.")
            if issued is not None:
                issued["truncated"] = True
        for row in rows:
            # A row with no id is not a duplicate of the last row with no id.
            # Putting None in `seen` made the first one swallow every one after.
            key = row.get(id_key)
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            if history is not None:
                history.append(row)
            amount = row.get(outstanding_key) or 0
            if not amount or not row.get("dueDate"):
                continue
            # outstandingAmount is in the *invoice's* currency, not NOK. There
            # is no rate here and inventing one is not this module's job, so
            # the money stays in the forecast at face value — dropping it
            # would understate what leaves — and the shortfall is declared
            # instead of quietly standing in for kroner.
            currency = (row.get("currency") or "NOK").upper()
            if currency != "NOK" and not in_kroner:
                warnings.append(
                    f"{row.get(name_key) or 'En faktura'} står i {currency}, "
                    f"ikke kroner ({_kr(float(amount))} {currency}). Beløpet "
                    f"er lagt inn som om det var kroner, så prognosen er feil "
                    f"på denne posten med hele valutakursen.")
            out.append({"id": key, "name": row.get(name_key) or "",
                        "due": row["dueDate"], "invoiced": row.get("invoiceDate"),
                        "amount": float(amount),
                        # Carried for the reminder drafts in cards.py: a chase
                        # letter without invoice numbers is not a chase letter.
                        "number": row.get("invoiceNumber"),
                        "email": row.get("customerEmail") or "",
                        "url": row.get("url") or ""})
    return out, warnings, complete


def _receipt_parts(inv: dict, today: date,
                   habits: dict | None = None) -> list[tuple[date, float]] | None:
    """When one customer invoice's money is expected to land: (date, amount).

    An invoice that is already overdue will not arrive the day you notice it,
    and one that is not yet due will not arrive on the dot either. Overdue
    invoices are spread over the next few weeks; the rest are dated from their
    due date plus the lag customers take anyway. None for an invoice with no
    usable due date. The schedule below and the invoice list kept with each
    forecast both come from here, so a miss is measured against what the
    forecast actually said.
    """
    late = _days_overdue(inv, today)
    if late is None:
        return None
    due = date.fromisoformat(inv["due"])
    if late > DOUBTFUL_DAYS:
        return []
    if late > LATE_DAYS:
        first, last = SLOW_WEEKS
        per = inv["amount"] / (last - first + 1)
        return [(today + timedelta(days=7 * w), per) for w in range(first, last + 1)]
    if late > 0:
        # A customer who always pays three weeks late and is one week late now
        # is not late by his own lights: his money comes when it usually does.
        usual = payment_habits.own(habits, inv.get("name") or "")
        if usual is not None and late < usual:
            return [(due + timedelta(days=usual), inv["amount"])]
        per = inv["amount"] / LATE_SPREAD_WEEKS
        return [(today + timedelta(days=7 * (w + 1)), per)
                for w in range(LATE_SPREAD_WEEKS)]
    # Not yet due: the customer's own lateness, the company's where he has too
    # little history, and the old seven days where there is none at all.
    lag = payment_habits.lag(habits, inv.get("name") or "", PAY_LAG_DAYS)
    return [(due + timedelta(days=lag), inv["amount"])]


def _days_overdue(inv: dict, today: date) -> int | None:
    """Days past due, 0 for one not yet due, None without a due date."""
    try:
        due = date.fromisoformat(inv["due"])
    except (ValueError, TypeError, KeyError):
        return None
    return max(0, (today - due).days)


def _payment_parts(bill: dict, today: date) -> list[tuple[date, float]] | None:
    """When one of our own bills leaves: on its due date, or this week if it
    is already overdue. As `_receipt_parts`, but without the lag or the spread
    — both would understate what leaves the account soon."""
    try:
        due = date.fromisoformat(bill["due"])
    except (ValueError, TypeError, KeyError):
        return None
    return [(max(due, today), bill["amount"])]


def _schedule_receipts(invoices: list, today: date,
                       habits: dict | None = None) -> list:
    """Customer invoices as flows. Not-yet-due ones keep their own line;
    overdue ones are pooled into one line a week, since the spread is ours and
    a line per invoice per week would bury the table.

    Those 31-90 days late come back as `ar_slow`, which belongs in the
    expected line only; the caller splits them off. Those later still have no
    flow at all."""
    flows, overdue, slow = [], [], []
    for inv in invoices:
        parts = _receipt_parts(inv, today, habits)
        if not parts:
            continue
        if (_days_overdue(inv, today) or 0) > LATE_DAYS:
            slow.append(parts)
            continue
        if len(parts) > 1:
            overdue.append((inv, parts))
            continue
        for when, amount in parts:
            flows.append({"date": when, "amount": amount, "kind": "ar",
                          "label": f"Faktura til {inv['name']}"})
    if overdue:
        for w in range(LATE_SPREAD_WEEKS):
            flows.append({"date": today + timedelta(days=7 * (w + 1)),
                          "amount": sum(p[w][1] for _, p in overdue),
                          "kind": "ar_late",
                          "label": f"Forfalte fakturaer ({len(overdue)} stk), "
                                   f"fordelt over {LATE_SPREAD_WEEKS} uker"})
    if slow:
        first, last = SLOW_WEEKS
        for n, w in enumerate(range(first, last + 1)):
            flows.append({"date": today + timedelta(days=7 * w),
                          "amount": sum(p[n][1] for p in slow),
                          "kind": "ar_slow",
                          "label": f"Fakturaer {LATE_DAYS + 1}–{DOUBTFUL_DAYS} "
                                   f"dager på overtid ({len(slow)} stk), "
                                   f"fordelt over uke {first}–{last}"})
    return flows


def _schedule_payments(bills: list, today: date) -> list:
    """Our own bills as flows. The customer scheduler above must not be reused
    here — it adds the lag customers take, and spreads the overdue book over
    weeks, both of which understate what leaves the account soon."""
    flows = []
    for bill in bills:
        for when, amount in _payment_parts(bill, today) or []:
            flows.append({"date": when, "amount": -amount,
                          "kind": "ap", "label": f"Regning fra {bill['name']}"})
    return flows


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    i = year * 12 + (month - 1) + n
    return i // 12, i % 12 + 1


def _fixed_bills(history: list, today: date,
                 horizon: date) -> tuple[list, list, dict]:
    """The bills that come whether anyone sells anything: rent, leasing,
    insurance, software. Returns the flows, what was found, and the fixed
    amount of each month still to be billed — paid inside the window or not,
    since it is that month's cost all the same and the expected line nets it.

    The committed line is the floor, and it had payroll and the tax dates but
    none of these — they lived only inside the expected line's running costs,
    so the floor the brief's colour rests on stood higher than it is.

    Found by how the bills arrive, not by which account they are booked on:
    6400, 6700 and 7700 hold fixed and variable alike, while a supplier who
    bills the same amount every month is plain to see. Monthly: a bill in at
    least FIXED_MIN of the last FIXED_LOOKBACK closed months. Quarterly: at
    least FIXED_MIN bills three months apart. Every amount within
    FIXED_TOLERANCE of the supplier's median, so materials that follow sales
    stay out — they are not certain, which is what this line is for. Credit
    notes and foreign currency stay out of the reading.

    A month whose bill has arrived is skipped: it is in the payables or paid
    out of the opening balance. One whose usual day has passed without a bill
    is placed anyway, on its usual due date or today, since a bill that is
    late or in the inbox is still owed.
    """
    by_supplier: dict = {}
    for row in history:
        if row.get("isCreditNote") or (row.get("currency") or "NOK").upper() != "NOK":
            continue
        try:
            issued = date.fromisoformat(row["invoiceDate"])
            due = date.fromisoformat(row["dueDate"])
        except (ValueError, TypeError, KeyError):
            continue
        amount = float(row.get("amountCurrency") or row.get("amount") or 0)
        name = row.get("supplierName") or ""
        if amount <= 0 or not name:
            continue
        s = by_supplier.setdefault(row.get("supplierId") or name,
                                   {"name": name, "months": {}})
        m = s["months"].setdefault((issued.year, issued.month),
                                   {"amount": 0.0, "days": [], "terms": [], "last": issued})
        m["amount"] += amount
        m["days"].append(issued.day)
        m["terms"].append((due - issued).days)
        m["last"] = max(m["last"], issued)

    this = (today.year, today.month)
    closed = [_add_months(*this, -n) for n in range(1, FIXED_LOOKBACK + 1)]
    flows, found, by_month = [], [], {}
    for s in by_supplier.values():
        months = s["months"]
        past = sorted(k for k in months if k < this)
        if not past:
            continue

        def stable(keys) -> bool:
            values = [months[k]["amount"] for k in keys]
            mid = statistics.median(values)
            return mid > 0 and all(abs(v - mid) <= FIXED_TOLERANCE * mid for v in values)

        recent = [k for k in closed if k in months]
        gaps = [(b[0] * 12 + b[1]) - (a[0] * 12 + a[1]) for a, b in zip(past, past[1:])]
        if len(recent) >= FIXED_MIN and stable(recent):
            step, cadence, basis = 1, "månedlig", recent
        elif len(past) >= FIXED_MIN and gaps and all(g == 3 for g in gaps) \
                and stable(past) and _add_months(*past[-1], 3) >= this:
            step, cadence, basis = 3, "kvartalsvis", past
        else:
            continue

        latest = max(months, key=lambda k: months[k]["last"])
        amount = months[latest]["amount"]
        day = int(statistics.median([d for k in basis for d in months[k]["days"]]))
        terms = int(statistics.median([t for k in basis for t in months[k]["terms"]]))
        upcoming = []
        y, mo = _add_months(*past[-1], step)
        while True:
            issued = date(y, mo, min(day, monthrange(y, mo)[1]))
            if issued >= horizon:
                break
            pay = max(issued + timedelta(days=terms), today)
            due_now = (y, mo) >= this and (y, mo) not in months
            if due_now:
                by_month[(y, mo)] = by_month.get((y, mo), 0.0) + amount
            if due_now and pay < horizon:
                flows.append({"date": pay, "amount": -amount, "kind": "fixed",
                              "month": (y, mo),
                              "label": f"Fast regning fra {s['name']}"})
                upcoming.append(pay)
            y, mo = _add_months(y, mo, step)
        found.append({"name": s["name"], "amount": round(amount, 2),
                      "cadence": cadence, "day": day, "terms": terms,
                      "next": min(upcoming).isoformat() if upcoming else None})
    found.sort(key=lambda f: -f["amount"])
    return flows, found, by_month


def _bill_rows(history: list):
    """(issued, due, gross, supplier) for every readable NOK bill in the
    supplier history. Credit notes and foreign currency are left out."""
    for row in history:
        if row.get("isCreditNote") or (row.get("currency") or "NOK").upper() != "NOK":
            continue
        try:
            issued = date.fromisoformat(row["invoiceDate"])
            due = date.fromisoformat(row["dueDate"])
        except (ValueError, TypeError, KeyError):
            continue
        amount = float(row.get("amountCurrency") or row.get("amount") or 0)
        if amount > 0:
            yield issued, due, amount, row.get("supplierName") or ""


def _weighted_median(pairs: list[tuple[float, float]]) -> float:
    """The value at which half the weight is reached. (value, weight) pairs."""
    pairs = sorted(pairs)
    half, running = sum(w for _, w in pairs) / 2, 0.0
    for value, weight in pairs:
        running += weight
        if running >= half:
            return value
    return pairs[-1][0]


def _cost_profile(history: list, fixed_names: set[str]) -> dict:
    """When in the month the variable bills are dated, and how long after they
    are paid — measured on this company's own supplier history.

    The running costs used to leave in one lump on the last day of the month.
    Materials dated the 6th on fourteen days' terms are paid on the 20th, and
    a bill dated the 25th on thirty days is paid next month; the lump was
    wrong both ways, and the week it put the low point in is the week the
    brief names. Split into COST_PERIODS: each period's share of the amount,
    and the amount-weighted median of its terms. The fixed suppliers are
    left out: their bills are placed on their own dates already.

    Each bill weighs by its amount, but no more than PROFILE_WEIGHT_CAP times
    the median bill: one machine bought on 65 days' terms otherwise set the
    pattern for every month's cleaning supplies.

    Too few bills to read a pattern off, and the month-end lump is kept and
    said to be kept.
    """
    return _profile([(i, d, a) for i, d, a, who in _bill_rows(history)
                     if who not in fixed_names])


def _sales_rows(history: list):
    """(issued, due, amount) for every customer invoice in the history that
    stands: a credited invoice and its credit note are left out together."""
    for row in history:
        if row.get("isCredited"):
            continue
        try:
            issued = date.fromisoformat(row["invoiceDate"])
            due = date.fromisoformat(row["dueDate"])
        except (ValueError, TypeError, KeyError):
            continue
        amount = float(row.get("amount") or row.get("amountCurrency") or 0)
        if amount > 0:
            yield issued, due, amount


def _sales_profile(history: list) -> dict:
    """When in the month this company's invoices are dated, and on what
    terms — the same reading `_cost_profile` makes of the supplier bills.

    New sales were assumed invoiced on the last day of every month, on the
    median terms of the open invoices: a company invoicing on the 10th had
    its money placed three weeks late, and October's invoicing paid in
    January fell outside the window altogether.
    """
    return _profile(list(_sales_rows(history)))


def _profile(bills: list[tuple[date, date, float]]) -> dict:
    """Shares and terms by COST_PERIODS from (issued, due, amount) rows."""
    sums = [0.0] * len(COST_PERIODS)
    terms: list[list] = [[] for _ in COST_PERIODS]
    # The day within the period the money is usually dated, not its middle:
    # a company invoicing on the last workday was placed on the 26th, five
    # days early, and five days decide which week the money lands in.
    days: list[list] = [[] for _ in COST_PERIODS]
    cap = (PROFILE_WEIGHT_CAP * statistics.median([b[2] for b in bills])
           if bills else 0.0)
    count = 0
    for issued, due, gross in bills:
        amount = min(gross, cap)
        i = next(n for n, (_, last) in enumerate(COST_PERIODS) if issued.day <= last)
        sums[i] += amount
        terms[i].append((max(0, (due - issued).days), amount))
        days[i].append((issued.day, amount))
        count += 1
    total = sum(sums)
    if count < PROFILE_MIN_BILLS or total <= 0:
        return {"measured": False, "bills": count, "periods": []}
    # A period with a bill or two says little about its terms, and a lone
    # one-off set them on its own: it takes the terms of all the bills.
    overall = int(_weighted_median([t for ts in terms for t in ts]))
    return {"measured": True, "bills": count, "periods": [
        {"from": first, "to": last, "share": round(sums[i] / total, 4),
         "day": int(_weighted_median(days[i])),
         "terms": (int(_weighted_median(terms[i]))
                   if len(terms[i]) >= PROFILE_MIN_PERIOD_BILLS else overall)}
        for i, (first, last) in enumerate(COST_PERIODS) if sums[i] > 0]}


def _cost_parts(profile: dict, month: date, today: date,
                current: bool) -> list[tuple[date, float, str]]:
    """(pay day, share, which days) for one month's variable costs.

    The current month's remainder is what has not been booked yet, so it is
    spread over the periods not yet over, and nothing is paid before today.
    """
    last_day = monthrange(month.year, month.month)[1]
    month_end = date(month.year, month.month, last_day)
    if not profile.get("measured"):
        return [(max(month_end, today), 1.0, "")]
    periods = [p for p in profile["periods"]
               if not current or min(p["to"], last_day) >= today.day]
    if not periods:
        return [(max(month_end, today), 1.0, "")]
    total = sum(p["share"] for p in periods)
    out = []
    for p in periods:
        to = min(p["to"], last_day)
        # The usual day where measured; an older profile without one, the middle.
        mid = date(month.year, month.month,
                   min(max(p.get("day") or (p["from"] + to) // 2, p["from"]), to))
        pay = max(mid + timedelta(days=p["terms"]), today)
        out.append((pay, p["share"] / total, f"fakturert {p['from']}.–{to}."))
    return out


def _expected_items(invoices: list, bills: list, today: date,
                    habits: dict | None = None) -> dict:
    """Every open invoice and bill, with when this forecast expects it.

    Kept with the saved forecast, so that when it is scored a miss can be put
    down to who paid later than expected — the pooled overdue line cannot say.
    """
    def items(rows, parts_of):
        out = []
        for r in rows:
            parts = parts_of(r, today)
            if parts:
                out.append({"number": r.get("number"), "name": r.get("name") or "",
                            "amount": round(r["amount"], 2),
                            "parts": [[d.isoformat(), round(a, 2)] for d, a in parts]})
        return out
    return {"ar": items(invoices, lambda r, t: _receipt_parts(r, t, habits)),
            "ap": items(bills, _payment_parts)}


def _merged(rows: list, columns: list, ranges) -> list:
    """One monthly series across several account ranges.

    Summed before the outlier filter runs, never after. Filtering each
    range on its own and adding the results lets a quiet month in one range
    be judged against that range's own median, which is not the question —
    the question is what the whole cost base does in a month.
    """
    total: dict = {}
    order: list = []
    for low, high in ranges:
        for m, v in _monthly(rows, columns, low, high):
            if m not in total:
                total[m] = 0.0
                order.append(m)
            total[m] += v
    return [(m, total[m]) for m in order]


def _month_no(label: str) -> int | None:
    """1-12 for a column label, "Okt" or last year's "Okt 2025"."""
    name = label.split(" ")[0]
    return saldobalanse.MONTHS.index(name) + 1 if name in saldobalanse.MONTHS else None


def _seasons(history: tuple | None) -> dict:
    """Each month's season for sales and for running costs, from last year.

    `history` is last year's (rows, columns). A season is that month against
    last year's average, held within SEASON_LIMITS and pulled half way to 1:
    December at 0.82 last year becomes 0.91. None for a series without twelve
    months of something in them — a new company, or a month never posted —
    and the forecast then stays flat, and says so.
    """
    out: dict = {}
    for key, (ranges, flip) in (("revenue", ([(3000, 3999)], -1)),
                                ("opex", (OPEX_RANGES, 1))):
        by = {}
        if history:
            for m, v in _merged(history[0], history[1], ranges):
                if (n := _month_no(m)):
                    by[n] = v * flip
        if len(by) < 12 or any(v <= 0 for v in by.values()):
            out[key] = None
            continue
        mean = sum(by.values()) / 12
        lo, hi = SEASON_LIMITS
        out[key] = {m: round(1 + SEASON_WEIGHT * (min(max(v / mean, lo), hi) - 1), 4)
                    for m, v in by.items()}
    return out


def _run_rates(rows: list, columns: list,
               prior: tuple | None = None, season: dict | None = None,
               history: tuple | None = None) -> tuple[dict, list[str]]:
    """Monthly run-rates that a posting backlog cannot poison.

    Costs in this ledger read 122k, 223k, 114k, then 48k, 14k, 13k. Nothing got
    cheaper — supplier invoices stopped being booked. A trailing average takes
    those months at face value and forecasts a third of the real cost, which is
    the most dangerous direction to be wrong in.

    So: median of the closed months, keep those within half to double of it,
    average those. A month that is a fraction of every other month is not a
    cheap month, it is an unposted one — and it is named, not silently dropped.
    The current month is excluded outright, being part-posted by definition.

    `prior` is `(rows, columns, year, keep)`: last year's monthly report, of
    which the final `keep` months are put in front of this year's. Early in the
    year this year alone has too few closed months — none at all in January,
    where every rate came out 0 and the forecast had no payroll, costs or
    revenue in it.

    `season`, from `_seasons`, and `history`, last year's `(rows, columns,
    year)`: for sales and running costs with a measured season, the rate is
    the level instead — the last LEVEL_MONTHS closed months, last year's
    included where this year has too few, each divided by its own season. A
    year of growth then shows in the level, and the forecast multiplies each
    month's season back on. Without a season, the median of the closed months
    as before.
    """
    notes: list[str] = []
    merged = _merged

    def series_for(ranges) -> list:
        """Last year's tail, if asked for, then this year's months."""
        head = []
        if prior:
            p_rows, p_columns, year, keep = prior
            # Named with the year: "Des" alone would read as this December.
            head = [(f"{m} {year}", v)
                    for m, v in merged(p_rows, p_columns, ranges)][-keep:]
        return head + merged(rows, columns, ranges)

    def rate(ranges, flip, name, key=None):
        idx = (season or {}).get(key) if key else None
        full = series_for(ranges)
        series = [(m, v * flip) for m, v in full][:-1]
        if idx and series:
            past = []
            if history:
                h_rows, h_cols, year = history
                past = [(f"{m} {year}", v * flip)
                        for m, v in merged(h_rows, h_cols, ranges)]
            this = [(m, v * flip) for m, v in merged(rows, columns, ranges)][:-1]
            series = [(m, v / idx.get(_month_no(m) or 0, 1.0))
                      for m, v in (past + this)[-LEVEL_MONTHS:]]
        values = [v for _, v in series]
        if not values:
            # No account in the range at all is a real zero: a company without
            # staff has no payroll. Accounts with only the open month behind
            # them is not, and a zero rate that drops payroll out of the
            # forecast must not pass for a quiet month — so that one is said.
            if not full:
                return 0.0
            notes.append(f"{name} kunne ikke beregnes — det finnes ingen "
                         f"avsluttede måneder å regne snittet på, så den er "
                         f"satt til 0 i prognosen.")
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
        said = (f"{name} er lagt inn med {_kr(average)} kr i måneden"
                f"{' før sesong' if idx else ''}.")
        # One note per rate, not one per direction. A range with both a quiet
        # month and a loud one used to produce two notes opening on the same
        # sentence, which reads like the figure was stated twice.
        why = []
        if low_months:
            why.append(
                f"{', '.join(low_months)} er holdt utenfor — de ligger langt "
                f"under de andre månedene, og det betyr nesten alltid at bilag "
                f"ikke er bokført, ikke at kostnaden forsvant.")
        if high_months:
            # Said for the same reason the low ones are. A month at several
            # times the median pulls the rate down when it is dropped, and a
            # rate quietly lowered is the dangerous direction to be wrong in.
            why.append(
                f"{', '.join(high_months)} er holdt utenfor — de ligger langt "
                f"over de andre månedene. Det er som regel etterslep som ble "
                f"bokført på én gang, eller noe som bare skjedde denne ene "
                f"gangen, men sjekk det før du stoler på snittet.")
        if why:
            notes.append(" ".join([said] + why))
        return average

    rates = {"revenue": rate([(3000, 3999)], -1, "Omsetning", "revenue"),
             # The full wage cost, accrual and all — what the P&L carries.
             "wages": rate([(5000, 5099)], 1, "Lønn"),
             # What actually leaves on pay day. Feriepenger (5020) is excluded:
             # it accrues monthly but is paid next summer, and commitments
             # already dates it there, so counting it here pays it twice.
             "wages_cash": rate([(5000, 5019), (5030, 5099)], 1,
                                "Lønn som går ut på lønningsdagen"),
             # Not part of opex, and not double counted: commitments dates the
             # 2770 balance for payrolls already reported, this rates the ones
             # still to come. 5401 stays out, being the feriepenger's own.
             "aga": rate([(5400, 5400)], 1, "Arbeidsgiveravgift"),
             "opex": rate(OPEX_RANGES, 1, "Driftskostnader", "opex")}
    return rates, notes


def _closing_range(rows: list, low: int, high: int) -> float:
    """Closing balance across an account range, from the last numeric cell."""
    total = 0.0
    for r in rows:
        n = _account(r)
        if n is None or not (low <= n <= high):
            continue
        cells = [c for c in (r.get("cells") or []) if isinstance(c, (int, float))]
        if cells:
            total += float(cells[-1])
    return total


def _closing_or_none(rows: list, low: int, high: int) -> float | None:
    """`_closing_range`, but None when the range is not in the ledger at all.

    The distinction decides whether a reconciliation runs. A company that
    keeps no 2400 is not a company that owes nothing, and a warning built on
    an invented zero sends someone looking for a gap that is not there.
    """
    if not any((n := _account(r)) is not None and low <= n <= high for r in rows):
        return None
    return _closing_range(rows, low, high)


def _vat_input_share(rows: list) -> tuple[float, bool]:
    """How much of the output VAT the input VAT cancels, per this company.

    Not every krone collected is paid over: VAT on what the company buys is
    deducted first. The share is read from 2700 against 2710 rather than
    assumed, and those two are the one pair in the ledger that needs no
    differencing — a settlement clears both on the same day, so their ratio
    inside a term is the live ratio with no drift across the boundary.

    Returns the share and whether it could be measured. Unmeasured means the
    whole output VAT is scheduled out, which is the safe direction to be wrong.
    """
    out = abs(_closing_range(rows, 2700, 2709))
    inn = abs(_closing_range(rows, 2710, 2719))
    if out < VAT_RATIO_MIN:
        return 0.0, False
    # Capped: a deduction above half would mean the company buys nearly as much
    # as it sells, which for a cleaning company means a posting error, not a
    # bargain, and a too-large deduction understates the payment.
    return min(inn / out, 0.5), True


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


def _pay_days(today: date, horizon: date) -> list[tuple[int, int, date]]:
    """Every pay day in the window, with the month it pays for.

    Public to the module rather than inlined in `_payroll_runs`, because the
    briefing needs the same answer: its notes about December and the holiday
    month describe what the payroll run does, so they have to be gated on the
    run being in the window — not on the month merely being touched by it,
    which is a different question at both edges of thirteen weeks.
    """
    out, month = [], today
    while True:
        # The same pay day commitments uses — imported, not reimplemented. Two
        # implementations disagreed and the forecast lost a December payroll.
        pay_day = workdays.backward(commitments.payday(month.year, month.month))
        if pay_day >= horizon:
            break
        if pay_day >= today:
            out.append((month.year, month.month, pay_day))
        month = (date(month.year + 1, 1, 1) if month.month == 12
                 else date(month.year, month.month + 1, 1))
    return out


def _payroll_runs(today: date, horizon: date, payroll_cash: float,
                  aga_monthly: float = 0.0, aga_booked: float = 0.0) -> list[dict]:
    """Every pay day between now and the horizon, and what leaves on it.

    Gross, not net: from 2026 the trekk goes to Skatteetaten the same day as
    the salary, so the whole of it leaves the account on pay day. December is
    no exception — see HALF_TAX_MONTH above. The feriepenger month is, and it
    is the one month that can produce no flow at all.
    """
    ferie_month = commitments.ferie_month()
    withheld, _, _ = _ferie_withheld()
    flows = []
    for year, month_no, pay_day in _pay_days(today, horizon):
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
                          "kind": "wages", "label": label})

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
                    "date": due, "amount": -aga, "kind": "aga_future",
                    "label": f"Arbeidsgiveravgift på lønn "
                             f"{MONTH_NAMES[month.month - 1]}"})
    return flows


async def build(today: date | None = None) -> dict:
    today = today or date.today()
    week0 = _monday(today)
    horizon = week0 + timedelta(weeks=WEEKS)
    start_year = f"{today.year}-01-01"

    # The current month is not closed, so January has none of this year's.
    keep = max(0, MIN_CLOSED_MONTHS - (today.month - 1))
    last_year = today.year - 1

    # Last year always: early in the year for the months this year lacks,
    # and every month for the seasonal pattern.
    async def _prior():
        return await saldobalanse.monthly(mcp, f"{last_year}-01-01", f"{last_year}-12-31")

    issued: dict = {}
    supplier_history: list = []
    customer_history: list = []
    balance, com, ar, ap, prior, paid = await asyncio.gather(
        saldobalanse.monthly(mcp, start_year, today.isoformat()),
        commitments.cached(),
        _open_invoices(today, "search_invoices", "Kundefakturaer", "id",
                       "amountOutstanding", "customerName", issued,
                       # Kroner already, for a foreign-currency invoice too.
                       in_kroner=True, history=customer_history),
        # Supplier rows are keyed by voucherId, not id.
        _open_invoices(today, "search_supplier_invoices", "Leverandørfakturaer",
                       "voucherId", "outstandingAmount", "supplierName",
                       history=supplier_history),
        _prior(),
        payment_habits.payments(mcp, today),
        return_exceptions=True,
    )
    if isinstance(balance, Exception):
        raise RuntimeError(f"Kunne ikke lese saldobalansen: {balance}")
    warnings: list[str] = []
    if isinstance(com, Exception):
        raise RuntimeError(f"Kunne ikke lese forpliktelsene: {com}")
    ar_open, ar_warn, ar_complete = ([], ["Kundefakturaer kunne ikke hentes."], False) \
        if isinstance(ar, Exception) else ar
    ap_open, ap_warn, ap_complete = ([], ["Leverandørfakturaer kunne ikke hentes."], False) \
        if isinstance(ap, Exception) else ap
    warnings += ar_warn + ap_warn

    rows = _rows(balance)
    columns = [c.get("name") for c in balance.get("table", {}).get("columns", [])]
    prior_months = None
    if keep:
        if isinstance(prior, dict) and "table" in prior:
            prior_months = (_rows(prior),
                            [c.get("name") for c in prior["table"].get("columns", [])],
                            last_year, keep)
            warnings.append(
                f"Det er for tidlig på året til å regne løpende tall på "
                f"{today.year} alene, så de siste {keep} månedene av "
                f"{last_year} er tatt med i snittet.")
        else:
            log.warning("Cashflow: fjorårets saldobalanse feilet: %s", prior)
            warnings.append(
                f"Saldobalansen for {last_year} kunne ikke hentes, så de "
                f"løpende tallene hviler på færre enn {MIN_CLOSED_MONTHS} "
                f"måneder.")
    history = None
    if isinstance(prior, dict) and "table" in prior:
        history = (_rows(prior),
                   [c.get("name") for c in prior["table"].get("columns", [])])
    season = _seasons(history)
    # How late each customer pays, from a year of payments on 1500. Without
    # it every customer is the old seven days late, and that is said.
    if isinstance(paid, Exception):
        log.warning("Cashflow: innbetalingene kunne ikke leses: %s", paid)
        paid = None
    habits = payment_habits.habits(customer_history, paid)
    if paid is None or not habits["complete"]:
        warnings.append(
            "Innbetalingene på konto 1500 kunne ikke leses helt, så "
            "betalingsvanene er ufullstendige; kunder uten nok historikk er "
            f"regnet med {PAY_LAG_DAYS} dager etter forfall.")
    rates, rate_notes = _run_rates(rows, columns, prior_months, season,
                                   (*history, last_year) if history else None)
    warnings += rate_notes

    def revenue_in(month_no: int) -> float:
        return rates["revenue"] * ((season.get("revenue") or {}).get(month_no, 1.0))

    def opex_in(month_no: int) -> float:
        return rates["opex"] * ((season.get("opex") or {}).get(month_no, 1.0))

    # Open on the money in the bank, not on the booked balance. The bank feed
    # runs days ahead of the bookkeeping, and every week of the forecast, the
    # low point with it, was shifted down by whatever had landed unposted.
    # Measured in commitments, so the forecast and "how much of this is mine"
    # open on the same figure.
    gap = com.get("bank_gap")
    booked = com.get("bank_booked", com["bank"])
    opening = com["bank"]
    if gap is None:
        warnings.append(
            "Bankavstemmingen i Tripletex kunne ikke leses, så prognosen "
            "starter på den bokførte banksaldoen. Har det kommet inn eller gått "
            "ut penger som ikke er bokført ennå, er startpunktet feil med så "
            "mye — og det er ukjent hvor mye.")
    else:
        warnings += gap["unknown"]
        # The figure is right as of the last imported line, so that date is
        # said whenever the feed is behind the last working day.
        if gap.get("stale"):
            warnings.append(
                f"Bankfeeden i Tripletex har ingenting etter {gap['latest']}, "
                f"så startsaldoen er pengene i banken per den dagen. Det som "
                f"har kommet inn eller gått ut siden, er ikke med.")
        if gap["approximate"]:
            warnings.append(
                "For noen måneder i bankavstemmingen fantes ingen bokført "
                "månedsbevegelse å måle mot, så forskjellen mellom bank og bøker "
                "der er regnet ut fra de umatchede listene alene. De utelater "
                "lønnsposteringer brukeren ikke har innsyn i.")

    # A payment the bank has and the ledger has not is still an open invoice
    # in the register. With the opening lifted by that payment, scheduling the
    # invoice as well collects the same krone twice — so what the unbooked
    # lines have paid comes off the lists the schedules are built from. The
    # full lists stay for the reconciliations against 1500 and 2400 below,
    # which compare the register with the ledger and must see what the
    # ledger sees, and for this month's invoicing, which is invoicing whether
    # or not it has been paid.
    unbooked = gap["unbooked"] if gap else []
    ar_due, ar_paid = bankgap.settle(ar_open, unbooked, +1)
    ap_due, ap_paid = bankgap.settle(ap_open, unbooked, -1)

    # Customers Enhetsregisteret has in trouble, as of the last morning check.
    # A bankrupt customer's invoices are not money coming in: they leave the
    # schedule and are carried beside it, for the card that says so. One under
    # voluntary liquidation usually pays, and stays.
    risky = brreg.at_risk()
    # Said on the customer's card, not among the warnings: those are what the
    # regnskapsfører has to fix, and this is nothing in the books.
    ar_at_risk = [{**i, "register": risky[i["name"]]} for i in ar_due if i["name"] in risky]
    ar_due = [i for i in ar_due if not risky.get(i["name"], {}).get("excluded")]

    # The open ledger should agree with the invoice list. Where it does not,
    # the forecast is built on the invoices and the gap is declared.
    # Read with the same carry-forward the rest of the module uses. Requiring
    # the *last* cell to be numeric switched this whole reconciliation off in
    # any month where the account had not moved — a blank cell means unchanged,
    # not zero, as `_monthly` says in as many words — and a silent skip here
    # drops the residual from the forecast and the warning from the answer.
    # The range, not 1500 alone: receivables posted to 1501 and up belong to
    # the same reconciliation, and `commitments` already treats them as one.
    gl_ar = _closing_or_none(rows, 1500, 1509)
    ar_total = sum(i["amount"] for i in ar_open)
    ar_residual = 0.0
    residual_counted = False
    if gl_ar is not None and gl_ar - ar_total > 1000:
        # The invoice list is short of the ledger. It used to be counted as
        # money in, in the committed line, over the next three weeks — money
        # nobody could explain, propping up the floor the colour rests on,
        # while the supplier side pays its unexplained difference this week.
        # What it usually is: invoices older than the lookback (past ninety
        # days by then), postings made straight to 1500, payments not matched
        # to their invoices. Only a list cut off at a hundred rows gives a
        # reason to think it is ordinary invoicing on its way in — that, or a
        # register that could not be read whole; then it is
        # expected, slowly, like the invoices a month or two late. Otherwise it
        # is in neither line, and named, as the oldest invoices are.
        ar_residual = gl_ar - ar_total
        list_short = bool(issued.get("truncated")) or not ar_complete
        residual_counted = list_short
        head = (f"Konto 1500 viser {_kr(gl_ar)} kr i kundefordringer, men de "
                f"åpne fakturaene summerer bare til {_kr(ar_total)} kr. ")
        warnings.append(
            head + (f"Fakturalista er ikke lest helt, så de resterende "
                    f"{_kr(ar_residual)} kr er trolig vanlige fakturaer som ikke "
                    f"ble lest. De ligger bare i den forventede linjen, fordelt "
                    f"over uke {SLOW_WEEKS[0]}–{SLOW_WEEKS[1]}."
                    if residual_counted else
                    f"De resterende {_kr(ar_residual)} kr er ikke regnet med i "
                    f"prognosen før noen har funnet ut hva de består av — "
                    f"gamle fakturaer, posteringer rett på kontoen eller "
                    f"innbetalinger som ikke er koblet til fakturaen."))

    committed: list[dict] = []
    expected: list[dict] = []

    receipts = _schedule_receipts(ar_due, today, habits)
    committed += [f for f in receipts if f["kind"] != "ar_slow"]
    expected += [f for f in receipts if f["kind"] == "ar_slow"]
    # The ones not counted on at all, named so they are chased.
    ar_doubtful = [{**i, "days_overdue": _days_overdue(i, today)} for i in ar_due
                   if (_days_overdue(i, today) or 0) > DOUBTFUL_DAYS]
    ar_doubtful.sort(key=lambda i: -i["amount"])
    ages = {"i_rute": 0.0, "inntil_30": 0.0, "31_90": 0.0, "over_90": 0.0}
    for i in ar_due:
        late = _days_overdue(i, today)
        if late is None:
            continue
        key = ("i_rute" if late == 0 else "inntil_30" if late <= LATE_DAYS
               else "31_90" if late <= DOUBTFUL_DAYS else "over_90")
        ages[key] += i["amount"]
    if ar_residual and residual_counted:
        first, last = SLOW_WEEKS
        per = ar_residual / (last - first + 1)
        for w in range(first, last + 1):
            expected.append({"date": today + timedelta(days=7 * w),
                             "amount": per, "kind": "ar_unmatched",
                             "label": "Kundefordringer uten kjent faktura, "
                                      "trolig fra en avkortet fakturaliste"})
    committed += _schedule_payments(ap_due, today)
    # Rent, leasing, insurance: certain whether anyone sells anything, so the
    # floor carries them. The expected line's running costs already contain
    # them, and are netted below month by month.
    fixed_flows, fixed_found, fixed_by_month = _fixed_bills(
        supplier_history, today, horizon)
    committed += fixed_flows
    profile = _cost_profile(supplier_history, {f["name"] for f in fixed_found})
    # And the sales not yet invoiced: when in the month this company invoices,
    # on what terms, paid as late as its customers usually pay.
    sales_profile = _sales_profile(customer_history)
    sales_lag = (habits["company"] if habits.get("company") is not None
                 else PAY_LAG_DAYS)

    # The same check as on 1500 above, which 2400 never had — and the asymmetry
    # was backwards. Being short on receivables flatters the forecast; being
    # short on payables hides money going out, and that is the side nobody
    # noticed was empty for as long as the supplier search read the wrong key.
    # A liability is a credit balance, so what is owed is the balance negated.
    gl_ap_raw = _closing_or_none(rows, 2400, 2409)
    gl_ap = None if gl_ap_raw is None else -gl_ap_raw
    ap_total = sum(b["amount"] for b in ap_open)
    if gl_ap is not None and gl_ap - ap_total > 1000:
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

    # What this month's payroll has already put on 2770, if it has been run
    # and posted. A liability is a credit balance, so an accrual is negative.
    aga_series = _monthly(rows, columns, 2770, 2779)
    aga_booked = max(0.0, -aga_series[-1][1]) if aga_series else 0.0
    committed += _payroll_runs(today, horizon, rates["wages_cash"],
                               rates["aga"], aga_booked)
    payroll_months = [m for _, m, _ in _pay_days(today, horizon)]

    # Trading that has not happened yet: invoicing goes out at month end and is
    # collected on the terms this company's customers actually take. Running
    # costs are charged from next month, since this month's bills are already
    # in the payables above.
    terms = [(date.fromisoformat(i["due"]) - date.fromisoformat(i["invoiced"])).days
             for i in ar_open if i.get("invoiced") and i.get("due")]
    # What the customers' own invoices say first; the company's stated terms
    # where there are none to measure; 30 days only where neither exists.
    stated_terms = company.setting("kredittid_dager")
    if terms:
        credit_days, credit_source = int(statistics.median(terms)), "målt på fakturaene"
    elif stated_terms and 0 < int(stated_terms) <= 365:
        credit_days, credit_source = int(stated_terms), "fra company.md"
    else:
        credit_days, credit_source = 30, "antatt"
    vat_share, vat_measured = _vat_input_share(rows)
    # What this month has already accrued. commitments dates the whole
    # 2700-2739 balance to the running term's deadline, and the loop below
    # adds a full month's VAT for the current month on that very same date —
    # so everything already booked was being paid twice, by a margin that
    # grows through the month to nearly a full month's VAT by the end of it.
    # Only the part still to be invoiced belongs here. A liability is a credit
    # balance, so an accrual shows up as a negative movement; `commitments`
    # negates the same way when it turns a balance into an amount owed.
    booked_vat = 0.0
    vat_series = _monthly(rows, columns, 2700, 2739)
    if vat_series:
        booked_vat = max(0.0, -vat_series[-1][1])
    # The same overlap on the way in. Invoicing already issued this month sits
    # in ar_open with a real due date of its own; forecasting a full month on
    # top of it collects the same krone twice. The opex leg three lines down
    # has always guarded this ("this month's bills are already in the payables
    # above") — the revenue leg never did. Gross against gross: amounts here
    # are what the customer owes, and so is revenue × (1 + MVA_RATE).
    invoiced_this_month = 0.0
    for i in ar_open:
        try:
            issued_on = date.fromisoformat(i["invoiced"])
        except (ValueError, TypeError, KeyError):
            continue
        if (issued_on.year, issued_on.month) == (today.year, today.month):
            invoiced_this_month += i["amount"]
    # Everything invoiced this month, paid ones included. The open list above
    # has only what is still owed, so an invoice sent on the 2nd and paid on
    # the 9th was not netted off: its money was in the opening balance and
    # collected again at month end. The open list stays the floor, for a
    # month whose invoices could not be read.
    invoiced_this_month = max(invoiced_this_month, issued.get("this_month", 0.0))
    # Running costs leave the account with their VAT on, and the run-rate is
    # the P&L figure, which has none. The VAT forecast above takes the input
    # VAT off what is paid over, so leaving it off the bills as well took the
    # deduction without ever paying the VAT it deducts. Added back as exactly
    # that deduction rather than 25 % on every cost account: pension,
    # insurance and bank fees carry none, and the deduction is already the
    # measured share. Unmeasured, it is zero on both sides.
    opex_vat = rates["revenue"] * MVA_RATE * vat_share
    opex_cash = rates["opex"] + opex_vat
    # Per month from here, each on its own season: the VAT on the bills
    # follows the deduction, which follows the month's sales.
    # What this month has already booked against the same cost accounts. The
    # opex leg used to start next month on the strength of "this month's bills
    # are already in the payables" — true on the last day of the month only.
    # On the 5th most of the month's bills have not arrived, and they were in
    # no line at all. Netted the way the revenue leg nets what is invoiced: a
    # bill booked this month is in the payables or already paid out of the
    # opening balance, and one still in the inbox is in neither, so it belongs
    # to the remainder. Net against net; the VAT goes on after.
    booked_opex = 0.0
    for low, high in OPEX_RANGES:
        series = _monthly(rows, columns, low, high)
        if series:
            booked_opex += series[-1][1]
    booked_opex = max(0.0, booked_opex)
    opex_left = max(0.0, opex_in(today.month) - booked_opex)
    sales_by_month, costs_by_month = [], []
    month = date(today.year, today.month, 1)
    for _ in range(6):
        month_end = date(month.year, month.month, monthrange(month.year, month.month)[1])
        revenue = revenue_in(month.month)
        opex = opex_in(month.month)
        sales_by_month.append({"month": MONTH_NAMES[month.month - 1],
                               "amount": round(revenue, 2)})
        costs_by_month.append({"month": MONTH_NAMES[month.month - 1],
                               "amount": round(opex, 2)})
        month_vat = revenue * MVA_RATE * vat_share
        gross = revenue * (1 + MVA_RATE)
        if (month.year, month.month) == (today.year, today.month):
            gross = max(0.0, gross - invoiced_this_month)
        current = (month.year, month.month) == (today.year, today.month)
        if sales_profile.get("measured"):
            # Each period's share, paid its own terms plus the lateness after.
            # This month's remainder only in the days still to come.
            parts = [(pay + timedelta(days=sales_lag), share, days)
                     for pay, share, days in _cost_parts(sales_profile, month,
                                                         today, current)]
        else:
            parts = [(month_end + timedelta(days=credit_days + sales_lag), 1.0, "")]
        for landing, share, days in parts:
            amount = gross * share
            if today <= landing < horizon and round(amount) > 0:
                expected.append({"date": landing, "amount": amount,
                                 "kind": "new_sales",
                                 "label": f"Fakturering {MONTH_NAMES[month.month - 1]}"
                                          f"{', ' + days.replace('fakturert ', '') if days else ''}"
                                          f", betalt"})
        # The VAT on that invoicing, whether or not the customer has paid by
        # then — the deadline does not wait for the money. Scheduled even when
        # the receipt itself falls outside the window, because that is the case
        # that hurts: the liability inside, the cash outside.
        net_vat = revenue * MVA_RATE * (1 - vat_share)
        if (month.year, month.month) == (today.year, today.month):
            net_vat = max(0.0, net_vat - booked_vat)
        vat_due = workdays.forward(
            commitments.term_due(month.year, month.month, commitments.MVA_TERMS))
        if today <= vat_due < horizon and round(net_vat) > 0:
            expected.append({"date": vat_due, "amount": -net_vat,
                             "kind": "vat_future",
                             "label": f"Merverdiavgift på fakturering "
                                      f"{MONTH_NAMES[month.month - 1]}"})
        cost = (opex_left * ((opex + month_vat) / opex) if opex else 0.0) \
            if current else opex + month_vat
        # The fixed bills of this month are its cost too, placed in the
        # committed line on their own dates when they fall inside the window.
        # Both gross. Never below zero: fixed bills above the run-rate mean
        # the rate is low, not that money comes back.
        fixed = fixed_by_month.get((month.year, month.month), 0.0)
        cost = max(0.0, cost - fixed)
        # Spread by when the bills are paid. A part paid after the window
        # leaves it, as sales collected after it do.
        for pay, share, days in _cost_parts(profile, month, today, current):
            part = cost * share
            if pay < horizon and round(part) > 0:
                expected.append({"date": pay, "amount": -part,
                                 "kind": "opex",
                                 "label": f"Driftskostnader "
                                          f"{MONTH_NAMES[month.month - 1]}"
                                          f"{', resten' if current else ''}"
                                          f"{', ' + days if days else ''}"
                                          f"{' utenom faste regninger' if fixed >= 0.5 else ''}"
                                          f"{' (inkl. moms)' if month_vat >= 0.5 else ''}"})
        month = (date(month.year + 1, 1, 1) if month.month == 12
                 else date(month.year, month.month + 1, 1))

    if not vat_measured:
        warnings.append(
            "Forholdet mellom utgående og inngående merverdiavgift lot seg "
            "ikke måle — konto 2700 er tom eller nettopp gjort opp. Prognosen "
            "legger derfor ut hele den utgående momsen på ny fakturering, uten "
            "fradrag for moms på det dere selv kjøper. Det er for strengt, ikke "
            "for snilt, men det er verdt å vite.")

    data = _assemble(today, week0, opening, committed, expected,
                     rates, credit_days, warnings, ar_due, ap_due,
                     vat_share, vat_measured, booked_vat,
                     invoiced_this_month, payroll_months)
    data["assumptions"]["credit_days_source"] = credit_source
    # What the bills cost in cash, against the P&L figure beside it, and what
    # this month has already booked — netted off, as `fakturert_denne_maneden`.
    data["assumptions"]["mva_paa_kostnader"] = round(opex_vat, 2)
    data["assumptions"]["monthly_opex_cash"] = round(opex_cash, 2)
    data["assumptions"]["kostnader_bokfort_denne_maneden"] = round(booked_opex, 2)
    # The recurring bills the committed line now carries, for the owner to
    # check against what he knows he pays.
    data["fixed_costs"] = fixed_found
    data["assumptions"]["kostnadsprofil"] = profile
    data["assumptions"]["fakturaprofil"] = {**sales_profile, "forsinkelse_dager": sales_lag}
    data["assumptions"]["sesong"] = {
        k: ({MONTH_NAMES[m - 1]: v for m, v in sorted(idx.items())} if idx else None)
        for k, idx in season.items()}
    data["assumptions"]["sesong_vekt"] = SEASON_WEIGHT
    data["assumptions"]["omsetning_per_maned"] = sales_by_month
    data["assumptions"]["kostnader_per_maned"] = costs_by_month
    data["assumptions"]["faste_regninger_mnd"] = round(sum(
        f["amount"] / (1 if f["cadence"] == "månedlig" else 3) for f in fixed_found), 2)
    data["bank"] = _bank_payload(booked, gap, ar_paid, ap_paid)
    data["items"] = _expected_items(ar_due, ap_due, today, habits)
    data["betalingsvaner"] = habits
    # What is still owed after the bank's unbooked receipts: a customer who
    # has paid must not be sent a reminder because the books are behind.
    data["ar_open"] = ar_due
    # Invoices to customers in trouble, held out or not, for their cards; and
    # what could not be checked, for the clean-up list.
    data["ar_at_risk"] = ar_at_risk
    data["ar_doubtful"] = ar_doubtful
    data["assumptions"]["ukjente_fordringer"] = {
        "belop": round(ar_residual, 2),
        "behandlet": ("forventet" if residual_counted else "ikke_regnet_med")
                     if ar_residual else None}
    data["assumptions"]["forfalte_grupper"] = {k: round(v, 2) for k, v in ages.items()}
    data["register"] = brreg.loose_ends({i["name"] for i in ar_open})
    # Whether that list is the whole book. An empty list from a failed call
    # reads exactly like a book with nobody late, and cards.py closes every
    # collections card on the strength of it unless told otherwise.
    data["ar_complete"] = ar_complete
    # A forecast missing a register is not a forecast, and holding one for the
    # full ten minutes is how a two-second Tripletex blip becomes ten minutes
    # of a company being told it has no receivables. `Cached` keeps a degraded
    # build only long enough to stop a stampede, then goes and asks again.
    data["partial"] = not (ar_complete and ap_complete)
    # Kept, so it can be scored against what the bank later shows (card 5).
    # Saving is never allowed to cost the forecast itself.
    try:
        forecasts.record(data, bankgap.ledger_balances(rows), today)
    except Exception:  # noqa: BLE001
        log.exception("Kunne ikke lagre prognosen")
    # And the forecasts from 1, 2 and 4 weeks ago held against what the bank
    # showed — scored as soon as the figures for it exist, and only once.
    try:
        scoring.score(today)
    except Exception:  # noqa: BLE001
        log.exception("Kunne ikke score prognosene")
    return data


def _bank_payload(booked: float, gap: dict | None, ar_paid: list,
                  ap_paid: list) -> dict:
    """How the opening balance was arrived at, for the declaration."""
    if not gap:
        return {"booked": round(booked, 2), "adjustment": None, "known": False}
    return {
        "booked": round(booked, 2),
        "adjustment": gap["adjustment"],
        "known": not gap["unknown"],
        "lines": gap["lines"], "in": gap["in"], "out": gap["out"],
        "postings": gap["postings"], "postings_sum": gap["postings_sum"],
        "latest": gap["latest"],
        "stale": gap.get("stale", False),
        "booked_latest": gap.get("booked_latest"),
        "booked_undated": gap.get("booked_undated", 0),
        "accounts": gap["accounts"],
        "unknown": gap["unknown"],
        "approximate": gap["approximate"],
        "settled_ar": round(sum(p["amount"] for p in ar_paid), 2),
        "settled_ar_count": len({(p["name"], p["number"]) for p in ar_paid}),
        "settled_ap": round(sum(p["amount"] for p in ap_paid), 2),
        "settled_ap_count": len({(p["name"], p["number"]) for p in ap_paid}),
    }


def _assemble(today, week0, opening, committed, expected, rates, credit_days,
              warnings, ar_open, ap_open, vat_share=0.0,
              vat_measured=False, booked_vat=0.0, invoiced=0.0,
              payroll_months=()) -> dict:
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
    # Both lines, because they do not fail together and the floor fails first.
    # Reading only the expected line told the owner "kontoen går ikke i minus"
    # with the committed line 800 000 kr under water — the one sentence this
    # module cannot afford to get wrong, since it is the answer to "will I
    # make it". The committed line going dry is a fact about money already
    # agreed; the expected line going dry is that plus a forecast failing too.
    first_negative = next((w for w in weeks if w["expected_close"] < 0), None)
    first_negative_c = next((w for w in weeks if w["committed_close"] < 0), None)

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
        "goes_negative_committed": ({"label": first_negative_c["label"],
                                     "start": first_negative_c["start"]}
                                    if first_negative_c else None),
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
            "monthly_aga": round(rates.get("aga", 0.0), 2),
            # The liability side of trading that has not happened yet.
            "mva_sats": MVA_RATE,
            "mva_fradrag_andel": round(vat_share, 3),
            "mva_fradrag_malt": vat_measured,
            # Netted off this month's figure rather than charged on top of it:
            # commitments already dates this to the same deadline.
            "mva_bokfort_denne_maneden": round(booked_vat, 2),
            # Likewise netted off, not added to: these invoices are already in
            # the committed line with due dates of their own.
            "fakturert_denne_maneden": round(invoiced, 2),
            # Which payroll runs are actually inside the window. The notes
            # about December and the holiday month describe what a *run* does,
            # so they are gated on the run, not on the months the thirteen
            # weeks happen to touch — those differ at both edges, and a note
            # describing a withheld salary the table does not contain is worse
            # than no note.
            "lonnskjoringer": list(payroll_months),
        },
        "warnings": warnings,
    }


_flight = freshness.Cached(build, CACHE_SECONDS,
                           degraded=lambda d: bool(d.get("partial")))


async def cached() -> dict:
    return await _flight.get()


def rules(data: dict | None) -> dict:
    """The company's rules, with the floor resolved against this forecast.

    Resolved on every read and never stored in the forecast: the forecast is
    cached for ten minutes, and a floor changed in Selskapet has to count the
    next time anyone looks, not after the cache happens to expire.
    """
    wages = ((data or {}).get("assumptions") or {}).get("monthly_wages")
    return company.rules(wages)


def below_floor(data: dict, floor: float) -> dict | None:
    """The first week the committed line closes under the floor, if any."""
    return next(({"label": w["label"], "start": w["start"],
                  "amount": w["committed_close"]}
                 for w in data.get("weeks") or []
                 if w["committed_close"] < floor), None)


def _opening_note(bank: dict | None) -> str:
    """Where the opening figure comes from, said every time.

    The adjustment is the point of the opening balance being right, and an
    adjustment nobody is told about is a number that disagrees with the books
    for no stated reason. Said with the count and the date, so the owner can
    find the lines in Bankavstemming himself.
    """
    if not bank:
        return ""
    booked = _kr(bank["booked"])
    if bank.get("adjustment") is None:
        return (f"  — det er den **bokførte** saldoen. Bankavstemmingen kunne "
                f"ikke leses, så om banken står høyere eller lavere er ukjent.")
    adj = bank["adjustment"]
    if abs(adj) < 1:
        note = (f"  — banken og bøkene er like, {booked} kr. Ingen banklinjer "
                f"venter på å bli bokført.")
    else:
        latest = f", siste {bank['latest']}" if bank.get("latest") else ""
        note = (f"  — det er **pengene i banken**, ikke den bokførte saldoen på "
                f"{booked} kr. Banken har {bank['lines']} transaksjoner som "
                f"ikke er bokført ennå ({_kr(bank['in'])} kr inn, "
                f"{_kr(-bank['out'])} kr ut{latest})")
        if bank.get("postings"):
            note += (f", og bøkene har {bank['postings']} posteringer på "
                     f"{_kr(bank['postings_sum'])} kr som ikke finnes i banken")
        note += (f". Til sammen står banken {_kr(abs(adj))} kr "
                 f"{'høyere' if adj > 0 else 'lavere'} enn bøkene.")
        if bank.get("settled_ar_count"):
            note += (f" {bank['settled_ar_count']} kundefakturaer på "
                     f"{_kr(bank['settled_ar'])} kr er betalt i banken og er "
                     f"derfor tatt ut av innbetalingene, så de ikke telles to "
                     f"ganger.")
        if bank.get("settled_ap_count"):
            note += (f" {bank['settled_ap_count']} leverandørfakturaer på "
                     f"{_kr(bank['settled_ap'])} kr er betalt og tatt ut av "
                     f"utbetalingene.")
        if bank.get("stale"):
            note += (f" Bankfeeden stopper {bank['latest']}, så dette er "
                     f"saldoen per den dagen, ikke i dag.")
        note += (" Say this when you quote the opening balance: the books will "
                 "show the lower figure until the bookkeeper catches up.")
    if not bank.get("known"):
        note += (" Deler av bankavstemmingen er ukjent — se det som svekker "
                 "prognosen under.")
    return note


def _floor_line(data: dict) -> str:
    """The low point against the company's floor, and whose floor it is.

    The floor is what "tight" means for this company. Measured against our own
    default, the CEO must be told it is ours — otherwise a guess at his
    comfort level reads as his rule, and he never learns he can set it.
    """
    floor = rules(data)["likviditetsgulv_kr"]
    whose = ("satt av selskapet i Selskapet" if not floor["assumed"] else
             f"{company.said(floor)}. Say it is assumed whenever you measure "
             f"against it, and that he can set his own floor under Selskapet")
    hit = below_floor(data, floor["value"])
    where = (f"Den bundne linjen er under gulvet første gang i {hit['label']} "
             f"({hit['start']}), med {_kr(hit['amount'])} kr."
             if hit else "Den bundne linjen holder seg over gulvet alle 13 "
                         "ukene.")
    return (f"- **Gulvet** er **{_kr(floor['value'])} kr** — {whose}. {where} "
            f"Weigh the low point against this floor, not against zero alone: "
            f"under it is tight even while the balance is still positive.\n")


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
           _opening_note(data.get("bank")),
           f"- **Bundet linje** — det som allerede er fakturert inn og ut, de "
           f"faste regningene, "
           f"lønn og skattedatoer: lavest **{_kr(low_c['amount'])} kr** i "
           f"{low_c['label']} ({low_c['start']}).",
           f"- **Forventet linje** — med vanlig drift og fakturering: lavest "
           f"**{_kr(low_e['amount'])} kr** i {low_e['label']} "
           f"({low_e['start']}).",
           _floor_line(data)]

    # Said per line, never as one verdict. The floor and the forecast go dry
    # in different weeks and for different reasons, and "kontoen går i minus"
    # without saying which line means nothing he can act on.
    neg_e, neg_c = data.get("goes_negative"), data.get("goes_negative_committed")
    if neg_c and neg_e:
        out.append(f"**Kontoen går i minus i begge linjene.** Den bundne i "
                   f"{neg_c['label']} ({neg_c['start']}), den forventede i "
                   f"{neg_e['label']} ({neg_e['start']}). That is the finding. "
                   f"Lead with the bundne week — it is the one that needs no "
                   f"forecast to happen — say what it would take to avoid it, "
                   f"and do not bury either in the table.\n")
    elif neg_c:
        out.append(f"**Den bundne linjen går i minus i {neg_c['label']} "
                   f"({neg_c['start']}).** What is already invoiced in and out, "
                   f"plus wages and the tax dates, does not keep the account "
                   f"above zero. The forventede line stays positive, but only "
                   f"if the invoicing actually goes out and gets paid. That is "
                   f"the finding: lead with the week, name the invoicing the "
                   f"comfort depends on, and never say the account stays "
                   f"positive without that condition attached.\n")
    elif neg_e:
        out.append(f"**Den forventede linjen går i minus i {neg_e['label']} "
                   f"({neg_e['start']}),** selv om den bundne holder seg over "
                   f"null. Ordinary trading is what takes it under — the VAT "
                   f"and the running costs on invoicing not yet sent. Lead "
                   f"with it, and say it is a forecast failing, not a bill "
                   f"already agreed.\n")
    else:
        out.append("Ingen av de to linjene går i minus i perioden. Say that "
                   "plainly when asked; do not manufacture alarm from a low "
                   "point that is still comfortably positive.\n")

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
               f"{_kr(a['monthly_opex'])} kr"
               + (f" ({_kr(a['monthly_opex_cash'])} kr ut av kontoen med "
                  f"{_kr(a['mva_paa_kostnader'])} kr inngående moms)"
                  if a.get("mva_paa_kostnader") else "")
               + (f", hvorav {_kr(a['kostnader_bokfort_denne_maneden'])} kr "
                  f"alt er bokført denne måneden og bare resten lagt inn"
                  if a.get("kostnader_bokfort_denne_maneden") else "")
               + f", kredittid {a['credit_days']} dager "
               f"pluss {a['pay_lag_days']} dagers forsinkelse, forfalte fakturaer "
               f"fordelt over {a['late_spread_weeks']} uker.\n")

    # How far the overdue book is counted on, by age. Said whenever any of it
    # is held back, because the owner will otherwise count it himself.
    ages = a.get("forfalte_grupper") or {}
    if ages.get("31_90") or ages.get("over_90"):
        parts = []
        if ages.get("31_90"):
            parts.append(f"{_kr(ages['31_90'])} kr er {LATE_DAYS + 1}–"
                         f"{DOUBTFUL_DAYS} dager på overtid og ligger bare i den "
                         f"forventede linjen, fordelt over uke {SLOW_WEEKS[0]}–"
                         f"{SLOW_WEEKS[1]}")
        if ages.get("over_90"):
            named = ", ".join(
                f"{i['name']} {_kr(i['amount'])} kr ({i['days_overdue']} dager)"
                for i in (data.get("ar_doubtful") or [])[:5])
            parts.append(f"{_kr(ages['over_90'])} kr er mer enn {DOUBTFUL_DAYS} "
                         f"dager på overtid og er ikke regnet med i noen av "
                         f"linjene: {named}")
        out.append(f"**Forfalte kundefakturaer, etter alder** — det som er "
                   f"inntil {LATE_DAYS} dager på overtid er vanlig forsinkelse "
                   f"og ligger i begge linjene. " + "; ".join(parts) + ". "
                   f"Kommer de gamle pengene inn, er det en gevinst prognosen "
                   f"ikke har lovet. Say this when he asks what is owed to him: "
                   f"the money is still his to chase, it is just not counted "
                   f"on.\n")

    # When the customers' money comes: their own habits, said with the slowest.
    h = data.get("betalingsvaner") or {}
    if h.get("measured"):
        slow = sorted(((n, c["days"]) for n, c in (h.get("customers") or {}).items()
                       if c["days"] > 0), key=lambda x: -x[1])[:3]
        named = (" De tregeste: " + ", ".join(f"{n} {d} dager" for n, d in slow) + "."
                 if slow else "")
        overall = (f"kundene betaler vanligvis {h['company']} dager etter "
                   f"forfall, og " if h.get("company") is not None else "")
        out.append(f"**Når kundene betaler** — målt på et år med innbetalinger: "
                   f"{overall}hver kunde med minst {payment_habits.MIN_CUSTOMER} betalte "
                   f"fakturaer er lagt inn med sin egen vane.{named} Fakturaer "
                   f"som ikke er forfalt, er lagt på forfall pluss kundens vane.\n")
    else:
        out.append(f"**Når kundene betaler** — det er for få innbetalinger å se "
                   f"et mønster i, så alle kunder er lagt inn med "
                   f"{PAY_LAG_DAYS} dager etter forfall.\n")

    # When the sales not yet invoiced come in, and what that rests on.
    sp = a.get("fakturaprofil") or {}
    if sp.get("measured"):
        spread = ", ".join(f"{round(p['share'] * 100)} % fakturert "
                           f"{p['from']}.–{min(p['to'], 31)}. med {p['terms']} "
                           f"dagers frist" for p in sp["periods"])
        out.append(f"**Ny fakturering** — lagt på måneden slik selskapet "
                   f"pleier å fakturere, målt på {sp['bills']} fakturaer: "
                   f"{spread}, betalt {sp['forsinkelse_dager']} dager etter "
                   f"forfall. Det som betales etter de 13 ukene, er ikke med.\n")
    else:
        out.append(f"**Ny fakturering** — for få fakturaer til å se når i "
                   f"måneden selskapet fakturerer, så den er lagt på siste dag "
                   f"i måneden med {a['credit_days']} dagers kredittid og "
                   f"{sp.get('forsinkelse_dager', PAY_LAG_DAYS)} dagers "
                   f"forsinkelse.\n")

    # The months are not alike, and the owner should hear which ones are not.
    seasons = a.get("sesong") or {}
    if seasons.get("revenue"):
        months = [m["month"] for m in a.get("omsetning_per_maned") or []]
        said = ", ".join(
            f"{m} {round((seasons['revenue'][m] - 1) * 100):+d} %" for m in months
            if m in seasons["revenue"])
        sales = ", ".join(f"{m['month']} {_kr(m['amount'])} kr"
                          for m in a.get("omsetning_per_maned") or [])
        out.append(f"**Sesong** — omsetningen følger fjorårets mønster, tatt "
                   f"med halv styrke fordi ett år er et tynt grunnlag: {said} "
                   f"mot en vanlig måned. Nivået er de siste {LEVEL_MONTHS} "
                   f"avsluttede månedene med sesongen trukket ut, så vekst eller "
                   f"nedgang siden i fjor er med. Lagt inn: {sales}. "
                   + ("Driftskostnadene har sitt eget mønster fra fjorårets "
                      "kostnader." if seasons.get("opex") else
                      "Driftskostnadene ligger flatt — fjoråret har ikke tolv "
                      "måneder med kostnader å lese et mønster av.") + "\n")
    else:
        out.append("**Sesong** — fjoråret har ikke tolv måneder med omsetning "
                   "å lese et mønster av, så hver måned er lagt inn likt. Er "
                   "noen måneder normalt stillere, er prognosen for snill i "
                   "dem.\n")

    # The receivables nobody can explain: never in the floor, and only in the
    # forecast when the invoice list is known to be short.
    unknown = a.get("ukjente_fordringer") or {}
    if unknown.get("behandlet") == "ikke_regnet_med":
        out.append(f"**Kundefordringer uten faktura** — konto 1500 har "
                   f"{_kr(unknown['belop'])} kr mer enn de åpne fakturaene. "
                   f"Ingen vet hva det er, så det er ikke regnet med i noen av "
                   f"linjene. Do not promise this money; say the accountant "
                   f"should find out what it is.\n")
    elif unknown.get("behandlet") == "forventet":
        out.append(f"**Kundefordringer uten faktura** — konto 1500 har "
                   f"{_kr(unknown['belop'])} kr mer enn fakturalista som ble "
                   f"lest, og lista er ikke hel. Det er trolig vanlige fakturaer, "
                   f"så det ligger i den forventede linjen, men ikke i den "
                   f"bundne.\n")

    # When the running costs leave, and what that rests on: it moves which week
    # is the tight one, so it is said either way.
    prof = a.get("kostnadsprofil") or {}
    if prof.get("measured"):
        spread = ", ".join(f"{round(p['share'] * 100)} % fakturert "
                           f"{p['from']}.–{min(p['to'], 31)}. og betalt etter "
                           f"{p['terms']} dager" for p in prof["periods"])
        out.append(f"**Når driftskostnadene går ut** — fordelt på måneden etter "
                   f"når selskapets egne leverandørfakturaer pleier å komme og "
                   f"betales, målt på {prof['bills']} fakturaer det siste året: "
                   f"{spread}. Det som betales etter de 13 ukene, er ikke med.\n")
    else:
        out.append("**Når driftskostnadene går ut** — det finnes for få "
                   "leverandørfakturaer til å se et mønster, så de løpende "
                   "kostnadene er lagt på siste dag i hver måned.\n")

    # The floor's newest part, named bill by bill so the owner can check it
    # against what he knows he pays — and what it cannot see, said every time.
    fixed = data.get("fixed_costs") or []
    gap = ("Husleie eller leasing som trekkes direkte fra banken uten "
           "leverandørfaktura, og regninger som kommer én gang i året, er ikke "
           "med — de finnes ikke som gjentatte fakturaer.")
    if fixed:
        named = ", ".join(
            f"{f['name']} {_kr(f['amount'])} kr {f['cadence']}" for f in fixed[:8])
        more = f" og {len(fixed) - 8} til" if len(fixed) > 8 else ""
        out.append(f"**Faste regninger i den bundne linjen** — funnet på at "
                   f"leverandøren fakturerer det samme hver måned eller hvert "
                   f"kvartal, lagt på vanlig forfallsdag: {named}{more}. Til "
                   f"sammen {_kr(a.get('faste_regninger_mnd'))} kr i måneden. "
                   f"De er trukket fra driftskostnadene i den forventede "
                   f"linjen, så de telles ikke to ganger. {gap}\n")
    else:
        out.append(f"**Ingen faste regninger funnet** — ingen leverandør "
                   f"fakturerer det samme beløpet jevnlig, så den bundne linjen "
                   f"har ingen husleie, leasing eller forsikring i seg. {gap} "
                   f"Say so if he asks how safe the bundne line is.\n")

    # The half of the forecast that is easy to leave out, because it is a bill
    # arriving for money that already came in.
    out.append(
        f"**Ny fakturering tar med seg sin egen regning.** Momsen på det som "
        f"faktureres framover er lagt ut på terminforfallet sitt, ikke på den "
        f"dagen kunden betaler — og de to er sjelden samme uke. Satsen er "
        f"{round(a['mva_sats'] * 100)} %, med "
        + (f"{round(a['mva_fradrag_andel'] * 100)} % fradrag for inngående "
           f"moms, målt på konto 2700 mot 2710."
           if a.get("mva_fradrag_malt") else
           "ingen fradrag for inngående moms, fordi forholdet ikke lot seg "
           "måle — det er for strengt, ikke for snilt.")
        + (f" Av denne månedens moms er {_kr(a['mva_bokfort_denne_maneden'])} "
           f"kr alt bokført og ligger i forpliktelsene, så bare resten er lagt "
           f"inn her — ellers ville den samme kronen gått ut to ganger."
           if a.get("mva_bokfort_denne_maneden") else "")
        + f" Arbeidsgiveravgift på lønn som ennå ikke er kjørt ligger på samme "
          f"måte på sitt eget terminforfall, {_kr(a['monthly_aga'])} kr i "
          f"måneden. Begge deler er anslag som følger av omsetnings- og "
          f"lønnsraten over: endrer han den ene, endrer han disse.\n")

    # The two months that do not behave like the other ten. Only said when one
    # of them is actually inside the window: a note about December in February
    # is noise, and noise is what gets the real notes skimmed past.
    months = set(a.get("lonnskjoringer") or ())
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
