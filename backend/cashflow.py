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
# The fewest closed months a run-rate is allowed to rest on. Before April this
# year has fewer, and the gap is made up from the end of last year.
MIN_CLOSED_MONTHS = 3

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
                         outstanding_key: str, name_key: str) -> tuple[list, list, bool]:
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
            # outstandingAmount is in the *invoice's* currency, not NOK. There
            # is no rate here and inventing one is not this module's job, so
            # the money stays in the forecast at face value — dropping it
            # would understate what leaves — and the shortfall is declared
            # instead of quietly standing in for kroner.
            currency = (row.get("currency") or "NOK").upper()
            if currency != "NOK":
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


def _run_rates(rows: list, columns: list,
               prior: tuple | None = None) -> tuple[dict, list[str]]:
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
    """
    notes: list[str] = []

    def merged(rows: list, columns: list, ranges) -> list:
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

    def series_for(ranges) -> list:
        """Last year's tail, if asked for, then this year's months."""
        head = []
        if prior:
            p_rows, p_columns, year, keep = prior
            # Named with the year: "Des" alone would read as this December.
            head = [(f"{m} {year}", v)
                    for m, v in merged(p_rows, p_columns, ranges)][-keep:]
        return head + merged(rows, columns, ranges)

    def rate(ranges, flip, name):
        full = series_for(ranges)
        series = [(m, v * flip) for m, v in full][:-1]
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
        said = f"{name} er lagt inn med {_kr(average)} kr i måneden."
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
    rates = {"revenue": rate([(3000, 3999)], -1, "Omsetning"),
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
             "opex": rate(OPEX_RANGES, 1, "Driftskostnader")}
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

    async def _prior():
        if not keep:
            return None
        return await mcp.call("fetch_report", {
            "report_name": "Saldobalanse per måned",
            "period_start": f"{last_year}-01-01",
            "period_end": f"{last_year}-12-31", "limit": 0})

    balance, com, ar, ap, prior = await asyncio.gather(
        mcp.call("fetch_report", {"report_name": "Saldobalanse per måned",
                                  "period_start": start_year,
                                  "period_end": today.isoformat(), "limit": 0}),
        commitments.cached(),
        _open_invoices(today, "search_invoices", "Kundefakturaer", "id",
                       "amountOutstanding", "customerName"),
        # Supplier rows are keyed by voucherId, not id.
        _open_invoices(today, "search_supplier_invoices", "Leverandørfakturaer",
                       "voucherId", "outstandingAmount", "supplierName"),
        _prior(),
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
    rates, rate_notes = _run_rates(rows, columns, prior_months)
    warnings += rate_notes

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
    if gl_ar is not None and gl_ar - ar_total > 1000:
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

    committed += _schedule_receipts(ar_due, today)
    if ar_residual:
        per = ar_residual / LATE_SPREAD_WEEKS
        for w in range(LATE_SPREAD_WEEKS):
            committed.append({"date": today + timedelta(days=7 * (w + 1)),
                              "amount": per, "kind": "ar_unmatched",
                              "label": "Kundefordringer uten kjent faktura"})
    committed += _schedule_payments(ap_due, today)

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
    credit_days = int(statistics.median(terms)) if terms else 30
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
            issued = date.fromisoformat(i["invoiced"])
        except (ValueError, TypeError, KeyError):
            continue
        if (issued.year, issued.month) == (today.year, today.month):
            invoiced_this_month += i["amount"]
    month = date(today.year, today.month, 1)
    for _ in range(6):
        month_end = date(month.year, month.month, monthrange(month.year, month.month)[1])
        landing = month_end + timedelta(days=credit_days + PAY_LAG_DAYS)
        gross = rates["revenue"] * (1 + MVA_RATE)
        if (month.year, month.month) == (today.year, today.month):
            gross = max(0.0, gross - invoiced_this_month)
        if today <= landing < horizon and round(gross) > 0:
            expected.append({"date": landing, "amount": gross,
                             "kind": "new_sales",
                             "label": f"Fakturering {MONTH_NAMES[month.month - 1]}"
                                      f", betalt"})
        # The VAT on that invoicing, whether or not the customer has paid by
        # then — the deadline does not wait for the money. Scheduled even when
        # the receipt itself falls outside the window, because that is the case
        # that hurts: the liability inside, the cash outside.
        net_vat = rates["revenue"] * MVA_RATE * (1 - vat_share)
        if (month.year, month.month) == (today.year, today.month):
            net_vat = max(0.0, net_vat - booked_vat)
        vat_due = workdays.forward(
            commitments.term_due(month.year, month.month, commitments.MVA_TERMS))
        if today <= vat_due < horizon and round(net_vat) > 0:
            expected.append({"date": vat_due, "amount": -net_vat,
                             "kind": "vat_future",
                             "label": f"Merverdiavgift på fakturering "
                                      f"{MONTH_NAMES[month.month - 1]}"})
        cost_day = month_end
        if month > date(today.year, today.month, 1) and today <= cost_day < horizon:
            expected.append({"date": cost_day, "amount": -rates["opex"],
                             "kind": "opex",
                             "label": f"Driftskostnader "
                                      f"{MONTH_NAMES[month.month - 1]}"})
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
    data["bank"] = _bank_payload(booked, gap, ar_paid, ap_paid)
    # What is still owed after the bank's unbooked receipts: a customer who
    # has paid must not be sent a reminder because the books are behind.
    data["ar_open"] = ar_due
    # Whether that list is the whole book. An empty list from a failed call
    # reads exactly like a book with nobody late, and cards.py closes every
    # collections card on the strength of it unless told otherwise.
    data["ar_complete"] = ar_complete
    # A forecast missing a register is not a forecast, and holding one for the
    # full ten minutes is how a two-second Tripletex blip becomes ten minutes
    # of a company being told it has no receivables. `Cached` keeps a degraded
    # build only long enough to stop a stampede, then goes and asks again.
    data["partial"] = not (ar_complete and ap_complete)
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
           f"- **Bundet linje** — bare det som allerede er fakturert inn og ut, "
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
               f"{_kr(a['monthly_opex'])} kr, kredittid {a['credit_days']} dager "
               f"pluss {a['pay_lag_days']} dagers forsinkelse, forfalte fakturaer "
               f"fordelt over {a['late_spread_weeks']} uker.\n")

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
