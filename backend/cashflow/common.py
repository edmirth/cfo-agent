"""Small helpers every part of the forecast uses: weeks, months, kroner."""
from collections.abc import Iterator
from datetime import date, timedelta



WEEKS = 13
LATE_SPREAD_WEEKS = 3        # already-overdue invoices land across this many
# How late an overdue invoice is decides how far it is counted on. Up to
# LATE_DAYS is ordinary lateness: in both lines, over the next three weeks.
# Up to DOUBTFUL_DAYS it usually pays, but not reliably and not soon: in the
# expected line only, over SLOW_WEEKS. Beyond that it is not counted on at all
# — money that in practice comes back through debt collection or not at all —
# and is named instead, so it is chased rather than forecast.
LATE_DAYS = 30
DOUBTFUL_DAYS = 90
SLOW_WEEKS = (3, 8)
PAY_LAG_DAYS = 7             # customers pay this late even when not "late"

# The same reading on the other side of the ledger: a customer invoiced in each
# of the last RECURRING_MONTHS closed months is billed every month, whatever
# the amounts did, and is counted at the lowest of those months, because the
# floor is where being wrong costs most.
RECURRING_MONTHS = 3

# The invoice runs (card 60). Money coming in is read off the invoice register,
# customer by customer, not off the revenue in the accounts: what the company
# invoices is what reaches the bank, on each customer's own day and terms.
# Regular: invoiced in RUN_ACTIVE of the last RUN_MONTHS closed months, and in
# every one of the last RECURRING_MONTHS. Usual is the median of the months he
# was invoiced; the committed line takes the lowest of the last three.
RUN_MONTHS = 6
RUN_ACTIVE = 5
# Terms are shown rounded to the ones companies use, so a week's runs merge.
TERM_STEPS = (7, 10, 14, 20, 30, 45, 60, 90)

# The months are not alike. Sales and running costs get a seasonal pattern
# from last year — each month against last year's average, held within
# SEASON_LIMITS and taken at SEASON_WEIGHT, since one year is a thin basis —
# and a level from the last LEVEL_MONTHS closed months with the season taken
# out, which carries the trend without drawing a line into the future.
LEVEL_MONTHS = 6
SEASON_WEIGHT = 0.5

# The running costs that are not fixed bills are spread over the month by
# when this company's variable bills are dated and paid. See _cost_profile.
COST_PERIODS = ((1, 7), (8, 14), (15, 21), (22, 31))
# Above this share of the money out with no category, the bank's costs leave
# too much out, and the accounts carry the forecast as before (card 64).
BANK_UNKNOWN_MAX = 0.10

MONTH_NAMES = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
               "august", "september", "oktober", "november", "desember"]

# Invoicing that has not happened yet brings in gross cash and creates a
# liability on the same krone. The forecast used to take the first and not the
# second: 1 950 013 kr landing in the window with 390 003 kr of VAT inside it
# that never left again, and the inflow landed in the tightest week. Money
# leaves before it arrives — October's VAT falls due 10 December while October's
# invoicing is collected around 22 December — so having neither side overstated
# comfort in exactly the weeks that were already the problem.
MVA_RATE = 0.25
# Every krone that leaves the account has to be in exactly one of these.
# 4000-4999 and 5100-5999 were in none of them: varekjøp, underentreprise,
# pensjon and yrkesskade simply did not exist in the forecast, about
# 116 000 kr a month against a modelled opex of 156 000.
#
# And no krone that never leaves it. A cost booked against a balance sheet
# account rather than the bank is a P&L figure, not a payment: counting it
# took the depreciation on three cars — about 19 000 kr a month in Q1 —
# out of the account every month as if it were a bill.
OPEX_RANGES = [(4000, 4999),      # varekjøp og underentreprise
               (5100, 5199),
               (5300, 5399),      # annen opplysningspliktig godtgjørelse
               (5402, 5999),      # pensjon, yrkesskade, personalkostnad
               (6100, 7799),      # ordinære driftskostnader
               (7900, 7999)]
# The gaps in that list, each on purpose:
# - 5200-5299 fordel i arbeidsforhold: a benefit in kind, taxed through
#   payroll and booked against its own contra account. No money moves.
# - 5400/5401 arbeidsgiveravgift: dated by commitments from its own
#   balance; taking it here as well would pay it twice.
# - 6000-6099 avskrivning og nedskrivning: the cost of an asset already
#   paid for, spread over its life.
# - 7800-7899 tap på fordringer og ved avgang: money that did not come in,
#   or an asset written off. Neither is a payment.


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
PAYROLL_MONTHS = 6
WAGE_ACCOUNTS = (5000, 5099)
PAID_FROM = ((1900, 1949), (2600, 2609), (2910, 2939))   # bank, trekk, net pay


# The month's net movement on 2770 and 2700-2739 is what this month booked
# there only until a term is paid or settled in it. Then the payment is in the
# same figure, usually larger than the accrual, and the month read as nothing
# booked: a run journalised before its pay day was forecast again on top of
# the balance commitments dates, and so was the VAT already invoiced. The
# month's postings find those vouchers; the movement less them is the accrual.
VAT_ACCRUED = (2700, 2739)
AGA_ACCRUED = (2770, 2779)
