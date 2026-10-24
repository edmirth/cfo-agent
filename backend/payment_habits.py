"""How late each customer pays, read off the ledger.

The forecast dated every customer's money the same way: the due date plus
seven days, for the customer who pays on the dot and the one who is always a
month behind alike. The invoices do not say when they were paid, but account
1500 does: every payment is a credit there, with the customer and the day.

Matched to the invoices oldest first, customer by customer, which is how
customers nearly always pay, each fully paid invoice gets the days between
its due date and the payment that closed it. A customer's lateness is the
amount-weighted median of those; one with too few paid invoices takes the
company's, and with too little history altogether the forecast keeps its
seven days.

The payments are read once a day: habits move slowly, and reading a year of
postings takes a few dozen calls.
"""
import asyncio
import logging
import time
from datetime import date, timedelta

log = logging.getLogger("cfo.payment_habits")

CACHE_SECONDS = 24 * 3600
DEGRADED_SECONDS = 45      # a half-read year is asked again soon, as in freshness
RECEIVABLES = (1500, 1509)
PAGE = 100                 # the most search_ledger_postings returns per call
PAGES_PER_MONTH = 15
MIN_CUSTOMER = 3           # paid invoices before a customer has habits of his own
MIN_COMPANY = 5            # paid invoices before the company has one at all
MAX_DAYS = 60              # beyond this, the overdue age groups take over


def _month_windows(today: date) -> list[tuple[date, date]]:
    """Twelve months back, a month a window, end exclusive; the last ends
    tomorrow so today's postings count."""
    out = []
    y, m = today.year, today.month
    for _ in range(12):
        first = date(y, m, 1)
        nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
        out.append((first, min(nxt, today + timedelta(days=1))))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


async def _window(client, start: date, end: date) -> tuple[list, bool]:
    """The 1500 postings of one month, paged. Complete or not."""
    out = []
    for page in range(PAGES_PER_MONTH):
        r = await client.call("search_ledger_postings", {
            "dateFrom": start.isoformat(), "dateTo": end.isoformat(),
            "accountNumberFrom": RECEIVABLES[0], "accountNumberTo": RECEIVABLES[1],
            "count": PAGE, "from": page * PAGE})
        out += r.get("postings") or []
        if not r.get("hasMore"):
            return out, True
    return out, False


def _customer(p: dict) -> str:
    c = p.get("customer")
    return (p.get("customerName") or (c.get("name") if isinstance(c, dict) else "")
            or "").strip()


async def _read(client, today: date) -> dict:
    """Every payment to a customer account in the last year."""
    results = await asyncio.gather(*(_window(client, a, b)
                                     for a, b in _month_windows(today)),
                                   return_exceptions=True)
    payments, complete = [], True
    for r in results:
        if isinstance(r, Exception):
            log.warning("Innbetalingene kunne ikke leses: %s", r)
            complete = False
            continue
        postings, whole = r
        complete = complete and whole
        for p in postings:
            amount = float(p.get("amount") or 0)
            name = _customer(p)
            if amount < 0 and name and p.get("date"):
                payments.append({"customer": name, "date": p["date"], "amount": -amount})
    return {"payments": payments, "complete": complete, "read_on": today.isoformat()}


# Per client: the forecast passes the one it reads everything else through,
# which the tests replace — a module-level client here would have gone to the
# real Tripletex from a test.
_cache: dict = {}


async def payments(client, today: date | None = None) -> dict:
    """A year of payments, read at most once a day."""
    today = today or date.today()
    key = (id(client), today)
    hit = _cache.get(key)
    if hit:
        at, data = hit
        ttl = CACHE_SECONDS if data.get("complete") else DEGRADED_SECONDS
        if time.time() - at < ttl:
            return data
    data = await _read(client, today)
    _cache.clear()
    _cache[key] = (time.time(), data)
    return data


def _weighted_median(pairs: list[tuple[float, float]]) -> float:
    pairs = sorted(pairs)
    half, running = sum(w for _, w in pairs) / 2, 0.0
    for value, weight in pairs:
        running += weight
        if running >= half:
            return value
    return pairs[-1][0]


def _matched(invoices: list, paid: list) -> list[tuple[int, float]]:
    """(days late, amount) for each of one customer's fully paid invoices.

    `invoices` are the customer's rows, `paid` the customer's payments. The
    payments of the year can reach back to invoices from before it, so they
    are taken from the latest back until they cover what the listed invoices
    have had paid, and the earlier ones are left out; then laid against the
    invoices oldest first.
    """
    rows = []
    for inv in invoices:
        try:
            due = date.fromisoformat(inv["dueDate"])
        except (ValueError, TypeError, KeyError):
            continue
        amount = float(inv.get("amount") or inv.get("amountCurrency") or 0)
        if amount <= 0:
            continue
        outstanding = max(0.0, float(inv.get("amountOutstanding") or 0))
        rows.append([due, amount, min(amount, amount - outstanding), outstanding < 0.5])
    rows.sort(key=lambda r: r[0])
    needed = sum(r[2] for r in rows)
    if needed <= 0:
        return []
    kept, covered = [], 0.0
    for p in sorted(paid, key=lambda p: p["date"], reverse=True):
        if covered >= needed - 0.5:
            break
        kept.append(p)
        covered += p["amount"]
    kept.sort(key=lambda p: p["date"])

    out, i, left = [], 0, None
    for p in kept:
        money = p["amount"]
        while money > 0.5 and i < len(rows):
            due, amount, to_pay, whole = rows[i]
            if left is None:
                left = to_pay
            take = min(money, left)
            money -= take
            left -= take
            if left <= 0.5:
                if whole:
                    days = (date.fromisoformat(p["date"]) - due).days
                    out.append((max(0, days), amount))
                i, left = i + 1, None
    return out


def habits(invoices: list, paid: dict | None) -> dict:
    """Each customer's lateness, and the company's, from the invoice rows
    the forecast already read and the payments above.

    {"customers": {name: {"days", "invoices"}}, "company": days or None,
     "measured": bool, "complete": bool}
    """
    if not paid or not paid.get("payments"):
        return {"customers": {}, "company": None, "measured": False,
                "complete": bool(paid and paid.get("complete"))}
    by_inv: dict = {}
    for row in invoices:
        name = (row.get("customerName") or "").strip()
        if name:
            by_inv.setdefault(name, []).append(row)
    by_pay: dict = {}
    for p in paid["payments"]:
        by_pay.setdefault(p["customer"], []).append(p)

    customers, everything = {}, []
    for name, rows in by_inv.items():
        matched = _matched(rows, by_pay.get(name, []))
        everything += matched
        if len(matched) >= MIN_CUSTOMER:
            customers[name] = {"days": min(MAX_DAYS, int(_weighted_median(matched))),
                               "invoices": len(matched)}
    company = (min(MAX_DAYS, int(_weighted_median(everything)))
               if len(everything) >= MIN_COMPANY else None)
    return {"customers": customers, "company": company,
            "measured": company is not None, "complete": bool(paid.get("complete"))}


def lag(h: dict | None, customer: str, default: int) -> int:
    """The days after due this customer's money is expected."""
    if not h:
        return default
    own = (h.get("customers") or {}).get(customer)
    if own:
        return own["days"]
    return h["company"] if h.get("company") is not None else default


def own(h: dict | None, customer: str) -> int | None:
    """The customer's own lateness, if measured; never the company's."""
    c = ((h or {}).get("customers") or {}).get(customer)
    return c["days"] if c else None
