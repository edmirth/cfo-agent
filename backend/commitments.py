"""How much of the money in the bank is actually the company's.

The question no SMB owner is ever asked and every one of them gets wrong. A
bank balance looks like money. Most of it usually belongs to someone else: VAT
collected on the state's behalf, tax deducted from employees' pay, employer's
contribution, holiday pay earned but not paid out, wages for a month already
worked, corporation tax on profit nobody has booked yet.

An owner who reads the bank balance as spending money hires a person he cannot
afford, and finds out in June when feriepenger leave and the VAT falls due in
the same fortnight.

So this takes the bank, subtracts what is committed, sorts it by when it
actually falls due, and produces one number: what is genuinely his. No model
is involved — it is arithmetic on the ledger, and it must be exact, because it
is the number he will make decisions on.

Two things it is careful about:

- **When, not whether, the tax leaves.** Until 2026 withheld employee tax sat
  on a restricted account and was settled bimonthly; from 2026 it goes to
  Skatteetaten on pay day, so it leaves with the salary and is not a commitment
  waiting for a term date.
- **When, not just how much.** Holiday pay in June is not the same problem as
  VAT in three weeks, and presenting them as one lump is how a solvent company
  is told it is broke.
"""
import asyncio
import calendar
import logging
from dataclasses import dataclass
from datetime import date, timedelta

import bankgap
import company
import freshness
import workdays
from mcp_client import mcp
import saldobalanse

log = logging.getLogger("cfo.commitments")

CACHE_SECONDS = 600

TAX_RATE = 0.22          # alminnelig inntekt for an AS
NEAR_DAYS = 30
SOON_DAYS = 90


# ------------------------------------------------------------ due dates
# Norwegian settlement calendar. Both are two-month terms, on different days:
# VAT on the 10th of the month after the term, withholding tax and employer's
# contribution on the 15th. The third VAT term is the summer exception.
MVA_TERMS = [((1, 2), (4, 10)), ((3, 4), (6, 10)), ((5, 6), (8, 31)),
             ((7, 8), (10, 10)), ((9, 10), (12, 10)), ((11, 12), (2, 10))]
SKATT_TERMS = [((1, 2), (3, 15)), ((3, 4), (5, 15)), ((5, 6), (7, 15)),
               ((7, 8), (9, 15)), ((9, 10), (11, 15)), ((11, 12), (1, 15))]


def term_due(year: int, month: int, terms: list) -> date:
    """When the term containing `month` falls due.

    `_next_due` answers "what is the next deadline from here", which is the
    right question for a balance already sitting in the ledger. It is the wrong
    one for activity that has not happened yet: VAT on November's invoicing is
    not due at the next deadline, it is due at November's own. Public because
    the forecast needs it to date liabilities it is creating itself.
    """
    for months, (due_month, due_day) in terms:
        if month in months:
            # A term settled in a lower month number than it covers settles in
            # the new year — November/December VAT falls due in February.
            roll = due_month < months[0]
            return date(year + 1 if roll else year, due_month, due_day)
    raise ValueError(f"no term covers month {month}")


def _next_due(today: date, terms: list) -> date:
    """The first settlement on or after today, by the day it is actually due.

    A deadline on a weekend or holiday is due the next working day, so it is
    still ahead on that Monday. Compared on the literal date, 15 November 2026
    (a Sunday) had already passed on Monday the 16th, and the employer's
    contribution due that very day was dated to 15 January instead. The
    literal date is returned; the caller rolls it forward as before.
    """
    candidates = []
    for _, (month, day) in terms:
        for year in (today.year, today.year + 1):
            due = date(year, month, day)
            if workdays.forward(due) >= today:
                candidates.append(due)
    return min(candidates)


FERIE_MONTH = 6          # the usual payout month, where nothing is stated


def ferie_month() -> int:
    """The month feriepenger is paid out in.

    June for most Norwegian companies, but not all: some pay with the July run,
    and a company that shuts in a different month moves it. Public and the only
    implementation, for the same reason `payday` is — the forecast withholds a
    month's ordinary salary against this month, and a second opinion about
    which month that is would put the feriepenger in one week and the missing
    salary in another.
    """
    stated = company.setting("ferie_utbetalingsmnd")
    if stated and 1 <= int(stated) <= 12:
        return int(stated)
    return FERIE_MONTH


