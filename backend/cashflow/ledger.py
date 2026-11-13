"""Monthly run rates and balances read off the trial balance."""
import statistics

import saldobalanse
from preflight import _account, _monthly

from .common import LEVEL_MONTHS, OPEX_RANGES, SEASON_WEIGHT, _kr


SEASON_LIMITS = (0.5, 1.5)


def _merged(rows: list, columns: list, ranges) -> list:
    """One monthly series across several account ranges.

    Summed before the outlier filter runs, never after. Filtering each
    range on its own and adding the results lets a quiet month in one range
    be judged against that range's own median, which is not the question —
    the question is what the whole cost base does in a month.
    """
    total: dict = {}
    order: list = []
    for low, high in ranges:
        for m, v in _monthly(rows, columns, low, high):
            if m not in total:
                total[m] = 0.0
                order.append(m)
            total[m] += v
    return [(m, total[m]) for m in order]


def _month_no(label: str) -> int | None:
    """1-12 for a column label, "Okt" or last year's "Okt 2025"."""
    name = label.split(" ")[0]
    return saldobalanse.MONTHS.index(name) + 1 if name in saldobalanse.MONTHS else None


def _seasons(history: tuple | None) -> dict:
    """Each month's season for sales and for running costs, from last year.

    `history` is last year's (rows, columns). A season is that month against
    last year's average, held within SEASON_LIMITS and pulled half way to 1:
    December at 0.82 last year becomes 0.91. None for a series without twelve
    months of something in them — a new company, or a month never posted —
    and the forecast then stays flat, and says so.
    """
    out: dict = {}
    for key, (ranges, flip) in (("revenue", ([(3000, 3999)], -1)),
                                ("opex", (OPEX_RANGES, 1))):
        by = {}
        if history:
            for m, v in _merged(history[0], history[1], ranges):
                if (n := _month_no(m)):
                    by[n] = v * flip
        if len(by) < 12 or any(v <= 0 for v in by.values()):
            out[key] = None
            continue
        mean = sum(by.values()) / 12
        lo, hi = SEASON_LIMITS
        out[key] = {m: round(1 + SEASON_WEIGHT * (min(max(v / mean, lo), hi) - 1), 4)
                    for m, v in by.items()}
    return out


