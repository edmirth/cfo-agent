"""From a figure back to the entries it is made of.

A CFO who cannot show you the postings behind a number is asking to be taken
on trust, and this product has no right to that. Every balance it reports is a
sum of ledger entries; this hands back the entries.

Two things it deliberately does not do. It does not invent a link into
Tripletex — report results carry their own `url` and those are quoted verbatim;
a constructed one that lands on the wrong view is worse than none. And it does
not silently truncate: when an account has more postings than were fetched, the
count says so, because a trail that is quietly partial is not a trail.
"""
import logging
from datetime import date, timedelta

from mcp_client import mcp

log = logging.getLogger("cfo.trace")

MAX_ROWS = 100


def _kr(v) -> str:
    return f"{round(v):,}".replace(",", " ")


async def account(number: int, date_from: str, date_to: str,
                  limit: int = MAX_ROWS) -> dict:
    """The postings on one account for a period, and what they sum to.

    `date_to` is given the way a person means it — inclusive — and converted,
    because the API's own `dateTo` is exclusive and quietly drops the last day.
    """
    try:
        end = date.fromisoformat(date_to) + timedelta(days=1)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Ugyldig sluttdato: {date_to}") from exc

    result = await mcp.call("search_ledger_postings", {
        "dateFrom": date_from, "dateTo": end.isoformat(),
        "accountNumberFrom": int(number), "accountNumberTo": int(number),
        "count": min(int(limit), MAX_ROWS)})

    rows = result.get("postings") or []
    total = sum(float(r.get("amount") or 0) for r in rows)
    available = result.get("fullResultSize")
    truncated = bool(available and available > len(rows))

    return {
        "account": int(number),
        "account_name": rows[0].get("accountName") if rows else None,
        "period": {"from": date_from, "to": date_to},
        "count": len(rows),
        "available": available,
        "truncated": truncated,
        "total": round(total, 2),
        "entries": [{
            "id": r.get("id"), "date": r.get("date"),
            "description": r.get("description"),
            "amount": float(r.get("amount") or 0),
            "counterparty": r.get("customerName") or r.get("supplierName"),
            "voucher": r.get("voucherId"),
        } for r in rows],
    }


def as_text(trail: dict) -> str:
    """The trail as the agent should show it: entries first, sum last."""
    if not trail["entries"]:
        return (f"Konto {trail['account']} har ingen posteringer mellom "
                f"{trail['period']['from']} og {trail['period']['to']}.")
    lines = [f"Konto {trail['account']}"
             + (f" {trail['account_name']}" if trail["account_name"] else "")
             + f", {trail['period']['from']} til {trail['period']['to']}:"]
    for e in trail["entries"][:40]:
        who = f" ({e['counterparty']})" if e["counterparty"] else ""
        lines.append(f"  {e['date']}  {_kr(e['amount']):>12}  "
                     f"{(e['description'] or '')[:70]}{who}")
    if len(trail["entries"]) > 40:
        lines.append(f"  … og {len(trail['entries']) - 40} til")
    lines.append(f"Sum av {trail['count']} posteringer: {_kr(trail['total'])} kr")
    if trail["truncated"]:
        lines.append(f"ADVARSEL: kontoen har {trail['available']} posteringer i "
                     f"perioden, bare {trail['count']} er hentet. Summen over er "
                     f"derfor ikke hele kontoen — si det hvis du bruker den.")
    return "\n".join(lines)
