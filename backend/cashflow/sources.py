"""Everything the forecast reads from Tripletex. The only module that awaits
the ledger; `mcp` here is the one connection, and tests replace it here."""
import logging
import asyncio
from datetime import date

from mcp_client import mcp

from .common import AGA_ACCRUED, MONTH_NAMES, PAID_FROM, PAYROLL_MONTHS, VAT_ACCRUED, WAGE_ACCOUNTS, _add_months, _kr, _month_bounds
from .payroll import payroll_paid
import bankcat
import commitments
import payment_habits
import saldobalanse
from preflight import _rows
from .common import PAY_LAG_DAYS
from .ledger import _seasons
from .models import Sources

log = logging.getLogger("cfo.cashflow")

# The fewest closed months a run-rate is allowed to rest on. Before April this
# year has fewer, and the gap is made up from the end of last year.
MIN_CLOSED_MONTHS = 3


AR_MONTHS_BACK = 12          # how far back to look for still-open invoices
INVOICE_PAGE = 100           # the most one invoice search returns
INVOICE_PAGES = 20           # pages read in one month before it is called cut off


async def _month_rows(tool: str, start: date, end: date) -> dict:
    """One month of an invoice register, page by page, in the search's own
    answer shape: `rows`, and `complete` with its `degradedNote`.

    A month that came back full used to be warned about and left at that. A
    company sending 150 invoices at month end had a third of them missing
    from the forecast, and the money for them in no line at all — the 1500
    residual only reaches the expected line, slowly. So the month is asked
    again from where the last page ended, until a page comes back short.

    `truncated` says the pages ran out first, or the search handed back the
    same page twice, which is what an offset it does not honour looks like.
    A page after the first that fails keeps what was read and marks the month
    incomplete; a first page that fails fails the month, as before.
    """
    rows, first, complete, note = [], None, True, None
    for page in range(INVOICE_PAGES):
        args = {"invoiceDateFrom": start.isoformat(),
                "invoiceDateTo": end.isoformat(), "count": INVOICE_PAGE}
        if page:
            args["from"] = page * INVOICE_PAGE
        try:
            r = await mcp.call(tool, args)
        except Exception as exc:  # noqa: BLE001
            if not page:
                raise
            return {"rows": rows, "complete": False,
                    "degradedNote": f"side {page + 1} svarte ikke ({exc})"}
        got = r.get("rows") or []
        if r.get("complete") is False:
            complete, note = False, r.get("degradedNote") or note
        if page and got and got[0] == first:
            return {"rows": rows, "complete": complete, "degradedNote": note,
                    "truncated": True}
        first = got[0] if got else None
        rows += got
        if len(got) < INVOICE_PAGE:
            return {"rows": rows, "complete": complete, "degradedNote": note}
    return {"rows": rows, "complete": complete, "degradedNote": note,
            "truncated": True}


