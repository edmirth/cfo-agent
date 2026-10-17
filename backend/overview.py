"""Nøkkeltall til forsiden, hentet direkte fra Tripletex uten å bruke modellen.

Hver figur er regnet ut her, ikke lest fra Tripletex' egne nøkkeltall — deres
Overskuddsgrad og Egenkapitalrentabilitet kommer tilbake med feil fortegn for et
selskap som går i pluss.
"""
import asyncio
import logging
from datetime import date

import freshness
import memory
from mcp_client import mcp
import saldobalanse

log = logging.getLogger("cfo.overview")

CACHE_SECONDS = 600

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


def account_number(row: dict) -> int | None:
    """The account number a saldobalanse row belongs to, or None for a heading."""
    head = (row.get("path") or "").split(" ", 1)[0]
    return int(head) if head.isdigit() else None


def _side_total(rows: list[dict], lo: int, hi: int) -> float | None:
    """Closing balances summed across an account range, None if the range is
    absent entirely. Absent and zero are different: one is a company with no
    such accounts, the other is a company whose accounts net out."""
    vals = [float(r["cells"][-1]) for r in rows
            if (n := account_number(r)) is not None and lo <= n <= hi
            and (r.get("cells") or []) and isinstance(r["cells"][-1], (int, float))]
    return sum(vals) if vals else None


def equity_ratio(rows: list[dict]) -> float | None:
    """Equity as a share of assets, from the trial balance.

    Equity is the residual — assets less debt — so this year's result is in it
    even before it has been posted to 2050. Tripletex's own Egenkapitalandel row
    reports 0 for a company with roughly 30 % equity, which is why it is computed
    here rather than read.

    Debt accounts absent is not missing data: it is a company that owes nothing,
    and its equity ratio is 100 %, not unknown. Assets absent is missing data,
    because every going concern has some.
    """
    assets = _side_total(rows, 1000, 1999)
    if not assets:
        return None
    debts = _side_total(rows, 2100, 2999) or 0.0    # kredit, altså negativ
    return _pct(assets + debts, assets)


