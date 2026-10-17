"""Saldobalanse per måned, bygget av get_balance_sheet én måned om gangen.

Tripletex fjernet rapporten «Saldobalanse per måned» fra fetch_report i
oktober 2026 og pekte på get_balance_sheet i stedet: ett kall per måned,
inngående saldo fra første måned og utgående fra siste. Fire moduler leste
rapporten (forsiden, forpliktelsene, kontantstrømmen og helsesjekken), og alle
regner på formen den hadde. Så denne modulen bygger den samme formen, og
ingen av dem trenger å vite at kilden er byttet:

    columns: Inngående balanse, Jan, Feb, …, <siste måned>, Utgående saldo
    rows:    {"path": "1920 Bedriftskonto", "cells": [IB, jan, feb, …, UB]}

Cellene er akkumulert saldo ved utgangen av måneden, som før. Rapporten lot
cella stå tom når kontoen ikke hadde bevegelse den måneden, og modulene leser
tomt som «uendret»; det gjør denne også, ut fra hasPostingsInPeriod.

En måned som ikke kan leses, feller hele tabellen. Et hull midt i året ville
lest som en måned uten bevegelse, og det er den ene feilen som ser riktig ut.
"""
import asyncio
from datetime import date, timedelta

MONTHS = ["Jan", "Feb", "Mars", "April", "Mai", "Juni",
          "Juli", "Aug", "Sept", "Okt", "Nov", "Des"]
OPENING = "Inngående balanse"
CLOSING = "Utgående saldo"


class Incomplete(RuntimeError):
    """En måned svarte ikke, eller svarte med en avkortet tabell."""


def _windows(start: date, end: date) -> list[tuple[int, date, date]]:
    """(måned, fra, til-og-uten) for hver måned fra `start` til og med `end`.
    Siste vindu slutter dagen etter `end`, som rapporten gjorde med period_end."""
    out = []
    first = date(start.year, start.month, 1)
    while first <= end:
        nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
        out.append((first.month, max(first, start), min(nxt, end + timedelta(days=1))))
        first = nxt
    return out


def _col(columns: list, name: str) -> int:
    names = [c.get("name") for c in columns]
    if name not in names:
        raise Incomplete(f"get_balance_sheet mangler kolonnen «{name}»")
    return names.index(name)


def _path(row: dict) -> str:
    acc = row.get("account") or {}
    if acc.get("accountNumber") is not None:
        return f"{acc['accountNumber']} {acc.get('accountName') or ''}".strip()
    p = row.get("path")
    return p[0] if isinstance(p, list) and p else str(p or "")


async def monthly(client, period_start: str, period_end: str) -> dict:
    """Saldobalanse per måned for perioden, i formen fetch_report ga.

    `client` er MCP-klienten modulen allerede bruker (og som testene bytter
    ut). Kallene går parallelt; klienten selv holder antallet i lufta nede."""
    start, end = date.fromisoformat(period_start), date.fromisoformat(period_end)
    if end < start:
        raise ValueError("period_end er før period_start")
    windows = _windows(start, end)
    answers = await asyncio.gather(
        *(client.call("get_balance_sheet", {
            "dateFrom": a.isoformat(), "dateToExclusive": b.isoformat(),
            # Uten flagget mangler en konto som står på null en måned, og da
            # forskyver kolonnene seg.
            "showAccountsWithoutTransactionsInPeriod": True})
          for _, a, b in windows),
        return_exceptions=True)

    accounts: dict[str, list] = {}
    order: list[str] = []
    n = len(windows)
    for i, ((month, a, _), r) in enumerate(zip(windows, answers)):
        if isinstance(r, Exception):
            raise Incomplete(f"Saldobalansen for {MONTHS[month - 1]} kunne ikke leses: {r}")
        table = (r or {}).get("table") or {}
        if table.get("omitted_row_count"):
            raise Incomplete(f"Saldobalansen for {MONTHS[month - 1]} kom avkortet "
                             f"({table['omitted_row_count']} kontoer utelatt)")
        cols = table.get("columns") or []
        ib, ub = _col(cols, "Inngående balanse"), _col(cols, "Utgående balanse")
        for row in table.get("rows") or []:
            path = _path(row)
            if not path[:1].isdigit():
                continue
            if path not in accounts:
                # [IB] + én celle per måned + [UB]; en konto som dukker opp
                # midt i året har ingen bevegelse før det.
                accounts[path] = [None] * (n + 2)
                order.append(path)
            cells = row.get("cells") or []
            moved = (row.get("account") or {}).get("hasPostingsInPeriod", True)
            out = cells[ub] if ub < len(cells) else None
            if i == 0:
                accounts[path][0] = cells[ib] if ib < len(cells) else None
            accounts[path][1 + i] = out if moved else None
            if i == n - 1:
                accounts[path][-1] = out

    # En konto som ikke er med i siste måned, har likevel en utgående saldo:
    # den siste den hadde.
    for cells in accounts.values():
        if cells[-1] is None:
            cells[-1] = next((c for c in reversed(cells[:-1]) if c is not None), None)

    columns = [OPENING] + [MONTHS[m - 1] for m, _, _ in windows] + [CLOSING]
    return {"table": {"columns": [{"name": c} for c in columns],
                      "rows": [{"path": p, "cells": accounts[p]} for p in order]}}