def ferie_month_is_stated() -> bool:
    """Whether the payout month comes from the company or from our assumption."""
    stated = company.setting("ferie_utbetalingsmnd")
    return stated is not None and 1 <= int(stated) <= 12


def _next_ferie(today: date) -> date:
    """Feriepenger are paid out with one named month's payroll run.

    With the run, not at month end. The two are the same event: the holiday
    month's ordinary salary is withheld *because* feriepenger is paid instead,
    and cashflow withholds it on the pay day. Dating the payout to the last of
    the month put the money three forecast weeks away from the salary it
    replaces, so the week of the run showed no staff cost at all while the
    briefing told the owner the two were paired. `payday` is the one
    implementation of when wages leave, and it still falls back to month end
    for a company that has not said otherwise.
    """
    month = ferie_month()
    year = today.year
    # Gone once the run has been paid, which on a weekend pay day is the
    # Friday before it.
    if today.month > month or (today.month == month
                               and today > workdays.backward(payday(year, month))):
        # This year's run has gone. What is left on 2940 is next year's
        # accrual building up, and it is due at next year's run.
        year += 1
    return payday(year, month)


def payday(year: int, month: int) -> date:
    """The day wages leave the account in a given month.

    Public, and the only implementation, because two of them disagreed. This
    module read `lonn_utbetalingsdag` from company.md while cashflow.py computed
    its own pay day as month end, so the same wages were dated the 20th in one
    place and the 31st in the other. Over a 13-week horizon that put two runs
    ten days late and dropped December's entirely, month end falling outside the
    window where the 20th fell inside it.

    The pay day is a company habit the ledger does not state. Where they have
    written it down we use it; otherwise month end is the assumption, and it is
    declared as one.
    """
    last = calendar.monthrange(year, month)[1]
    stated = company.setting("lonn_utbetalingsdag")
    day = min(int(stated), last) if stated else last
    return date(year, month, max(1, day))


def payday_is_stated() -> bool:
    """Whether the pay day comes from the company or from our assumption."""
    return company.setting("lonn_utbetalingsdag") is not None


def _next_payroll(today: date) -> date:
    """Wages already earned are paid with the next run."""
    run = payday(today.year, today.month)
    # Gone once paid — the Friday before, when the pay day is a weekend.
    if workdays.backward(run) < today:       # this month's run has gone
        year, month = ((today.year + 1, 1) if today.month == 12
                       else (today.year, today.month + 1))
        run = payday(year, month)
    return run


def _running_due(today: date, terms: list) -> date:
    """The deadline of the term today falls in — where a term is still accumulating.

    Not "the settlement after next". That is the same date only while the
    previous term is still unpaid; once its deadline passes, the next
    settlement *is* this term's, and skipping one more put Sept–Oct VAT on
    10 February, outside the thirteen weeks.
    """
    return term_due(today.year, today.month, terms)


def _tax_due(today: date) -> date:
    """Forskuddsskatt for an AS falls in two instalments after year end.

    For tax already *booked* — last year's, sitting on 2500 — so in January to
    April its instalments are this year's. Tax on this year's profit is a year
    further out: see `_this_years_tax_due`."""
    for year, month in ((today.year, 2), (today.year, 4), (today.year + 1, 2)):
        due = date(year, month, 15)
        if workdays.forward(due) >= today:   # the working day it moves to
            return due
    return date(today.year + 1, 2, 15)


def _this_years_tax_due(today: date) -> date:
    """Tax on this year's profit is due after this year ends — never in it.

    Sharing `_tax_due` dated it to this year's 15 February or 15 April from
    January to mid-April, which are last year's instalments: this year's tax
    was pulled a whole year forward and into the thirteen-week forecast."""
    return date(today.year + 1, 2, 15)


