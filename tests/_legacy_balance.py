"""Old-style test ledgers, served as get_balance_sheet.

The tests describe a ledger the way «Saldobalanse per måned» printed it: one
row per account, cumulative cells under Inngående balanse, Jan, Feb, …,
Utgående saldo, a blank cell for a month the account did not move. Tripletex
removed that report, and the backend now asks get_balance_sheet once per
month instead (backend/saldobalanse.py).

`balance_sheet(stub)` wraps a stub that still answers the old report and
answers each monthly get_balance_sheet call from it, so a test keeps its
ledger as written and exercises the new path end to end. A failure the stub
raises for the old report is raised for every month, as Tripletex would.
"""
from datetime import date

MONTHS = ["Jan", "Feb", "Mars", "April", "Mai", "Juni",
          "Juli", "Aug", "Sept", "Okt", "Nov", "Des"]


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def month_table(report: dict, month: int) -> dict:
    """The get_balance_sheet answer for `month`, read off the old table."""
    table = (report or {}).get("table") or {}
    cols = [c.get("name") for c in table.get("columns") or []]
    name = MONTHS[month - 1]
    rows = []
    for r in table.get("rows") or []:
        cells = r.get("cells") or []
        path = r.get("path")
        path = path[0] if isinstance(path, list) else str(path or "")
        if not path[:1].isdigit():
            continue
        cell = lambda c: _num(cells[cols.index(c)]) if c in cols and cols.index(c) < len(cells) else None
        # The balance carried into the month: the opening balance, then the
        # last number in an earlier month's column.
        carried = cell("Inngående balanse")
        for m in MONTHS[:month - 1]:
            if (v := cell(m)) is not None:
                carried = v
        v = cell(name)
        moved = v is not None
        out = v if moved else carried
        printed = [c for c in cols if c in MONTHS]
        ub = cell("Utgående saldo")
        if ub is not None and (name not in cols or (printed and name == printed[-1])):
            # The table's last month closes on Utgående saldo, which carries
            # postings the month column had not caught yet. get_balance_sheet
            # has only the one figure, so the test ledger's closing is it.
            out = ub
            moved = moved or ub != carried
        head, _, rest = path.partition(" ")
        opening = carried or 0.0
        rows.append({
            "path": [path],
            "cells": [opening, (out or 0.0) - opening, out or 0.0],
            "account": {"accountNumber": int(head) if head.isdigit() else head,
                        "accountName": rest, "hasPostingsInPeriod": moved},
        })
    return {"table": {"columns": [{"name": "Inngående balanse"}, {"name": "Endring"},
                                  {"name": "Utgående balanse"}],
                      "rows": rows, "omitted_row_count": 0}}


class balance_sheet:
    """Wraps a stub MCP client; everything but get_balance_sheet passes through."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def call(self, tool, args=None):
        if tool != "get_balance_sheet":
            return await self._inner.call(tool, args)
        start = date.fromisoformat(args["dateFrom"])
        report = await self._inner.call("fetch_report", {
            "report_name": "Saldobalanse per måned",
            "period_start": f"{start.year}-01-01",
            "period_end": args["dateToExclusive"], "limit": 0})
        return month_table(report, start.month)
