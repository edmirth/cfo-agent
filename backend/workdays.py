"""Norwegian working days, and which way a date moves when it lands off one.

Two different rules live here, and using the wrong one moves money the wrong
way in the forecast.

**Statutory deadlines roll forward.** VAT, employer's contribution and
withholding tax falling on a Saturday, Sunday or public holiday are due the
next working day. Paying on the literal date places the money leaving the
account earlier than it does, which makes the tight week look tighter and — as
happened here with arbeidsgiveravgift dated Sunday 15 November — moves the
reported low point onto the wrong week.

**Wages roll backward.** A pay day that lands on a weekend is not paid late; it
is paid on the last working day before it, because staff should not be short
over a weekend. Rolling wages forward with everything else would quietly flatter
the forecast, showing money still in the account on days it has already gone.

Christmas Eve and New Year's Eve are deliberately not holidays here. They are
ordinary working days in Norwegian law even though banks keep short hours, and
Skatteetaten does not shift a deadline for them.
"""
from datetime import date, timedelta

FIXED = ((1, 1), (5, 1), (5, 17), (12, 25), (12, 26))


def easter(year: int) -> date:
    """Easter Sunday, anonymous Gregorian algorithm. Everything else hangs
    off it: Maundy Thursday, Good Friday, Easter Monday, Ascension, Whitsun."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month = (h + ll - 7 * m + 114) // 31
    day = (h + ll - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def holidays(year: int) -> frozenset[date]:
    """Every Norwegian public holiday in one year."""
    e = easter(year)
    return frozenset(
        [date(year, m, d) for m, d in FIXED]
        + [e + timedelta(days=n) for n in (-3, -2, 0, 1, 39, 49, 50)])


def is_working_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def forward(d: date) -> date:
    """The first working day on or after `d` — a statutory deadline."""
    while not is_working_day(d):
        d += timedelta(days=1)
    return d


def backward(d: date) -> date:
    """The last working day on or before `d` — a pay day."""
    while not is_working_day(d):
        d -= timedelta(days=1)
    return d