# ------------------------------------------------------------- groups
@dataclass(frozen=True)
class Group:
    id: str
    label: str            # what the accountant calls it
    plain: str            # what it is, to someone who does not know
    ranges: tuple         # one obligation often sits on several accounts
    kind: str             # "holding" = never his money; "bill" = his, owed
    due: object           # callable(today) -> date


GROUPS = [
    Group("mva_oppgjor", "Merverdiavgift, avsluttet termin", "moms fra en "
          "avsluttet periode som skal betales ved neste forfall",
          ((2740, 2749),), "holding", lambda d: _next_due(d, MVA_TERMS)),
    Group("mva_lopende", "Merverdiavgift, inneværende termin", "moms du har "
          "krevd inn så langt i denne perioden og betaler ved neste forfall "
          "etter det", ((2700, 2739),), "holding",
          lambda d: _running_due(d, MVA_TERMS)),
    Group("forskuddstrekk", "Forskudds- og utleggstrekk", "skatt og trekk du "
          "har holdt tilbake fra lønnen til de ansatte og skal betale videre",
          ((2600, 2619),), "holding", lambda d: _next_due(d, SKATT_TERMS)),
    Group("aga", "Arbeidsgiveravgift", "avgiften du betaler staten på toppen "
          "av lønnen", ((2770, 2779),), "holding",
          lambda d: _next_due(d, SKATT_TERMS)),
    Group("aga_ferie", "Arbeidsgiveravgift på feriepenger", "avgiften på "
          "feriepengene, som forfaller sammen med dem", ((2780, 2789),),
          "holding", _next_ferie),
    Group("feriepenger", "Skyldig feriepenger", "feriepenger de ansatte har "
          "tjent opp og får utbetalt til sommeren", ((2940, 2944),), "holding",
          _next_ferie),
    Group("skyldig_lonn", "Skyldig og periodisert lønn", "lønn for arbeid som "
          "allerede er utført, men ikke utbetalt", ((2945, 2949),), "bill",
          _next_payroll),
    Group("betalbar_skatt", "Betalbar skatt", "selskapsskatt som er fastsatt "
          "og skal betales", ((2500, 2540),), "holding", _tax_due),
    Group("leverandorgjeld", "Leverandørgjeld", "regninger fra leverandører "
          "som ikke er betalt", ((2400, 2409),), "bill", lambda d: d),
    Group("ansatte_eiere", "Gjeld til ansatte og eiere", "penger selskapet "
          "skylder deg eller de ansatte", ((2250, 2259), (2910, 2919)), "bill",
          lambda d: d),
    Group("annen_gjeld", "Annen kortsiktig gjeld", "andre regninger som "
          "forfaller snart", ((2990, 2999),), "bill", lambda d: d),
]

# Deliberately excluded: 2120 utsatt skatt is an accounting figure, not money
# anyone will ask for. Instalment debt is reported apart, because the whole
# balance is not due at once and folding it in implies that it is.
# Statute fixes the tax dates. These are inferred, and are shown as inferred —
# except the pay day, which stops being an inference the moment the company
# writes it in. Decided per build, not at import: the CEO edits company.md in
# the app, and the label has to follow without a restart.
ASSUMED_DUE = {"leverandorgjeld", "ansatte_eiere", "annen_gjeld"}


# Which way a date moves when it lands on a weekend or a holiday. Statutory
# deadlines roll forward to the next working day; wages roll back to the last
# one, because staff are not left short over a weekend. Supplier bills are
# absent from both: those carry a real due date from the invoice, and guessing
# which way a given supplier shifts it would be inventing a fact.
PAID_EARLY = {"skyldig_lonn", "feriepenger"}
SHIFTED = PAID_EARLY | {"mva_oppgjor", "mva_lopende", "mva_forrige_termin", "forskuddstrekk", "aga",
                        "aga_ferie", "betalbar_skatt", "arets_skatt"}


def _shift(group_id: str, due: date) -> date:
    """Move a due date onto a working day, in the direction that obligation
    actually moves. Anything not listed keeps the date it was given."""
    if group_id in PAID_EARLY:
        return workdays.backward(due)
    if group_id in SHIFTED:
        return workdays.forward(due)
    return due


