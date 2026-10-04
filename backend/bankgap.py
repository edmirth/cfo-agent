"""How far the bank is ahead of the books.

The forecast used to open on the closing balance of 1900-1949 in Saldobalanse:
the *booked* bank balance. The bank feed lands every day; the bookkeeper posts
when he gets to it. On 2 October 2026 the account held about 386 000 kr more
than the ledger said, almost all of it customer payments from the last days of
September that nobody had booked yet — and the owner saw it before the
software did.

Tripletex already knows the difference: Bank > Bankavstemming lists, per
account and month, the bank lines with no posting and the postings with no
bank line. Read across every month, it gives

    money in the bank = booked balance + (bank movement - ledger movement)

summed over the reconciliation periods. The ledger side is taken from the
monthly saldobalanse rather than from the unmatched-postings list, because that
list leaves out postings the user may not read — salary, under the privacy
setting — and a booked salary whose bank line is still unmatched would
otherwise be subtracted from the balance once more. Where the ledger month is
not to hand, the two lists are used instead and the result is marked
approximate.

What cannot be read is said to be unknown, never zero: an account nobody has
ever reconciled, a month skipped in the middle, a list cut at 1000 rows, a
call that failed.

`settle` is the other half, and without it the first half does harm. A
payment the bank has and the ledger has not is, in the ledger, still an open
invoice — so lifting the opening balance while the invoice stays in the
receipts schedule collects the same krone twice. Each unbooked bank line is
matched to the counterparty's open invoices and takes them off the schedule.
"""
import asyncio
import logging
import re
from datetime import date, timedelta

import workdays
from mcp_client import mcp
from preflight import _account, MONTHS

log = logging.getLogger("cfo.bankgap")

BANK = (1900, 1949)          # the same range commitments calls bank_free
WINDOW_MONTHS = 12           # reconciliation periods read back from this month
NAME_MIN = 3                 # a normalised name shorter than this matches nothing
AMOUNT_TOLERANCE = 1.0       # kroner; an exact match is exact to the krone
SUFFIXES = {"as", "asa", "nuf", "ab", "ans", "da", "sa", "ba", "ltd", "gmbh"}


def _kr(v) -> str:
    return f"{round(v):,}".replace(",", " ")


def _month_start(d: date, back: int) -> date:
    y, m = d.year, d.month - back
    while m < 1:
        y, m = y - 1, m + 12
    return date(y, m, 1)


# ------------------------------------------------------------- ledger side
def ledger_moves(rows: list, columns: list, year: int) -> dict:
    """{(account, year, month): movement} for every bank account in the report.

    Saldobalanse per måned is cumulative and leaves a cell blank when the
    account did not move, so each month is the difference from the last
    numeric cell before it. January is measured from the opening balance, not
    from zero — the year's IB is not a movement.
    """
    out = {}
    for r in rows:
        n = _account(r)
        if n is None or not (BANK[0] <= n <= BANK[1]):
            continue
        cells = r.get("cells") or []
        prev = None
        for i, col in enumerate(columns):
            v = cells[i] if i < len(cells) and isinstance(cells[i], (int, float)) else None
            if col not in MONTHS:
                # The column before January is the opening balance.
                if prev is None and v is not None:
                    prev = float(v)
                continue
            month = MONTHS.index(col) + 1
            base = prev if prev is not None else 0.0
            current = float(v) if v is not None else base
            out[(str(n), year, month)] = current - base
            prev = current
    return out


def ledger_balances(rows: list) -> dict:
    """{account: closing balance} for the bank accounts in the report."""
    out = {}
    for r in rows:
        n = _account(r)
        if n is None or not (BANK[0] <= n <= BANK[1]):
            continue
        cells = [c for c in (r.get("cells") or []) if isinstance(c, (int, float))]
        out[str(n)] = float(cells[-1]) if cells else 0.0
    return out


# --------------------------------------------------------------- the gap
def _sum(totals: dict, key: str) -> float:
    return float(((totals or {}).get(key) or {}).get("sum") or 0.0)


