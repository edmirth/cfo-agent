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

- **Money already set aside.** Withheld employee tax is supposed to sit on a
  restricted account (1950). Where it does, it is not in the operating account
  and must not be subtracted from it twice.
- **When, not just how much.** Holiday pay in June is not the same problem as
  VAT in three weeks, and presenting them as one lump is how a solvent company
  is told it is broke.
"""
import asyncio
import calendar
import logging
import time
import company
from dataclasses import dataclass
from datetime import date, timedelta

from mcp_client import mcp

log = logging.getLogger("cfo.commitments")

CACHE_SECONDS = 600
_cache: dict = {}

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


def _next_due(today: date, terms: list) -> date:
    """The first settlement date on or after today."""
    candidates = []
    for _, (month, day) in terms:
        for year in (today.year, today.year + 1):
            due = date(year, month, day)
            if due >= today:
                candidates.append(due)
    return min(candidates)


def _next_june(today: date) -> date:
    """Feriepenger are paid out with the June run."""
    return date(today.year if today.month < 6 else today.year + 1, 6, 30)


def _next_payroll(today: date) -> date:
    """Wages already earned are paid with the next run.

    The pay day is a company habit the ledger does not state. Where they have
    written it in company.md we use it; otherwise month end is the assumption,
    and it is shown as one.
    """
    stated = company.setting("lonn_utbetalingsdag")
    year, month = today.year, today.month
    if stated:
        day = max(1, min(int(stated), 28))
        if today.day > day:                 # this month's run has gone
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return date(year, month, min(day, calendar.monthrange(year, month)[1]))
    if today.day > 25:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(year, month, calendar.monthrange(year, month)[1])


def _second_due(today: date, terms: list) -> date:
    """The settlement after next — where a term is still accumulating."""
    first = _next_due(today, terms)
    return _next_due(first + timedelta(days=1), terms)


def _tax_due(today: date) -> date:
    """Forskuddsskatt for an AS falls in two instalments after year end."""
    for year, month in ((today.year, 2), (today.year, 4), (today.year + 1, 2)):
        due = date(year, month, 15)
        if due >= today:
            return due
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
          lambda d: _second_due(d, MVA_TERMS)),
    Group("forskuddstrekk", "Forskudds- og utleggstrekk", "skatt og trekk du "
          "har holdt tilbake fra lønnen til de ansatte og skal betale videre",
          ((2600, 2619),), "holding", lambda d: _next_due(d, SKATT_TERMS)),
    Group("aga", "Arbeidsgiveravgift", "avgiften du betaler staten på toppen "
          "av lønnen", ((2770, 2779),), "holding",
          lambda d: _next_due(d, SKATT_TERMS)),
    Group("aga_ferie", "Arbeidsgiveravgift på feriepenger", "avgiften på "
          "feriepengene, som forfaller sammen med dem", ((2780, 2789),),
          "holding", _next_june),
    Group("feriepenger", "Skyldig feriepenger", "feriepenger de ansatte har "
          "tjent opp og får utbetalt til sommeren", ((2940, 2944),), "holding",
          _next_june),
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
        mcp.call("fetch_report", {"report_name": "Saldobalanse per måned",
                                  "period_start": start, "period_end": end, "limit": 0}),
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

    # Liabilities are credit balances, so what is owed is the balance negated.
    # A liability sitting in debit is a posting problem, not a negative
    # obligation: counting it would hand the owner cash he does not have.
    bank_free, bank_accounts = _sum_range(rows, (BANK,))
    restricted, _ = _sum_range(rows, (RESTRICTED,))
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
        due = g.due(today)
        items.append({"id": g.id, "label": g.label, "plain": g.plain,
                      "amount": round(owed, 2), "kind": g.kind,
                      "due": due.isoformat(), "days": (due - today).days,
                      "accounts": accounts, "estimated": False,
                      "assumed_due": g.id in assumed})

    # Withheld employee tax is meant to sit on a restricted account. Where it
    # does, that money is not in the operating account and subtracting it from
    # the operating account as well would count it twice.
    covered = 0.0
    trekk = next((i for i in items if i["id"] == "forskuddstrekk"), None)
    if trekk and restricted > 0:
        covered = min(restricted, trekk["amount"])
        trekk["amount"] = round(trekk["amount"] - covered, 2)
        trekk["covered_by_restricted"] = round(covered, 2)
        if trekk["amount"] < 0.5:
            items.remove(trekk)

    # Corporation tax on this year's profit. Norwegian SMBs commonly book it
    # only at year end, so an interim result looks better than it is and the
    # bill arrives as a surprise.
    p = pnl.get("table", {}).get("rows", []) or []
    pre_tax = _cell(p, "Ordinært resultat før skattekostnad")
    booked_tax = _cell(p, "Skattekostnad på ordinært resultat")
    if pre_tax and pre_tax > 0 and not booked_tax:
        due = _tax_due(today)
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


async def cached() -> dict:
    now = time.time()
    if _cache.get("data") and now - _cache.get("at", 0) < CACHE_SECONDS:
        return _cache["data"]
    data = await build()
    _cache.update({"data": data, "at": now})
    return data


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
           f"- På konto: **{_kr(data['bank'])} kr**",
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