MVA_RUNNING = ((2700, 2739),)


def _split_vat(items: list[dict], rows: list[dict], columns: list[str],
               today: date, paid: bool = False) -> None:
    """Date a completed VAT term to its own deadline, not the next one.

    2700/2710 hold the term being accrued. They also hold the *previous* term
    whenever the bookkeeper has not yet moved it to the settlement account —
    and that previous term is already owed, on a date that can be two months
    earlier. Reading the closing balance as one number and dating all of it to
    the next settlement is how 797 572 kr due 12 October came to be forecast as
    leaving on 10 December.

    The split is read off the report rather than estimated: the balance as at
    the end of the last completed term is that term, because a term that was
    transferred out shows zero in its own month column.

    `paid` is what the report cannot say: a term paid early, straight against
    2700, still shows in its own month column until the deadline. Without it
    this term's VAT was relabelled as the paid one and dated to its deadline.
    """
    running = next((i for i in items if i["id"] == "mva_lopende"), None)
    term = _completed_term(today)
    if running is None or term is None or paid:
        return
    month, due = term
    at_end = _term_end_balance(rows, columns, month, today)
    if at_end is None:
        return
    completed = round(-at_end, 2)
    total = running["amount"]
    # Transferred normally, or nothing left behind: one term, one date.
    if completed < 0.5 or total < 0.5:
        return
    completed = min(completed, total)
    remainder = round(total - completed, 2)

    running["amount"] = remainder
    running["plain"] = ("moms på det som er bokført i denne terminen så langt — "
                        "beløpet vokser mens bilagene føres")
    running["accruing"] = True
    items.append({
        "id": "mva_forrige_termin",
        "label": "Merverdiavgift, avsluttet termin",
        "plain": "moms for en termin som er over og forfaller på egen dato, "
                 "selv om den ennå ikke er overført til oppgjørskontoen",
        "amount": completed, "kind": "holding",
        "due": _shift("mva_forrige_termin", due).isoformat(),
        "days": (_shift("mva_forrige_termin", due) - today).days,
        "accounts": running["accounts"], "estimated": False,
        "assumed_due": False})
    if remainder < 0.5:
        items.remove(running)


PAID_TOLERANCE = 1.0      # kr; a VAT payment is the term's amount to the krone
POSTING_PAGE = 100        # the most search_ledger_postings returns per call
POSTING_PAGES = 20


def _term_end(month: int, due: date) -> date:
    """Last day of the term ending in `month` that settles on `due`."""
    year = due.year if month <= due.month else due.year - 1
    return date(year, month, calendar.monthrange(year, month)[1])


async def _paid_early(rows: list[dict], columns: list[str], today: date) -> bool:
    """Has the completed term already been paid, ahead of its deadline?

    Only the postings can tell. A payment booked straight against 2700 leaves
    the term's own month column unchanged, so the report reads the same paid
    or unpaid. What gives it away is one voucher on 2700–2739 since the term
    ended that nets to the term's amount in debit — a sales invoice nets to
    its own VAT in credit, and does not land on that figure by accident.

    Asked only in the days between a term ending and its deadline, when there
    is a completed term to split at all. A failed call answers "not paid":
    the money then shows on the earlier date, the safe direction to be wrong.
    """
    term = _completed_term(today)
    if term is None:
        return False
    month, due = term
    at_end = _term_end_balance(rows, columns, month, today)
    if at_end is None or -at_end < 0.5:
        return False
    owed = -at_end
    start = _term_end(month, due) + timedelta(days=1)
    postings: list[dict] = []
    try:
        # Every invoice puts a line on 2700, so a month runs to hundreds of
        # rows and the API returns a hundred at a time, in voucher order.
        for page in range(POSTING_PAGES):
            result = await mcp.call("search_ledger_postings", {
                "dateFrom": start.isoformat(),
                # dateTo is exclusive; today's postings count.
                "dateTo": (today + timedelta(days=1)).isoformat(),
                "accountNumberFrom": MVA_RUNNING[0][0],
                "accountNumberTo": MVA_RUNNING[0][1],
                "count": POSTING_PAGE, "from": page * POSTING_PAGE})
            postings += result.get("postings") or []
            if not result.get("hasMore"):
                break
        else:
            # A voucher half-read could net to anything; not knowing is "not paid".
            log.warning("Commitments: mer enn %d mva-posteringer siden %s; "
                        "antar ubetalt", POSTING_PAGES * POSTING_PAGE, start)
            return False
    except Exception as exc:  # noqa: BLE001
        log.warning("Commitments: mva-posteringene kunne ikke leses: %s", exc)
        return False
    by_voucher: dict = {}
    for r in postings:
        key = r.get("voucherId") or r.get("id")
        by_voucher[key] = by_voucher.get(key, 0.0) + float(r.get("amount") or 0)
    return any(abs(net - owed) <= PAID_TOLERANCE for net in by_voucher.values())


