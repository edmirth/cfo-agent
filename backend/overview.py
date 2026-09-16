"""Nøkkeltall til forsiden, hentet direkte fra Tripletex uten å bruke modellen.

Hver figur er regnet ut her, ikke lest fra Tripletex' egne nøkkeltall — deres
Overskuddsgrad og Egenkapitalrentabilitet kommer tilbake med feil fortegn for et
selskap som går i pluss.
"""
import asyncio
import logging
import time
from datetime import date

from mcp_client import mcp

log = logging.getLogger("cfo.overview")

CACHE_SECONDS = 600
_cache: dict = {}

MONTHS = ["Jan", "Feb", "Mars", "April", "Mai", "Juni",
          "Juli", "Aug", "Sept", "Okt", "Nov", "Des"]
SHORT = ["jan", "feb", "mar", "apr", "mai", "jun",
         "jul", "aug", "sep", "okt", "nov", "des"]


def _rows(report: dict) -> list[dict]:
    return report.get("table", {}).get("rows", []) or []


def _cell(rows: list[dict], path: str, idx: int = 0):
    for r in rows:
        if r.get("path") == path:
            cells = r.get("cells") or []
            if idx < len(cells) and isinstance(cells[idx], (int, float)):
                return float(cells[idx])
    return None


def _starts(rows: list[dict], prefix: str, idx: int = 0):
    for r in rows:
        if (r.get("path") or "").startswith(prefix):
            cells = r.get("cells") or []
            if idx < len(cells) and isinstance(cells[idx], (int, float)):
                return float(cells[idx])
    return None


def _pct(part, whole):
    if part is None or not whole:
        return None
    return round(part / whole * 100, 1)


async def build(today: date | None = None) -> dict:
    today = today or date.today()
    start = f"{today.year}-01-01"
    end = today.isoformat()

    pnl, ratios, ar, monthly = await asyncio.gather(
        mcp.call("fetch_report", {"report_name": "Resultatrapport",
                                  "period_start": start, "period_end": end, "limit": 0}),
        mcp.call("fetch_report", {"report_name": "Nøkkeltallsrapport",
                                  "period_start": start, "period_end": end}),
        mcp.call("fetch_report", {"report_name": "Kundereskontro",
                                  "period_start": start, "period_end": end, "limit": 0}),
        mcp.call("fetch_report", {"report_name": "Saldobalanse per måned",
                                  "period_start": start, "period_end": end, "limit": 0}),
        return_exceptions=True,
    )
    for name, r in (("Resultatrapport", pnl), ("Nøkkeltall", ratios),
                    ("Kundereskontro", ar), ("Saldobalanse", monthly)):
        if isinstance(r, Exception):
            log.warning("%s feilet: %s", name, r)
    pnl, ratios, ar, monthly = [({} if isinstance(x, Exception) else x)
                                for x in (pnl, ratios, ar, monthly)]

    p = _rows(pnl)
    revenue = _cell(p, "Driftsresultat > Driftsinntekter")
    revenue_budget = _cell(p, "Driftsresultat > Driftsinntekter", 1)
    operating = _cell(p, "Driftsresultat")
    operating_budget = _cell(p, "Driftsresultat", 1)
    wages = _cell(p, "Driftsresultat > Driftskostnader > Lønnskostnad")
    wages_budget = _cell(p, "Driftsresultat > Driftskostnader > Lønnskostnad", 1)
    pre_tax = _cell(p, "Ordinært resultat før skattekostnad")
    booked_tax = _cell(p, "Skattekostnad på ordinært resultat")

    # Månedsserie for omsetning, og siste saldo for bank og kundefordringer.
    m = _rows(monthly)
    cols = [c.get("name") for c in monthly.get("table", {}).get("columns", [])]
    series, cash, receivables = [], None, None
    def _account_no(row: dict) -> int | None:
        head = (row.get("path") or "").split(" ", 1)[0]
        return int(head) if head.isdigit() else None

    rev_rows = [r for r in m
                if (n := _account_no(r)) is not None and 3000 <= n <= 3999]
    if rev_rows and cols:
        prev = 0.0
        for i, col in enumerate(cols):
            if col not in MONTHS:
                continue
            cum = 0.0
            for r in rev_rows:                    # summer alle inntektskontoer
                cell = r["cells"][i] if i < len(r.get("cells") or []) else None
                if isinstance(cell, (int, float)):
                    cum += -float(cell)           # inntekter ligger i kredit
            series.append({"month": SHORT[MONTHS.index(col)],
                           "value": round(cum - prev, 2)})
            prev = cum
    for r in m:
        path = r.get("path") or ""
        cells = [c for c in (r.get("cells") or []) if isinstance(c, (int, float))]
        if not cells:
            continue
        if path.startswith("1920"):
            cash = float(cells[-1])
        elif path.startswith("1500"):
            receivables = float(cells[-1])

    # Største enkeltkunde blant fordringene — konsentrasjonsrisikoen.
    ar_rows = sorted(
        ((r.get("path", "").split(" (")[0], float((r.get("cells") or [0, 0])[1]))
         for r in _rows(ar)
         if len(r.get("cells") or []) > 1 and isinstance(r["cells"][1], (int, float))),
        key=lambda kv: -kv[1])
    ar_ledger_total = sum(v for _, v in ar_rows if v > 0) or None
    top_customer = ar_rows[0] if ar_rows else None

    rr = _rows(ratios)
    liquidity = _cell(rr, "Likviditetsgrad 1")
    equity_ratio = _cell(rr, "Egenkapitalandel i % (soliditet)")

    unbooked_tax = None
    if pre_tax and pre_tax > 0 and not booked_tax:
        unbooked_tax = round(pre_tax * 0.22, 2)

    return {
        "company": None,           # fylles av kalleren
        "period": {"from": start, "to": end},
        "generated_at": today.isoformat(),
        "kpis": {
            "omsetning": revenue,
            "omsetning_budsjett": revenue_budget,
            "driftsresultat": operating,
            "driftsresultat_budsjett": operating_budget,
            "driftsmargin_pct": _pct(operating, revenue),
            "lonnsandel_pct": _pct(wages, revenue),
            "lonnsandel_budsjett_pct": _pct(wages_budget, revenue_budget),
            "bank": cash,
            "kundefordringer": receivables or ar_ledger_total,
            "likviditetsgrad": liquidity,
            "egenkapitalandel_pct": round(equity_ratio * 100, 1) if equity_ratio is not None else None,
        },
        "revenue_by_month": series,
        "top_debtor": ({"name": top_customer[0], "amount": top_customer[1],
                        # samme nevner som tallet vi viser, ellers spriker de
                        "share_pct": _pct(top_customer[1],
                                          receivables or ar_ledger_total)}
                       if top_customer and (receivables or ar_ledger_total) else None),
        "flags": {"ubokfort_skatt": unbooked_tax},
    }


async def cached() -> dict:
    now = time.time()
    if _cache.get("data") and now - _cache.get("at", 0) < CACHE_SECONDS:
        return _cache["data"]
    data = await build()
    _cache.update({"data": data, "at": now})
    return data