def _run_rates(rows: list, columns: list,
               prior: tuple | None = None, season: dict | None = None,
               history: tuple | None = None) -> tuple[dict, list[str]]:
    """Monthly run-rates that a posting backlog cannot poison.

    Costs in this ledger read 122k, 223k, 114k, then 48k, 14k, 13k. Nothing got
    cheaper — supplier invoices stopped being booked. A trailing average takes
    those months at face value and forecasts a third of the real cost, which is
    the most dangerous direction to be wrong in.

    So: median of the closed months, keep those within half to double of it,
    average those. A month that is a fraction of every other month is not a
    cheap month, it is an unposted one — and it is named, not silently dropped.
    The current month is excluded outright, being part-posted by definition.

    `prior` is `(rows, columns, year, keep)`: last year's monthly report, of
    which the final `keep` months are put in front of this year's. Early in the
    year this year alone has too few closed months — none at all in January,
    where every rate came out 0 and the forecast had no payroll, costs or
    revenue in it.

    `season`, from `_seasons`, and `history`, last year's `(rows, columns,
    year)`: for sales and running costs with a measured season, the rate is
    the level instead — the last LEVEL_MONTHS closed months, last year's
    included where this year has too few, each divided by its own season. A
    year of growth then shows in the level, and the forecast multiplies each
    month's season back on. Without a season, the median of the closed months
    as before.
    """
    notes: list[str] = []
    merged = _merged

    def series_for(ranges) -> list:
        """Last year's tail, if asked for, then this year's months."""
        head = []
        if prior:
            p_rows, p_columns, year, keep = prior
            # Named with the year: "Des" alone would read as this December.
            head = [(f"{m} {year}", v)
                    for m, v in merged(p_rows, p_columns, ranges)][-keep:]
        return head + merged(rows, columns, ranges)

    def rate(ranges, flip, name, key=None):
        idx = (season or {}).get(key) if key else None
        full = series_for(ranges)
        series = [(m, v * flip) for m, v in full][:-1]
        if idx and series:
            past = []
            if history:
                h_rows, h_cols, year = history
                past = [(f"{m} {year}", v * flip)
                        for m, v in merged(h_rows, h_cols, ranges)]
            this = [(m, v * flip) for m, v in merged(rows, columns, ranges)][:-1]
            series = [(m, v / idx.get(_month_no(m) or 0, 1.0))
                      for m, v in (past + this)[-LEVEL_MONTHS:]]
        values = [v for _, v in series]
        if not values:
            # No account in the range at all is a real zero: a company without
            # staff has no payroll. Accounts with only the open month behind
            # them is not, and a zero rate that drops payroll out of the
            # forecast must not pass for a quiet month — so that one is said.
            if not full:
                return 0.0
            notes.append(f"{name} kunne ikke beregnes — det finnes ingen "
                         f"avsluttede måneder å regne snittet på, så den er "
                         f"satt til 0 i prognosen.")
            return 0.0
        mid = statistics.median(values)
        if mid <= 0:
            return sum(values) / len(values)
        kept = [v for _, v in series if 0.5 * mid <= v <= 2 * mid]
        low_months = [m for m, v in series if v < 0.5 * mid]
        high_months = [m for m, v in series if v > 2 * mid]
        # Computed once, and before it is quoted. Quoting it inside the note
        # while `kept` was empty divided by zero and took the whole forecast
        # down with it — reachable whenever credit notes put some months below
        # half the median and others above double it.
        average = (sum(kept) / len(kept)) if kept else mid
        # Format the number on its own: the sentence has commas of its own.
        said = (f"{name} er lagt inn med {_kr(average)} kr i måneden"
                f"{' før sesong' if idx else ''}.")
        # One note per rate, not one per direction. A range with both a quiet
        # month and a loud one used to produce two notes opening on the same
        # sentence, which reads like the figure was stated twice.
        why = []
        if low_months:
            why.append(
                f"{', '.join(low_months)} er holdt utenfor — de ligger langt "
                f"under de andre månedene, og det betyr nesten alltid at bilag "
                f"ikke er bokført, ikke at kostnaden forsvant.")
        if high_months:
            # Said for the same reason the low ones are. A month at several
            # times the median pulls the rate down when it is dropped, and a
            # rate quietly lowered is the dangerous direction to be wrong in.
            why.append(
                f"{', '.join(high_months)} er holdt utenfor — de ligger langt "
                f"over de andre månedene. Det er som regel etterslep som ble "
                f"bokført på én gang, eller noe som bare skjedde denne ene "
                f"gangen, men sjekk det før du stoler på snittet.")
        if why:
            notes.append(" ".join([said] + why))
        return average

    rates = {"revenue": rate([(3000, 3999)], -1, "Omsetning", "revenue"),
             # The full wage cost, accrual and all — what the P&L carries.
             "wages": rate([(5000, 5099)], 1, "Lønn"),
             # What actually leaves on pay day. Feriepenger (5020) is excluded:
             # it accrues monthly but is paid next summer, and commitments
             # already dates it there, so counting it here pays it twice.
             "wages_cash": rate([(5000, 5019), (5030, 5099)], 1,
                                "Lønn som går ut på lønningsdagen"),
             # Not part of opex, and not double counted: commitments dates the
             # 2770 balance for payrolls already reported, this rates the ones
             # still to come. 5401 stays out, being the feriepenger's own.
             "aga": rate([(5400, 5400)], 1, "Arbeidsgiveravgift"),
             "opex": rate(OPEX_RANGES, 1, "Driftskostnader", "opex")}
    return rates, notes


def _closing_range(rows: list, low: int, high: int) -> float:
    """Closing balance across an account range, from the last numeric cell."""
    total = 0.0
    for r in rows:
        n = _account(r)
        if n is None or not (low <= n <= high):
            continue
        cells = [c for c in (r.get("cells") or []) if isinstance(c, (int, float))]
        if cells:
            total += float(cells[-1])
    return total


def _closing_or_none(rows: list, low: int, high: int) -> float | None:
    """`_closing_range`, but None when the range is not in the ledger at all.

    The distinction decides whether a reconciliation runs. A company that
    keeps no 2400 is not a company that owes nothing, and a warning built on
    an invented zero sends someone looking for a gap that is not there.
    """
    if not any((n := _account(r)) is not None and low <= n <= high for r in rows):
        return None
    return _closing_range(rows, low, high)