def _assumed_due() -> set[str]:
    if company.setting("lonn_utbetalingsdag"):
        return ASSUMED_DUE
    return ASSUMED_DUE | {"skyldig_lonn"}

LOANS = (2200, 2249)
BANK = (1900, 1949)
RESTRICTED = (1950, 1959)   # bundet skattetrekkskonto


def _account(row: dict) -> int | None:
    head = (row.get("path") or "").split(" ", 1)[0]
    return int(head) if head.isdigit() else None


def _closing(row: dict) -> float:
    cells = [c for c in (row.get("cells") or []) if isinstance(c, (int, float))]
    return float(cells[-1]) if cells else 0.0


MONTH_COLUMNS = ["Jan", "Feb", "Mars", "April", "Mai", "Juni",
                 "Juli", "Aug", "Sept", "Okt", "Nov", "Des"]


def _at_month(rows: list[dict], ranges, columns: list[str], month: int) -> float | None:
    """Summed balance across `ranges` as at the end of `month` (1-12).

    The monthly saldobalanse reflects posting dates, so a term that was
    transferred out shows zero in its own month column. That is what makes the
    split below readable off the report rather than guessed."""
    try:
        idx = columns.index(MONTH_COLUMNS[month - 1])
    except (ValueError, IndexError):
        return None
    total, found = 0.0, False
    for r in rows:
        n = _account(r)
        if n is None or not any(low <= n <= high for low, high in ranges):
            continue
        cells = r.get("cells") or []
        if idx < len(cells) and isinstance(cells[idx], (int, float)):
            total += float(cells[idx])
            found = True
    return total if found else None


OPENING = "Inngående balanse"


def _term_end_balance(rows: list[dict], columns: list[str], month: int,
                      today: date) -> float | None:
    """The VAT accounts' balance at the end of a completed term's last month.

    The report covers this year only. A term that ended last year — November
    and December, owed on 10 February — has no column of its own in it, so
    the split never ran in January and the whole balance was dated to April.
    Its month-end balance is this year's opening balance."""
    if month > today.month:
        try:
            idx = columns.index(OPENING)
        except ValueError:
            return None
        total, found = 0.0, False
        for r in rows:
            n = _account(r)
            if n is None or not any(lo <= n <= hi for lo, hi in MVA_RUNNING):
                continue
            cells = r.get("cells") or []
            if idx < len(cells) and isinstance(cells[idx], (int, float)):
                total += float(cells[idx])
                found = True
        return total if found else None
    return _at_month(rows, MVA_RUNNING, columns, month)


def _completed_term(today: date) -> tuple[int, date] | None:
    """The most recent VAT term that has ended, and when it falls due.

    Terms run two months and settle on the 10th of the month after — Jul-Aug on
    10 October. A term that ended is owed on a known date whether or not the
    bookkeeper has moved it to the settlement account yet.

    Only until that date. Once the deadline has passed the term has been paid,
    and the month-end balance that still shows it is history: reading it as
    owed would date this term's VAT to a deadline already gone."""
    best = None
    for (m1, m2), (dm, dd) in MVA_TERMS:
        for year in (today.year - 1, today.year):
            end = date(year + (1 if m2 < m1 else 0), m2,
                       calendar.monthrange(year + (1 if m2 < m1 else 0), m2)[1])
            if end >= today:
                continue
            due = date(year if dm > m2 else year + 1, dm, dd)
            if _shift("mva_forrige_termin", due) < today:
                continue
            if best is None or end > best[1]:
                best = (m2, end, due)
    return (best[0], best[2]) if best else None