def _pct(part, whole):
    if part is None or not whole:
        return None
    v = part / whole * 100
    # One decimal is right for a wage share of 83.8. It is wrong for a margin of
    # 0.043, which reads as 0.0 — the one figure where thin and nil differ.
    return round(v, 1) if abs(v) >= 1 else round(v, 2)


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
        saldobalanse.monthly(mcp, start, end),
        return_exceptions=True,
    )
    failed = []
    for name, r in (("Resultatrapport", pnl), ("Nøkkeltall", ratios),
                    ("Kundereskontro", ar), ("Saldobalanse", monthly)):
        if isinstance(r, Exception):
            log.warning("%s feilet: %s", name, r)
            failed.append(name)
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

    # Månedsserier til forsidekortene, og siste saldo for bank og kundefordringer.
    m = _rows(monthly)
    cols = [c.get("name") for c in monthly.get("table", {}).get("columns", [])]
    months = [(i, SHORT[MONTHS.index(c)]) for i, c in enumerate(cols) if c in MONTHS]

    # Siste månedskolonne og «Utgående saldo» er ikke alltid like — closing tar
    # med etterposteringer som ikke har landet i månedskolonnen ennå. Resultat-
    # rapporten regner med closing, så serien må ende der, ellers summerer
    # månedene til noe annet enn tallet vi viser stort på samme kort. Avviket
    # havner i inneværende måned, som er den som ikke er ferdig uansett.
    closing = next((i for i, c in enumerate(cols) if c == "Utgående saldo"), None)
    if closing is not None and months:
        months[-1] = (closing, months[-1][1])

    def _account_no(row: dict) -> int | None:
        head = (row.get("path") or "").split(" ", 1)[0]
        return int(head) if head.isdigit() else None

    def _in_range(lo: int, hi: int) -> list[dict]:
        return [r for r in m
                if (n := _account_no(r)) is not None and lo <= n <= hi]

    def _cumulative(rows: list[dict], sign: int) -> list[float | None]:
        """Akkumulert saldo per måned, summert konto for konto.

        Saldobalansen lar cella stå tom når kontoen ikke har bevegelse den
        måneden. Tomt betyr uendret, ikke null — så hver konto viderefører sin
        egen forrige saldo før de summeres. Summeres kolonnen rått i stedet,
        forsvinner hver konto som har ligget stille, og driftsresultatet bommer
        med akkurat de kontoene."""
        carried: list[float | None] = [None] * len(rows)
        out: list[float | None] = []
        started = False
        for i, _ in months:
            for j, r in enumerate(rows):
                cells = r.get("cells") or []
                cell = cells[i] if i < len(cells) else None
                if isinstance(cell, (int, float)):
                    carried[j] = float(cell)
                    started = True
            out.append(sign * sum(c for c in carried if c is not None)
                       if started else None)
        return out

    def _balance(rows: list[dict], sign: int = 1) -> list[float | None]:
        """Saldoen ved utgangen av hver måned, slik den står i rapporten."""
        if not rows:
            return [None] * len(months)
        return [None if v is None else round(v, 2)
                for v in _cumulative(rows, sign)]

    def _flow(rows: list[dict], sign: int = 1) -> list[float | None]:
        """Bevegelsen i måneden. Saldobalansen er akkumulert, så hver måned er
        differansen mot forrige — og inntekter ligger i kredit, altså negative."""
        if not rows:
            return [None] * len(months)
        out: list[float | None] = []
        prev = 0.0
        for v in _cumulative(rows, sign):
            if v is None:
                out.append(None)
                continue
            out.append(round(v - prev, 2))
            prev = v
        return out

    # Each cost account month by month, for the morning watch's unusual-cost
    # check (card 12). From the report already fetched: no extra call.
    cost_accounts = {
        "months": [MONTHS.index(cols[i]) + 1 if cols[i] in MONTHS else None
                   for i, _ in months],
        "accounts": [{"account": account_number(r),
                      "name": (r.get("path") or "").split(" ", 1)[-1].strip(),
                      "flows": _flow([r])}
                     for r in _in_range(4000, 7999)]}
    # The last column may be "Utgående saldo" standing in for the current
    # month; it is still that month.
    if cost_accounts["months"] and cost_accounts["months"][-1] is None:
        cost_accounts["months"][-1] = today.month

    bank_rows = [r for r in m if (r.get("path") or "").startswith("1920")]
    ar_row_1500 = [r for r in m if (r.get("path") or "").startswith("1500")]

    revenue_m = _flow(_in_range(3000, 3999), -1)
    wages_m = _flow(_in_range(5000, 5999))
    # Driftsresultat = inntekter minus driftskostnader. Kontoklasse 3 til 7 er
    # akkurat driften; 8 er finans og skatt og holdes utenfor.
    result_m = _flow(_in_range(3000, 7999), -1)
    bank_m = _balance(bank_rows)

    series = [{"month": name,
               "revenue": revenue_m[j], "wages": wages_m[j],
               "result": result_m[j], "bank": bank_m[j]}
              for j, (_, name) in enumerate(months)]

    def _last(vals: list[float | None]) -> float | None:
        return next((v for v in reversed(vals) if v is not None), None)

    cash = _last(bank_m)
    receivables = _last(_balance(ar_row_1500)) if ar_row_1500 else None

    # Største enkeltkunde blant fordringene — konsentrasjonsrisikoen.
    ar_rows = sorted(
        ((r.get("path", "").split(" (")[0], float((r.get("cells") or [0, 0])[1]))
         for r in _rows(ar)
         if len(r.get("cells") or []) > 1 and isinstance(r["cells"][1], (int, float))),
        key=lambda kv: -kv[1])
    ar_ledger_total = sum(v for _, v in ar_rows if v > 0) or None
    top_customer = ar_rows[0] if ar_rows else None

    rr = _rows(ratios)
    # Likviditetsgrad 1 er etterregnet mot saldobalansen og stemmer, så den
    # leses. Egenkapitalandelen gjør det ikke: Nøkkeltallsrapporten melder 0 for
    # et selskap som har rundt 30 % egenkapital, så den regnes ut her i stedet.
    # Egenkapital er residualen — eiendeler minus gjeld — og da er årets
    # resultat med selv om det ennå ikke er ført mot 2050.
    liquidity = _cell(rr, "Likviditetsgrad 1")

    equity = equity_ratio(m)

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
            "egenkapitalandel_pct": equity,
        },
        # Named, not a bare flag: whoever reads this should be able to say
        # which figures are missing, and the cache uses it to retry sooner.
        "partial": failed or None,
        "monthly": series,
        "cost_accounts": cost_accounts,
        "top_debtor": ({"name": top_customer[0], "amount": top_customer[1],
                        # samme nevner som tallet vi viser, ellers spriker de
                        "share_pct": _pct(top_customer[1],
                                          receivables or ar_ledger_total)}
                       if top_customer and (receivables or ar_ledger_total) else None),
        "flags": {"ubokfort_skatt": unbooked_tax},
    }


async def _build_and_remember() -> dict:
    data = await build()
    # Trend memory, written without a model in the loop. Same-day calls
    # overwrite, so the ten-minute refresh leaves one row per day. Inside the
    # single-flight build rather than after it: two concurrent cold callers used
    # to write this twice for the same day.
    # Never from a partial build. The cache forgets a bad figure in 45 seconds;
    # the trend store keeps it for good, and a day recorded with null revenue
    # because a report timed out is a hole in the history that nothing later
    # fills in.
    if data.get("partial"):
        log.warning("Hopper over dagens snapshot — mangler %s",
                    ", ".join(data["partial"]))
    else:
        try:
            memory.snapshot(data["kpis"], on=data["generated_at"])
        except Exception:  # noqa: BLE001 — the dashboard must render regardless
            log.exception("Kunne ikke lagre dagens nøkkeltall")
    return data


_flight = freshness.Cached(_build_and_remember, CACHE_SECONDS,
                           degraded=lambda d: bool(d.get("partial")))


async def cached() -> dict:
    return await _flight.get()
