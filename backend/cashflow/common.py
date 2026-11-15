"""Small helpers every part of the forecast uses: weeks, months, kroner."""
from collections.abc import Iterator
from datetime import date, timedelta

WEEKS = 13
# Terms are shown rounded to the ones companies use, so a week's runs merge.
TERM_STEPS = (7, 10, 14, 20, 30, 45, 60, 90)

MONTH_NAMES = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
               "august", "september", "oktober", "november", "desember"]



def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _month_bounds(anchor: date, back: int) -> tuple[date, date]:
    """First day of the month, and the first day of the next — end EXCLUSIVE.

    search_invoices treats invoiceDateTo as exclusive. Passing the last day of
    the month therefore dropped every invoice dated on it, and this company
    invoices monthly at month end, so most of its receivables were invisible:
    1 215 575 kr of open invoices against 2 539 600 kr on account 1500, and the
    missing half was spread over three weeks as an unexplained residual.
    """
    year, month = anchor.year, anchor.month - back
    while month < 1:
        month += 12
        year -= 1
    first = date(year, month, 1)
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return first, nxt


def _kr(v) -> str:
    if v is None:
        return "—"
    return f"{round(v):,}".replace(",", " ")


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    i = year * 12 + (month - 1) + n
    return i // 12, i % 12 + 1


def _next_month(d: date) -> date:
    """The first day of the month after the one `d` is in."""
    return date(*_add_months(d.year, d.month, 1), 1)


def _months_until(year: int, month: int, horizon: date) -> Iterator[tuple[int, int]]:
    """(year, month) from the one given, every month that starts before `horizon`."""
    while date(year, month, 1) < horizon:
        yield year, month
        year, month = _add_months(year, month, 1)


def _iso(value) -> date | None:
    """A date from an ISO string, None for anything that is not one: missing,
    empty, or not a date. The registers and commitments leave dates out."""
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _weighted_median(pairs: list[tuple[float, float]]) -> float:
    """The value at which half the weight is reached. (value, weight) pairs."""
    pairs = sorted(pairs)
    half, running = sum(w for _, w in pairs) / 2, 0.0
    for value, weight in pairs:
        running += weight
        if running >= half:
            return value
    return pairs[-1][0]


def _term_step(days: int) -> int:
    """The usual term nearest a measured one, for the label only."""
    return min(TERM_STEPS, key=lambda t: abs(t - days))


# What a pay day costs, read off the payroll vouchers rather than the wage
# accounts. The wage accounts carry accruals and holiday pay as they are
# earned; the bank sees net pay and the withheld tax, on the day. At the first
# customer the accounts said about a fifth more per pay day than ever left the
# bank, and a periodisation booked to 5000 one August month said more still.


# The month's net movement on 2770 and 2700-2739 is what this month booked
# there only until a term is paid or settled in it. Then the payment is in the
# same figure, usually larger than the accrual, and the month read as nothing
# booked: a run journalised before its pay day was forecast again on top of
# the balance commitments dates, and so was the VAT already invoiced. The
# month's postings find those vouchers; the movement less them is the accrual.