def _sum_range(rows: list[dict], ranges) -> tuple[float, list[str]]:
    """Closing balances across account ranges, with the accounts included."""
    total, names = 0.0, []
    for r in rows:
        n = _account(r)
        if n is None:
            continue
        if any(low <= n <= high for low, high in ranges):
            total += _closing(r)
            names.append((r.get("path") or "").strip())
    return total, names


def _cell(rows: list[dict], path: str, idx: int = 0):
    for r in rows:
        if r.get("path") == path:
            cells = r.get("cells") or []
            if idx < len(cells) and isinstance(cells[idx], (int, float)):
                return float(cells[idx])
    return None


def _kr(value) -> str:
    if value is None:
        return "—"
    return f"{round(value):,}".replace(",", " ")


async def build(today: date | None = None) -> dict:
    today = today or date.today()
    start, end = f"{today.year}-01-01", today.isoformat()

    balance, pnl = await asyncio.gather(
        saldobalanse.monthly(mcp, start, end),
        mcp.call("fetch_report", {"report_name": "Resultatrapport",
                                  "period_start": start, "period_end": end, "limit": 0}),
        return_exceptions=True,
    )
    for name, r in (("saldobalanse", balance), ("resultatrapport", pnl)):
        if isinstance(r, Exception):
            log.warning("Commitments: %s feilet: %s", name, r)
    if isinstance(balance, Exception) or not isinstance(balance, dict) \
            or "table" not in balance:
        raise RuntimeError("Kunne ikke lese saldobalansen")
    pnl = {} if isinstance(pnl, Exception) else (pnl or {})

    rows = balance.get("table", {}).get("rows", []) or []
    columns = [c.get("name") for c in balance.get("table", {}).get("columns", [])]

    # Liabilities are credit balances, so what is owed is the balance negated.
    # A liability sitting in debit is a posting problem, not a negative
    # obligation: counting it would hand the owner cash he does not have.
    bank_free, bank_accounts = _sum_range(rows, (BANK,))
    restricted, _ = _sum_range(rows, (RESTRICTED,))

    # The money in the bank, not the booked balance: the feed runs days ahead
    # of the bookkeeping, and "how much of this is mine" asked of a figure
    # 377 000 kr short answers the wrong question. Measured once here and
    # carried to the forecast, so the two screens open on the same krone.
    bank_booked = bank_free
    gap = await bankgap.measured(today, rows, columns, client=mcp)
    if gap:
        bank_free = bank_booked + gap["adjustment"]
    loans_balance, loan_accounts = _sum_range(rows, (LOANS,))

    items, anomalies = [], []
    assumed = _assumed_due()
    for g in GROUPS:
        raw, accounts = _sum_range(rows, g.ranges)
        owed = -raw
        if not accounts:
            continue
        if owed < -0.5:
            anomalies.append(
                f"{g.label} står i debet med {_kr(abs(owed))} kr "
                f"({', '.join(accounts)}) — enten en forskuddsbetaling eller "
                f"en posteringsfeil. Regnet som null her.")
            owed = 0.0
        if abs(owed) < 0.5:
            continue
        due = _shift(g.id, g.due(today))
        items.append({"id": g.id, "label": g.label, "plain": g.plain,
                      "amount": round(owed, 2), "kind": g.kind,
                      "due": due.isoformat(), "days": (due - today).days,
                      "accounts": accounts, "estimated": False,
                      "assumed_due": g.id in assumed})

    paid = (any(i["id"] == "mva_lopende" for i in items)
            and await _paid_early(rows, columns, today))
    _split_vat(items, rows, columns, today, paid=paid)

    # Until 2026 withheld employee tax sat on a restricted account (1950) and
    # was settled on a bimonthly term, so the balance there had to be netted off
    # or it was subtracted from the operating account twice. That regime is
    # gone: from 2026 there is no skattetrekkskonto and the trekk is paid to
    # Skatteetaten the same day as the salary. 1950 was emptied in January and
    # the offset is retired with it.
    #
    # A balance left on 2600 is therefore not money waiting for a term date —
    # it is a transfer that should already have gone, so it is dated today
    # rather than to a settlement that no longer exists.
    covered = 0.0
    trekk = next((i for i in items if i["id"] == "forskuddstrekk"), None)
    if trekk:
        trekk["due"] = today.isoformat()
        trekk["days"] = 0
        trekk["plain"] = ("skattetrekk som skulle vært overført til Skatteetaten "
                          "samme dag som lønnen")

    # Corporation tax on this year's profit. Norwegian SMBs commonly book it
    # only at year end, so an interim result looks better than it is and the
    # bill arrives as a surprise.
    p = pnl.get("table", {}).get("rows", []) or []
    pre_tax = _cell(p, "Ordinært resultat før skattekostnad")
    booked_tax = _cell(p, "Skattekostnad på ordinært resultat")
    if pre_tax and pre_tax > 0 and not booked_tax:
        due = _shift("arets_skatt", _this_years_tax_due(today))
        items.append({
            "id": "arets_skatt", "label": "Skatt på årets overskudd",
            "plain": "selskapsskatt på overskuddet så langt i år, som ennå "
                     "ikke er bokført",
            "amount": round(pre_tax * TAX_RATE, 2), "kind": "holding",
            "due": due.isoformat(), "days": (due - today).days,
            "accounts": [], "estimated": True, "assumed_due": False})

    items.sort(key=lambda i: i["days"])
    near = sum(i["amount"] for i in items if i["days"] <= NEAR_DAYS)
    soon = sum(i["amount"] for i in items if NEAR_DAYS < i["days"] <= SOON_DAYS)
    later = sum(i["amount"] for i in items if i["days"] > SOON_DAYS)
    committed = near + soon + later

    free_now = bank_free - near
    free_all = bank_free - committed
    verdict = ("negative" if free_all < 0
               else "tight" if free_now < 0 or free_all < bank_free * 0.1
               else "ok")

    return {
        "as_of": end,
        "bank": round(bank_free, 2),
        "bank_booked": round(bank_booked, 2),
        "bank_gap": gap,
        "bank_accounts": bank_accounts,
        "restricted": round(restricted, 2),
        "restricted_covers": round(covered, 2),
        "items": items,
        "totals": {"within_30": round(near, 2), "within_90": round(soon, 2),
                   "later": round(later, 2), "committed": round(committed, 2)},
        "free_now": round(free_now, 2),
        "free_all": round(free_all, 2),
        "loans": {"balance": round(-loans_balance, 2), "accounts": loan_accounts},
        "anomalies": anomalies,
        "verdict": verdict,
    }