def measure(periods: dict, unmatched: dict, moves: dict, balances: dict) -> dict:
    """The difference between bank and books, from what Tripletex answered.

    `periods` is the get_bank_reconciliation_periods answer; `unmatched` maps
    (account, period start) to the get_unmatched_bank_transactions answer, or
    to the exception that call raised. Pure, so the arithmetic is testable on
    the figures it was measured on.
    """
    names = {a.get("number"): a.get("name") or "" for a in periods.get("accounts") or []}
    by_account: dict[str, list] = {}
    for p in periods.get("periods") or []:
        n = p.get("accountNumber")
        if n and n.isdigit() and BANK[0] <= int(n) <= BANK[1]:
            by_account.setdefault(n, []).append(p)

    accounts, unknown, lines = [], [], []
    approximate = False
    for n in sorted(set(by_account) | set(balances)):
        label = f"{n} {names.get(n, '')}".strip()
        ps = sorted(by_account.get(n, []), key=lambda p: p["period"]["start"])
        started = [p for p in ps if p.get("status") != "not_started"]
        if not started:
            if abs(balances.get(n, 0.0)) > 0.5:
                unknown.append(
                    f"Konto {label} står med {_kr(balances[n])} kr i bøkene, men "
                    f"er aldri avstemt mot banken i Tripletex. Om det har kommet "
                    f"noe inn eller gått noe ut der som ikke er bokført, vet vi "
                    f"ikke.")
            continue

        first = started[0]["period"]["start"]
        acct = {"account": n, "name": names.get(n, ""), "adjustment": 0.0,
                "lines": 0, "in": 0.0, "out": 0.0, "postings": 0,
                "postings_sum": 0.0, "url": started[-1].get("url") or ""}
        for p in ps:
            start = p["period"]["start"]
            month = date.fromisoformat(start)
            when = f"{MONTHS[month.month - 1].lower()} {month.year}"
            if p.get("status") == "not_started":
                if start > first:
                    unknown.append(
                        f"Konto {label} er ikke avstemt for {when}, så det som "
                        f"kom inn eller gikk ut den måneden uten å bli bokført "
                        f"er ukjent.")
                continue
            r = unmatched.get((n, start))
            if r is None or isinstance(r, Exception):
                unknown.append(f"Bankavstemmingen for konto {label}, {when}, "
                               f"kunne ikke leses ({r}).")
                continue
            if r.get("truncated"):
                unknown.append(f"Bankavstemmingen for konto {label}, {when}, har "
                               f"over 1000 umatchede linjer og ble kuttet.")
                continue
            t = r.get("totals") or {}
            bank_unbooked = _sum(t, "unmatched")
            ledger_move = moves.get((n, month.year, month.month))
            if ledger_move is not None:
                bank_move = (_sum(t, "matched") + bank_unbooked
                             + _sum(t, "awaitingApproval"))
                gap = bank_move - ledger_move
            else:
                # No ledger month to measure against: fall back to the lists,
                # which miss postings the user may not read.
                gap = bank_unbooked - _sum(t, "unmatchedPostings")
                # Only worth saying when the lists actually had something in
                # them: a closed, empty month from last year is not a guess.
                approximate = approximate or abs(gap) > 0.5 or bool(
                    (t.get("unmatchedPostings") or {}).get("count"))
            acct["adjustment"] += gap
            u = t.get("unmatched") or {}
            acct["lines"] += int(u.get("count") or 0)
            acct["in"] += float(u.get("in") or 0.0)
            acct["out"] += float(u.get("out") or 0.0)
            up = t.get("unmatchedPostings") or {}
            acct["postings"] += int(up.get("count") or 0)
            acct["postings_sum"] += float(up.get("sum") or 0.0)
            for line in r.get("unmatched") or []:
                amount = line.get("amountCurrency")
                if not isinstance(amount, (int, float)):
                    continue
                lines.append({"account": n, "date": line.get("postedDate") or "",
                              "name": line.get("description") or "",
                              "amount": float(amount)})
        acct = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in acct.items()}
        accounts.append(acct)

    return {
        "adjustment": round(sum(a["adjustment"] for a in accounts), 2),
        "lines": sum(a["lines"] for a in accounts),
        "in": round(sum(a["in"] for a in accounts), 2),
        "out": round(sum(a["out"] for a in accounts), 2),
        "postings": sum(a["postings"] for a in accounts),
        "postings_sum": round(sum(a["postings_sum"] for a in accounts), 2),
        "latest": max((l["date"] for l in lines if l["date"]), default=None),
        "accounts": accounts,
        "unbooked": lines,
        "unknown": unknown,
        "approximate": approximate,
    }


