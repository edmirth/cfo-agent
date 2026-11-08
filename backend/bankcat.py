"""Every bank line with a category (card 63).

The forecast read the money going out off the accounts, which are only as
current as the bookkeeping: at the first customer the October costs were
largely unbooked, the input VAT on costs read as half a per cent of the output
VAT, and the running costs came out a quarter below what left the bank. The
bank lines are what actually left. Each gets a category here, so the costs
can be built from them (card 64).

Fixed rules, in order, so the same line always gets the same answer:

1. Who it is by name: the VAT and tax authority, lenders and leasing,
   insurance, pension, bank fees, card spend, NAV, rent, auditor and
   accountant (`RULES`). The posting a matched line is matched to is read the
   same way: "Bankgebyr: …" is a fee whatever the bank called the line.
2. Money in from a customer in the invoice register, or matched to "Betaling:
   Faktura nummer …", is a customer payment.
3. Money out to an employee is wages. The bank spells people as they gave
   their name to it, not as the employee register does: "Kari J.
   Nordmann" against "Nordmann Kari", "Ola Hansen2". Names are
   compared word for word, digits and initials left out, in any order. A
   private person paid within PAYDAY_WINDOW days of the pay day is wages too:
   the register does not know nicknames.
4. Money out to a company (AS, NUF, …) or a supplier in the register, or a
   payment with KID or message, is a supplier.
5. The rest is `ukjent`, named, so the owner can say what it is.

`summary` gives each month's money in and out by category, and the share
that is unknown, which is how much the costs built from this can be trusted.
"""
import asyncio
import logging
import re
from datetime import date, timedelta

import commitments
import workdays
from bankgap import BANK, _norm

log = logging.getLogger("cfo.bankcat")

MONTHS = 6                    # closed months read, and the current one
PAYDAY_WINDOW = 3
CACHE: dict[str, dict] = {}   # one read a day: closed months do not move

RULES: list[tuple[str, re.Pattern]] = [
    ("mva", re.compile(r"MERVERDIAVGIFT|\bMVA\b", re.I)),
    ("skatt", re.compile(r"SKATTEETATEN|SKATTEINNKREV|SKATTEOPPKREV", re.I)),
    ("lan", re.compile(r"FINANCE|FINANS\b|SANTANDER|BN BANK|KREDITT|LEASING|BILUTLEIE|AVDRAG", re.I)),
    ("forsikring", re.compile(r"FORSIKRING|IF SKADE|GJENSIDIGE|\bTRYG\b|FREMTIND|STOREBRAND|\bSPAREBANK 1 FORS", re.I)),
    ("pensjon", re.compile(r"NORDEA LIV|\bKLP\b|PENSJON|DNB LIV", re.I)),
    ("gebyr", re.compile(r"OMKOSTNINGER|GEBYR|RENTER", re.I)),
    ("kort", re.compile(r"\bVISA\b|VAREKJ[ØO]P|KORTKJ[ØO]P|MASTERCARD", re.I)),
    ("nav", re.compile(r"^NAV\b|ARBEIDS- OG VELFERD", re.I)),
    ("husleie", re.compile(r"\bLEIE\b|HUSLEIE", re.I)),
    ("regnskap", re.compile(r"REVISJON|REVISOR|REGNSKAP", re.I)),
]
COMPANY = re.compile(r"\b(AS|ASA|NUF|AB|ANS|DA|SA|BA|LTD|GMBH|KS)\b", re.I)
SUPPLIER_TEXT = re.compile(r"BETALING MED (KID|MELDING)|EFAKTURA|AVTALEGIRO", re.I)
CUSTOMER_POSTING = re.compile(r"Faktura nummer|Kreditnota", re.I)

LABELS = {"kunder": "Kunder", "lonn": "Lønn", "skatt": "Skatt og avgift",
          "mva": "Merverdiavgift", "lan": "Lån og leasing", "forsikring": "Forsikring",
          "pensjon": "Pensjon", "gebyr": "Bankgebyr og renter", "kort": "Kort",
          "nav": "NAV", "husleie": "Husleie", "regnskap": "Revisor og regnskap",
          "leverandorer": "Leverandører", "ukjent": "Ukjent"}


def _words(name: str) -> frozenset[str]:
    """A person's name as words, digits and single letters left out."""
    return frozenset(w for w in re.sub(r"\d+", " ", _norm(name)).split() if len(w) > 1)


def _is_person(name: str) -> bool:
    return not COMPANY.search(name or "") and len(_words(name)) >= 1


def _employee(name: str, employees: list[frozenset[str]]) -> bool:
    words = _words(name)
    if len(words) < 2:
        return False
    return any(words <= e or (len(e) >= 2 and e <= words) for e in employees)


def _near_payday(day: date) -> bool:
    pay = workdays.backward(commitments.payday(day.year, day.month))
    return abs((day - pay).days) <= PAYDAY_WINDOW