_flight = freshness.Cached(build, CACHE_SECONDS)


async def cached() -> dict:
    return await _flight.get()


VERDICT_TEXT = {
    "negative": ("Selskapet skylder bort mer enn det har på konto.",
                 "This is the headline, and it is not softened. It does not "
                 "mean insolvency — most of it falls due months apart and "
                 "invoiced work is still coming in — but it does mean there is "
                 "no spare money, and any question about spending gets that "
                 "answer first."),
    "tight": ("Det meste av pengene på konto er allerede lovet bort.",
              "Say so before any question about spending, hiring or buying."),
    "ok": ("Det står igjen penger etter alt som skal ut.",
           "Say the free figure when money is the subject. Do not editorialise "
           "beyond it."),
}


def _bank_note(data: dict) -> str:
    """Where the bank figure comes from, and the one way it can mislead.

    Lifting the balance to the bank's is right for money that came in. For
    money that went out unbooked it is right too — unless that money paid a
    bill still listed below, which is then taken off twice. Nothing here can
    tell which bill a bank line paid, so the size of the risk is said instead.
    """
    gap = data.get("bank_gap")
    booked = data.get("bank_booked", data.get("bank"))
    if gap is None:
        return (f" — den **bokførte** saldoen; bankavstemmingen kunne ikke "
                f"leses, så om banken står høyere eller lavere er ukjent.")
    if abs(gap["adjustment"]) < 1:
        return ""
    note = (f" i banken (bokført {_kr(booked)} kr; banken har {gap['lines']} "
            f"transaksjoner som ikke er bokført ennå"
            + (f", siste {gap['latest']}" if gap.get("latest") else "") + ")")
    if gap.get("stale"):
        note += (f". Bankfeeden stopper {gap['latest']}, så dette er saldoen "
                 f"per den dagen, ikke i dag")
    if gap.get("out"):
        note += (f". {_kr(-gap['out'])} kr av det ubokførte gikk ut; betalte "
                 f"noe av det en regning eller skatt som står i lista under, er "
                 f"den trukket fra to ganger, og det frie beløpet er "
                 f"tilsvarende for lavt")
    return note + "."