async def _open_invoices(today: date, tool: str, what: str, id_key: str,
                         outstanding_key: str, name_key: str,
                         issued: dict | None = None,
                         in_kroner: bool = False,
                         history: list | None = None) -> tuple[list, list, bool]:
    """Open invoices with their due dates, the warnings, and whether every
    window answered — an empty list from failed calls is not an empty book.

    The search caps at INVOICE_PAGE rows per call, so the range is walked a
    month at a time, and a month with more than that is read page by page
    (`_month_rows`). Only a month that is still cut off after that is
    reported as possibly truncated.

    Both registers answer under `rows`. They did not always appear to: the
    supplier call read `invoices`, a key the response has never carried, so
    `r.get(...) or []` was empty every time and every supplier bill was dropped
    before it reached the forecast — silently, because the call itself
    succeeded. `what` names the register in the warnings, since two sources
    sharing one sentence left nobody able to tell which one was short.

    `issued`, when given, gets `this_month`: everything invoiced this month,
    paid or not, from the same rows. The open list leaves out what is paid,
    and what was invoiced and paid this month is invoicing all the same. It
    also gets `truncated` when a month could not be read to the end, which is
    the one known reason the ledger can hold more receivables than the list
    shows.

    `in_kroner` says the outstanding amount is already in kroner whatever
    the invoice's currency, as the customer register's `amountOutstanding`
    is. The supplier register's `outstandingAmount` is in the invoice's own.

    `history`, when given, gets every row, paid ones too: the fixed bills are
    read off how a supplier has billed, and most of those bills are paid.
    """
    results = await asyncio.gather(
        *(_month_rows(tool, *_month_bounds(today, back))
          for back in range(AR_MONTHS_BACK)),
        return_exceptions=True)

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
        if back == 0 and issued is not None:
            # In kroner: `amount` is the base currency, 0 for an invoice in
            # another currency not yet converted, which then counts at face.
            # A cancelled invoice and its credit note are both rows, and net
            # to nothing together.
            issued["this_month"] = sum(
                float(row.get("amount") or row.get("amountCurrency") or 0)
                for row in rows)
        if r.get("truncated"):
            warnings.append(f"Det er minst {len(rows)} {what.lower()} i {when}; "
                            f"lista kan være avkortet.")
            if issued is not None:
                issued["truncated"] = True
        for row in rows:
            # A row with no id is not a duplicate of the last row with no id.
            # Putting None in `seen` made the first one swallow every one after.
            key = row.get(id_key)
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            if history is not None:
                history.append(row)
            # A credited invoice and its credit note both report the balance
            # left between them; the credit note carries it. Counted on both,
            # a 5 200 kr credit came to 10 400.
            if row.get("isCredited"):
                continue
            amount = row.get(outstanding_key) or 0
            if not amount or not row.get("dueDate"):
                continue
            # outstandingAmount is in the *invoice's* currency, not NOK. There
            # is no rate here and inventing one is not this module's job, so
            # the money stays in the forecast at face value — dropping it
            # would understate what leaves — and the shortfall is declared
            # instead of quietly standing in for kroner.
            currency = (row.get("currency") or "NOK").upper()
            if currency != "NOK" and not in_kroner:
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
PAYROLL_PAGES = 50


async def _postings_in(low: int, high: int, start: date, end: date) -> list[dict]:
    rows: list[dict] = []
    for page in range(PAYROLL_PAGES):
        r = await mcp.call("search_ledger_postings", {
            "dateFrom": start.isoformat(), "dateTo": end.isoformat(),
            "accountNumberFrom": low, "accountNumberTo": high,
            "count": 100, "from": page * 100})
        rows += r.get("postings") or []
        if not r.get("hasMore"):
            return rows
    raise RuntimeError(f"mer enn {PAYROLL_PAGES * 100} posteringer på {low}–{high}")


async def _tax_postings(today: date) -> list[dict]:
    """This month's postings on the VAT and AGA accounts, settlement included."""
    start = date(today.year, today.month, 1)
    return await _postings_in(VAT_ACCRUED[0], AGA_ACCRUED[1], start,
                              date(*_add_months(today.year, today.month, 1), 1))


# Closed months do not change by the hour: read once a day, not on every
# rebuild of the forecast, which reads six months of bank postings each time.
_payroll_cache: dict[str, dict | None] = {}


async def _payroll_measured(today: date) -> dict | None:
    """`payroll_paid` over the last PAYROLL_MONTHS closed months, kept for the
    day; None with too few months; {"unread": why} when the postings could not
    be read, which is not kept, so the next build asks again."""
    key = today.isoformat()
    if key in _payroll_cache:
        return _payroll_cache[key]
    start = date(*_add_months(today.year, today.month, -PAYROLL_MONTHS), 1)
    end = date(today.year, today.month, 1)
    ranges = [WAGE_ACCOUNTS, *PAID_FROM]
    try:
        parts = await asyncio.gather(*(_postings_in(lo, hi, start, end) for lo, hi in ranges))
    except Exception as exc:  # noqa: BLE001 — the accounts are the fallback
        log.warning("Cashflow: lønnsbilagene kunne ikke leses: %s", exc)
        return {"unread": str(exc)}
    _payroll_cache.clear()
    _payroll_cache[key] = payroll_paid([p for part in parts for p in part], today)
    return _payroll_cache[key]