async def build(today: date, moves: dict, balances: dict, client=None) -> dict:
    """Read every reconciliation period in the window and measure the gap.

    `client` is the caller's Tripletex client, so a module stubbed in a test
    is stubbed here too rather than reaching past it to the live one."""
    client = client or mcp
    start = _month_start(today, WINDOW_MONTHS - 1)
    end = _month_start(today, -1)
    periods = await client.call("get_bank_reconciliation_periods", {
        "dateFrom": start.isoformat(), "dateTo": end.isoformat()})

    keys = [(p["accountNumber"], p["period"]["start"])
            for p in periods.get("periods") or []
            if p.get("status") != "not_started"
            and (p.get("accountNumber") or "").isdigit()
            and BANK[0] <= int(p["accountNumber"]) <= BANK[1]]
    answers = await asyncio.gather(
        *(client.call("get_unmatched_bank_transactions",
                   {"accountNumber": n, "date": s}) for n, s in keys),
        return_exceptions=True)
    for (n, s), a in zip(keys, answers):
        if isinstance(a, Exception):
            log.warning("Bankgap: %s %s feilet: %s", n, s, a)
    return measure(periods, dict(zip(keys, answers)), moves, balances)


def feed_is_stale(latest: str | None, today: date) -> bool:
    """Whether the bank feed stops before the last working day.

    Lines arrive the working day after they clear, so a feed that has the
    last working day before today is current. With no lines at all there is
    nothing to date the feed by, and nothing is claimed. On 4 October 2026
    the bank held 34 744 kr more than the measured figure: Friday's lines had
    not reached Tripletex yet."""
    if not latest:
        return False
    try:
        last = date.fromisoformat(latest)
    except ValueError:
        return False
    return last < workdays.backward(today - timedelta(days=1))


async def measured(today: date, rows: list, columns: list, client=None) -> dict | None:
    """The gap for this year's saldobalanse, or None when it cannot be read.

    None is not zero: the caller opens on the books and says the bank is
    unknown."""
    try:
        gap = await build(today, ledger_moves(rows, columns, today.year),
                          ledger_balances(rows), client=client)
    except Exception as e:  # noqa: BLE001 — a failed read is declared, not fatal
        log.warning("Bankgap: bankavstemmingen feilet: %s", e)
        return None
    gap["stale"] = feed_is_stale(gap.get("latest"), today)
    return gap


# ------------------------------------------------- what the bank has settled
def _norm(name: str) -> str:
    """A counterparty name as the bank feed and the register can both spell it.

    The feed drops æøå to '!' ("St! Entrepren!r AS"), shouts in capitals and
    keeps the company form; the register does none of that.
    """
    s = re.sub(r"[æøå!?]", "_", (name or "").lower())
    words = [w for w in re.split(r"[^\w]+", s) if w and w not in SUFFIXES]
    return " ".join(words)


def settle(items: list, lines: list, sign: int) -> tuple[list, list]:
    """Take what the unbooked bank lines have already paid off the open list.

    `sign` is +1 for receivables (money in pays customer invoices) and -1 for
    payables. A line pays the invoice of the same counterparty and the same
    amount when there is one; otherwise it pays that counterparty's invoices
    oldest due first, as far as it reaches. A line whose counterparty has no
    open invoice settles nothing — card spend, fees, NAV — and stays in the
    opening balance only.

    Returns the remaining open items (amounts reduced where partly paid) and
    one record per settlement, for the declaration.
    """
    remaining = [dict(i) for i in items]
    settled = []
    for line in sorted(lines, key=lambda l: l["date"]):
        amount = line["amount"] * sign
        key = _norm(line["name"])
        if amount <= 0 or len(key) < NAME_MIN:
            continue
        # Oldest due first, for the exact match as well: two open invoices for
        # the same amount are paid in the order they fell due.
        mine = sorted((i for i in remaining
                       if i["amount"] > 0 and _norm(i["name"]) == key),
                      key=lambda i: i.get("due") or "")
        if not mine:
            continue
        exact = next((i for i in mine
                      if abs(i["amount"] - amount) <= AMOUNT_TOLERANCE), None)
        targets = [exact] if exact else mine
        left = amount
        for inv in targets:
            if left <= AMOUNT_TOLERANCE:
                break
            take = min(inv["amount"], left)
            inv["amount"] = round(inv["amount"] - take, 2)
            left -= take
            settled.append({"name": inv["name"], "number": inv.get("number"),
                            "amount": round(take, 2), "paid": line["date"],
                            "exact": exact is not None})
    return [i for i in remaining if i["amount"] > AMOUNT_TOLERANCE], settled