def briefing(data: dict | None) -> str:
    """The block injected into the system prompt.

    The figures are exact and in Norwegian so they can be quoted straight to
    the owner; the instructions around them are for you.
    """
    if not data or not data.get("items"):
        return ""
    headline, instruction = VERDICT_TEXT.get(
        data.get("verdict", "ok"), VERDICT_TEXT["ok"])

    out = ["## Hvor mye av pengene på konto som faktisk er selskapets\n",
           f"Computed {data.get('as_of')} from the ledger, no model involved. "
           f"**{headline}** {instruction}\n",
           f"- På konto: **{_kr(data['bank'])} kr**{_bank_note(data)}",
           f"- Allerede lovet bort: **{_kr(data['totals']['committed'])} kr**",
           f"- Skal ut innen 30 dager: **{_kr(data['totals']['within_30'])} kr** "
           f"— da står det igjen **{_kr(data['free_now'])} kr**",
           f"- Fritt når alt er hensyntatt: **{_kr(data['free_all'])} kr**\n"]

    if data.get("restricted"):
        out.append(f"Av dette ligger {_kr(data['restricted'])} kr på bundet "
                   f"skattetrekkskonto og er allerede satt av"
                   + (f", som dekker {_kr(data['restricted_covers'])} kr av "
                      f"skattetrekket." if data.get("restricted_covers") else "."))
    else:
        out.append("Det står ingenting på bundet skattetrekkskonto. Skattetrekk "
                   "som holdes tilbake fra lønn skal normalt settes av der; når "
                   "det ikke er gjort, ligger pengene på driftskontoen og ser "
                   "ut som om de er til overs.")
    out.append("")

    out.append("**Når det forfaller**\n")
    out.append("| Hva | Beløp | Forfaller | Om |")
    out.append("|---|---:|---|---|")
    for i in data["items"]:
        note = " *(anslag)*" if i["estimated"] else " *(antatt dato)*" if i["assumed_due"] else ""
        out.append(f"| {i['label']} — {i['plain']} | {_kr(i['amount'])} kr | "
                   f"{i['due']}{note} | {i['days']} d |")
    out.append("")

    if data.get("loans", {}).get("balance"):
        out.append(f"Lån og avbetaling står på {_kr(data['loans']['balance'])} kr "
                   f"til sammen. Det er ikke tatt med over, fordi bare "
                   f"terminbeløpene forfaller snart — ikke hele saldoen.\n")
    if data.get("anomalies"):
        out.append("**Regnet som null, fordi tallet står på feil side:**\n")
        out += [f"- {a}" for a in data["anomalies"]]
        out.append("")

    out.append(
        "How to use this. It is the figure the owner has never been given and "
        "the one he needs before any decision that costs money — a hire, a "
        "van, a price cut, a dividend. Lead with it whenever he asks what he "
        "can afford, how things are going, or whether there is money. Never "
        "call the bank balance available money. Where a date is marked as an "
        "assumption or an estimate, say so in the same breath — in plain words, "
        "not with an asterisk. Feriepenger in June is not a surprise, it is a "
        "date he can prepare for, and telling him now is the entire point.")
    return "\n".join(out)