async def _read(today: date) -> Sources:
    """Every source at once. The trial balance and the commitments are the
    floor of the forecast, and without either there is none; any other read
    that fails is carried as what it is, and the stage that needs it says so."""
    last_year = today.year - 1

    # Last year always: early in the year for the months this year lacks,
    # and every month for the seasonal pattern.
    async def _prior():
        return await saldobalanse.monthly(mcp, f"{last_year}-01-01", f"{last_year}-12-31")

    issued: dict = {}
    supplier_history: list = []
    customer_history: list = []
    balance, com, ar, ap, prior, paid, wages_paid, tax_posts = await asyncio.gather(
        saldobalanse.monthly(mcp, f"{today.year}-01-01", today.isoformat()),
        commitments.cached(),
        _open_invoices(today, "search_invoices", "Kundefakturaer", "id",
                       "amountOutstanding", "customerName", issued,
                       # Kroner already, for a foreign-currency invoice too.
                       in_kroner=True, history=customer_history),
        # Supplier rows are keyed by voucherId, not id.
        _open_invoices(today, "search_supplier_invoices", "Leverandørfakturaer",
                       "voucherId", "outstandingAmount", "supplierName",
                       history=supplier_history),
        _prior(),
        payment_habits.payments(mcp, today),
        _payroll_measured(today),
        _tax_postings(today),
        return_exceptions=True,
    )
    if isinstance(balance, Exception):
        raise RuntimeError(f"Kunne ikke lese saldobalansen: {balance}")
    if isinstance(com, Exception):
        raise RuntimeError(f"Kunne ikke lese forpliktelsene: {com}")
    ar_open, ar_warn, ar_complete = ([], ["Kundefakturaer kunne ikke hentes."], False) \
        if isinstance(ar, Exception) else ar
    ap_open, ap_warn, ap_complete = ([], ["Leverandørfakturaer kunne ikke hentes."], False) \
        if isinstance(ap, Exception) else ap
    # Without this month's tax postings nothing is taken off the movement on
    # 2770 and 2700-2739, as before card 68.
    if isinstance(tax_posts, Exception):
        log.warning("Cashflow: månedens mva- og aga-posteringer kunne ikke leses: %s",
                    tax_posts)
        tax_posts = []
    return Sources(
        rows=_rows(balance),
        columns=[c.get("name") for c in balance.get("table", {}).get("columns", [])],
        com=com, ar_open=ar_open, ar_complete=ar_complete,
        ap_open=ap_open, ap_complete=ap_complete, prior=prior, paid=paid,
        wages_paid=wages_paid, tax_posts=tax_posts, issued=issued,
        supplier_history=supplier_history, customer_history=customer_history,
        warnings=ar_warn + ap_warn)


def _last_year(src: Sources, today: date, warnings: list[str]):
    """Last year's trial balance: its final months in front of this year's
    while this year has too few closed ones, and its pattern as the season.
    Returns (prior_months, history, season)."""
    # The current month is not closed, so January has none of this year's.
    keep = max(0, MIN_CLOSED_MONTHS - (today.month - 1))
    last_year = today.year - 1
    prior = src.prior
    read = isinstance(prior, dict) and "table" in prior
    prior_months = None
    if keep:
        if read:
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
    history = None
    if read:
        history = (_rows(prior),
                   [c.get("name") for c in prior["table"].get("columns", [])])
    return prior_months, history, _seasons(history)


async def _habits(src: Sources, today: date, warnings: list[str]):
    """How late each customer pays, and every bank line with a category.
    Returns (habits, bank_categories)."""
    # How late each customer pays, from a year of payments on 1500. Without
    # it every customer is the old seven days late, and that is said.
    paid = src.paid
    if isinstance(paid, Exception):
        log.warning("Cashflow: innbetalingene kunne ikke leses: %s", paid)
        paid = None
    habits = payment_habits.habits(src.customer_history, paid)
    # Every bank line with a category, once a day (card 63): what actually
    # left the account, for the costs (card 64) and for the owner to see.
    bank_categories = await bankcat.measured(
        mcp, today, {r.get("customerName") or "" for r in src.customer_history})
    if paid is None or not habits["complete"]:
        warnings.append(
            "Innbetalingene på konto 1500 kunne ikke leses helt, så "
            "betalingsvanene er ufullstendige; kunder uten nok historikk er "
            f"regnet med {PAY_LAG_DAYS} dager etter forfall.")
    return habits, bank_categories