def category(line: dict, customers: set[str], employees: list[frozenset[str]],
             suppliers: set[str]) -> str:
    """The category of one bank line: {"date", "name", "amount", "posting"}."""
    name, posting = line.get("name") or "", line.get("posting") or ""
    for cat, pattern in RULES:
        if pattern.search(name) or pattern.search(posting):
            return cat
    key = _norm(name)
    if line["amount"] > 0:
        if key in customers or CUSTOMER_POSTING.search(posting):
            return "kunder"
        return "ukjent"
    if _employee(name, employees):
        return "lonn"
    try:
        day = date.fromisoformat(str(line.get("date"))[:10])
    except ValueError:
        day = None
    if day and _is_person(name) and _near_payday(day):
        return "lonn"
    if key in suppliers or COMPANY.search(name) or SUPPLIER_TEXT.search(name):
        return "leverandorer"
    return "ukjent"


def summary(lines: list[dict], customers: set[str], employees: list[frozenset[str]],
            suppliers: set[str]) -> dict:
    """Each month's money in and out by category, and what is not known."""
    months: dict = {}
    unknown: dict = {}
    for line in lines:
        cat = category(line, customers, employees, suppliers)
        month = str(line.get("date"))[:7]
        m = months.setdefault(month, {})
        side = "inn" if line["amount"] > 0 else "ut"
        m.setdefault(cat, {"inn": 0.0, "ut": 0.0})[side] += line["amount"]
        if cat == "ukjent":
            u = unknown.setdefault((line.get("name") or "").strip(), {"amount": 0.0, "lines": 0})
            u["amount"] += line["amount"]
            u["lines"] += 1
    out_total = sum(-c["ut"] for m in months.values() for c in m.values())
    out_unknown = sum(-m.get("ukjent", {}).get("ut", 0.0) for m in months.values())
    return {
        "months": {k: {c: {s: round(v, 2) for s, v in sides.items()} for c, sides in m.items()}
                   for k, m in sorted(months.items())},
        "unknown": sorted(({"name": n, "amount": round(u["amount"], 2), "lines": u["lines"]}
                           for n, u in unknown.items()), key=lambda u: u["amount"])[:25],
        "unknown_share_out": round(out_unknown / out_total, 3) if out_total else 0.0,
    }


def _month_start(d: date, back: int) -> date:
    y, m = d.year, d.month - back
    while m < 1:
        y, m = y - 1, m + 12
    return date(y, m, 1)


async def lines(client, today: date) -> list[dict]:
    """Every bank line, matched or not, on the bank accounts in the last
    MONTHS closed months and this one."""
    start = _month_start(today, MONTHS)
    periods = await client.call("get_bank_reconciliation_periods", {
        "dateFrom": start.isoformat(),
        "dateTo": _month_start(today, -1).isoformat()})
    keys = sorted({(p["accountNumber"], p["period"]["start"])
                   for p in periods.get("periods") or []
                   if p.get("status") != "not_started"
                   and (p.get("accountNumber") or "").isdigit()
                   and BANK[0] <= int(p["accountNumber"]) <= BANK[1]})
    calls = [(n, s, status) for n, s in keys for status in ("matched", "unmatched")]
    answers = await asyncio.gather(
        *(client.call("get_unmatched_bank_transactions",
                      {"accountNumber": n, "date": s, "matchStatus": status})
          for n, s, status in calls), return_exceptions=True)
    out, seen = [], set()
    for (n, s, status), a in zip(calls, answers):
        if isinstance(a, Exception):
            raise RuntimeError(f"banklinjene for {n} {s} kunne ikke leses: {a}")
        for line in (a.get("matched") if status == "matched" else a.get("unmatched")) or []:
            if not isinstance(line, dict) or line.get("id") in seen:
                continue
            seen.add(line.get("id"))
            amount = line.get("amountCurrency")
            if not isinstance(amount, (int, float)):
                continue
            posting = next((p.get("description") or "" for m in line.get("matches") or []
                            for p in m.get("postings") or []), "")
            out.append({"account": n, "date": line.get("postedDate") or "",
                        "name": line.get("description") or "", "amount": float(amount),
                        "posting": posting})
    return out


async def measured(client, today: date, customers: set[str]) -> dict | None:
    """`summary` of the bank lines, read once a day; None when they cannot be
    read, and then asked again next time."""
    key = today.isoformat()
    if key in CACHE:
        return CACHE[key]
    try:
        bank, staff, register = await asyncio.gather(
            lines(client, today),
            client.call("search_employees", {"count": 100}),
            client.call("list_suppliers", {"count": 1000}))
    except Exception as exc:  # noqa: BLE001 — the costs fall back to the accounts
        log.warning("Bankcat: banklinjene kunne ikke leses: %s", exc)
        return None
    employees = [_words(f"{e.get('firstName') or ''} {e.get('lastName') or ''}")
                 for e in (staff or {}).get("employees") or []]
    suppliers = {_norm(s.get("name") or "") for s in (register or {}).get("suppliers") or []}
    CACHE.clear()
    CACHE[key] = summary(bank, {_norm(c) for c in customers}, [e for e in employees if e], suppliers)
    return CACHE[key]
