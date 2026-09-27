"""What business is this, and what should its CEO be looking at?

A wage ratio is the whole game in cleaning and almost meaningless in
wholesale, where the same screen should lead on gross margin and stock turn. A
dashboard that shows every company the same six figures is a spreadsheet with
rounded corners.

So the industry is worked out from the ledger itself — there is no NACE code in
Tripletex — and the KPIs follow from it. Two halves, deliberately separated:

- **The model chooses.** Given evidence from the books it names the industry
  and picks which figures matter, in what order, with the benchmark a company
  of that kind should be judged against. That is a judgement, so it is made
  once, cached, and shown with its reasoning so a human can disagree.
- **The ledger computes.** Every figure it can choose from is in `CATALOGUE`
  below and is calculated here, exactly, from Tripletex. The model picks from
  a menu; it never invents a number, and it cannot pick a KPI this company
  has no data for.

That split is the point. Letting the model choose *and* compute would produce a
dashboard that is wrong in a way nobody can see.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import date
from collections.abc import Callable

from anthropic import AsyncAnthropic

import calc
import commitments
import config
from mcp_client import mcp

log = logging.getLogger("cfo.industry")

PROFILE_STORE = config.ROOT / "state" / "profile.json"
VALUES_CACHE_SECONDS = 600
_values_cache: dict = {}

client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)


@dataclass(frozen=True)
class Kpi:
    id: str
    label: str            # what it is called on screen
    plain: str            # what it means, for someone who does not read accounts
    unit: str             # "kr" | "%" | "x" | "dager"
    better: str           # "high" | "low" — which direction is good
    compute: Callable     # (ctx) -> float | None


def _m(name: str, **inputs):
    """One definition per figure: the dashboard computes through calc.py
    rather than keeping a second implementation of the same formula. The
    duplicate that used to live here hardcoded its own VAT rate."""
    try:
        return calc.metric(name, inputs)["value"]
    except calc.CalcError:
        return None


def _pct(part, whole):
    if part is None or not whole:
        return None
    return round(part / whole * 100, 1)


def _div(a, b):
    if a is None or not b:
        return None
    return a / b


CATALOGUE: list[Kpi] = [
    Kpi("lonnsandel", "Lønnsandel",
        "av hver hundrelapp dere fakturerer, hvor mange kroner går til lønn",
        "%", "low", lambda c: _m("wage_ratio", wages=c["wages"], revenue=c["revenue"])),
    Kpi("driftsmargin", "Driftsmargin",
        "hvor mye som blir igjen av hver hundrelapp etter alle kostnader",
        "%", "high", lambda c: _m("margin", result=c["operating"], revenue=c["revenue"])),
    Kpi("omsetning_per_ansatt", "Omsetning per ansatt",
        "hvor mye hver ansatt drar inn i året", "kr", "high",
        lambda c: _m("per_head", value=c["revenue_annualised"], headcount=c["employees"])),
    Kpi("lonn_per_ansatt", "Lønnskostnad per ansatt",
        "hva en ansatt koster i året, alt inkludert", "kr", "low",
        lambda c: _m("per_head", value=c["wages_annualised"], headcount=c["employees"])),
    Kpi("resultat_per_ansatt", "Resultat per ansatt",
        "hvor mye hver ansatt sitter igjen med til selskapet", "kr", "high",
        lambda c: _m("per_head", value=c["operating_annualised"], headcount=c["employees"])),
    Kpi("vekst", "Vekst mot i fjor",
        "om dere selger mer eller mindre enn på samme tid i fjor", "%", "high",
        lambda c: _m("change", now=c["revenue"], before=c["revenue_prev"])),
    Kpi("varekostandel", "Varekostandel",
        "hvor mye av omsetningen som går til varer dere kjøper inn", "%", "low",
        lambda c: _pct(c["materials"], c["revenue"])),
    Kpi("bruttomargin", "Bruttomargin",
        "hva som er igjen etter varekjøp, før lønn og andre kostnader",
        "%", "high",
        lambda c: _pct((c["revenue"] or 0) - (c["materials"] or 0), c["revenue"])),
    Kpi("andre_kostnader", "Andre driftskostnader",
        "alt annet enn lønn og varer, som andel av omsetningen", "%", "low",
        lambda c: _pct(c["opex"], c["revenue"])),
    Kpi("betalingstid", "Betalingstid",
        "hvor mange dager kundene bruker på å betale", "dager", "low",
        lambda c: _m("dso", receivables=c["ar"], revenue=c["revenue"],
                     days=c["days_elapsed"])),
    Kpi("storste_kunde", "Største kunde",
        "hvor stor del av omsetningen som kommer fra én kunde", "%", "low",
        lambda c: c.get("top_customer_share")),
    Kpi("topp_tre", "Tre største kunder",
        "hvor mye dere er avhengige av de tre største", "%", "low",
        lambda c: c.get("top3_share")),
    Kpi("frie_penger", "Frie penger",
        "hva som står igjen på konto når alt som er lovet bort er trukket fra",
        "kr", "high", lambda c: c.get("free_cash")),
    Kpi("kontantdager", "Penger til å drive for",
        "hvor mange dager dere kan drive videre på det som står på konto",
        "dager", "high",
        lambda c: _div(c.get("free_cash"), _div(
            (c["wages"] or 0) + (c["opex"] or 0) + (c["materials"] or 0),
            c["days_elapsed"]))),
    Kpi("likviditetsgrad", "Likviditetsgrad",
        "om dere har nok omløpsmidler til å dekke det som forfaller nærmeste år",
        "x", "high", lambda c: c.get("liquidity")),
    Kpi("egenkapitalandel", "Egenkapitalandel",
        "hvor stor del av selskapet som er deres eget, ikke lånt", "%", "high",
        lambda c: c.get("equity_ratio")),
]

BY_ID = {k.id: k for k in CATALOGUE}


# ---------------------------------------------------------------- gathering

def _rows(report) -> list[dict]:
    if not isinstance(report, dict):
        return []
    return report.get("table", {}).get("rows", []) or []


def _at(rows: list[dict], path: str, idx: int = 0):
    for r in rows:
        if r.get("path") == path:
            cells = r.get("cells") or []
            if idx < len(cells) and isinstance(cells[idx], (int, float)):
                return float(cells[idx])
    return None


def _leaves(rows: list[dict], prefix: str, limit: int = 25) -> list[str]:
    """Account names under a branch — the strongest signal of what a company
    actually does. A ledger with 'Leie av gulvvaskmaskin' is not a law firm."""
    out = []
    for r in rows:
        path = r.get("path") or ""
        if path.startswith(prefix) and r.get("leaf"):
            out.append(path.rsplit(" > ", 1)[-1])
        if len(out) >= limit:
            break
    return out


async def _safe(coro, label: str):
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        log.warning("Industry: %s feilet: %s", label, exc)
        return None


async def _gather(today: date) -> tuple[dict, dict]:
    """Everything the KPIs need, and everything the classifier reads."""
    start = f"{today.year}-01-01"
    prev_start = f"{today.year - 1}-01-01"
    prev_end = today.replace(year=today.year - 1).isoformat()

    pnl, prev, ratios, ar, top, emp, invoices, com = await asyncio.gather(
        _safe(mcp.call("fetch_report", {"report_name": "Resultatrapport",
                                        "period_start": start,
                                        "period_end": today.isoformat(),
                                        "limit": 0}), "resultat"),
        _safe(mcp.call("fetch_report", {"report_name": "Resultatrapport",
                                        "period_start": prev_start,
                                        "period_end": prev_end,
                                        "limit": 0}), "resultat i fjor"),
        _safe(mcp.call("fetch_report", {"report_name": "Nøkkeltallsrapport",
                                        "period_start": start,
                                        "period_end": today.isoformat()}), "nøkkeltall"),
        _safe(mcp.call("fetch_report", {"report_name": "Kundereskontro",
                                        "period_start": start,
                                        "period_end": today.isoformat(),
                                        "limit": 0}), "kundereskontro"),
        _safe(mcp.call("fetch_report", {"report_name": "Topp 20 kunder",
                                        "period_start": start,
                                        "period_end": today.isoformat(),
                                        "limit": 0}), "topp 20"),
        _safe(mcp.call("search_employees", {"count": 100}), "ansatte"),
        _safe(mcp.call("search_invoices",
                       {"invoiceDateFrom": start, "invoiceDateTo": today.isoformat(),
                        "count": 40}), "fakturaer"),
        _safe(commitments.cached(), "forpliktelser"),
    )

    p, pr, rr = _rows(pnl), _rows(prev), _rows(ratios)
    revenue = _at(p, "Driftsresultat > Driftsinntekter")
    operating = _at(p, "Driftsresultat")
    wages = _at(p, "Driftsresultat > Driftskostnader > Lønnskostnad")
    materials = _at(p, "Driftsresultat > Driftskostnader > Varekostnad")
    costs = _at(p, "Driftsresultat > Driftskostnader")
    opex = (costs - (wages or 0) - (materials or 0)) if costs is not None else None

    employees = len((emp or {}).get("employees") or []) or None
    days = (today - date(today.year, 1, 1)).days + 1
    annualise = 365 / days if days else 1

    # Revenue concentration, from the customer report if it answers and from
    # the receivables ledger if it does not.
    top_share = top3 = None
    trows = _rows(top)
    tcols = [c.get("name") for c in (top or {}).get("table", {}).get("columns", [])]
    idx = next((i for i, n in enumerate(tcols) if n and "omsetning" in n.lower()), None)
    customers: list[tuple[str, float]] = []
    if idx is not None:
        for r in trows:
            cells = r.get("cells") or []
            if idx < len(cells) and isinstance(cells[idx], (int, float)):
                customers.append(((r.get("path") or "").split(" (")[0],
                                  float(cells[idx])))
    customers.sort(key=lambda kv: -kv[1])
    if customers and revenue:
        top_share = _pct(customers[0][1], revenue)
        top3 = _pct(sum(v for _, v in customers[:3]), revenue)

    ar_total = None
    ar_rows = [(r.get("path", "").split(" (")[0], float(r["cells"][1]))
               for r in _rows(ar)
               if len(r.get("cells") or []) > 1 and isinstance(r["cells"][1], (int, float))]
    if ar_rows:
        ar_total = sum(v for _, v in ar_rows)

    equity = _at(rr, "Egenkapitalandel i % (soliditet)")
    ctx = {
        "revenue": revenue, "revenue_prev": _at(pr, "Driftsresultat > Driftsinntekter"),
        "operating": operating, "wages": wages, "materials": materials,
        "opex": opex, "employees": employees, "ar": ar_total,
        "days_elapsed": days,
        "revenue_annualised": revenue * annualise if revenue else None,
        "wages_annualised": wages * annualise if wages else None,
        "operating_annualised": operating * annualise if operating else None,
        "top_customer_share": top_share, "top3_share": top3,
        "free_cash": (com or {}).get("free_all"),
        "liquidity": _at(rr, "Likviditetsgrad 1"),
        "equity_ratio": round(equity * 100, 1) if equity is not None else None,
    }

    evidence = {
        "selskap": config.COMPANY_NAME,
        "antall_ansatte": employees,
        "omsetning_hittil_i_ar": revenue,
        "kostnadsstruktur_pct": {
            "lønn": _pct(wages, revenue), "varer": _pct(materials, revenue),
            "annet": _pct(opex, revenue)},
        "inntektskontoer": _leaves(p, "Driftsresultat > Driftsinntekter"),
        "kostnadskontoer": _leaves(p, "Driftsresultat > Driftskostnader"),
        "storste_kunder": [n for n, _ in customers[:8]],
        "fakturatekster": [
            (r.get("invoiceComment") or "").replace("\n", " ").strip()[:110]
            for r in ((invoices or {}).get("rows") or [])[:18]
            if (r.get("invoiceComment") or "").strip()],
    }
    return ctx, evidence


# -------------------------------------------------------------- classifying

CLASSIFIER_PROMPT = """Du er CFO. Her er bevisene fra regnskapet til et norsk selskap.
Finn ut hvilken bransje selskapet faktisk er i, og velg hvilke nøkkeltall daglig
leder bør se på forsiden.

BEVIS
{evidence}

NØKKELTALL DU KAN VELGE MELLOM
Du kan bare velge fra denne lista. Tall som ikke lar seg regne ut for dette
selskapet er allerede fjernet.
{menu}

SVAR MED JSON, INGENTING ANNET:
{{
  "bransje": "kort navn på bransjen, på norsk",
  "beskrivelse": "én setning om hva selskapet gjør, i klartekst",
  "begrunnelse": "hva i bevisene som avgjorde det",
  "sikkerhet": "høy" | "middels" | "lav",
  "nokkeltall": [
    {{"id": "<id fra lista>",
      "hvorfor": "én setning: hvorfor dette tallet avgjør noe i akkurat denne bransjen, til en eier som ikke kan regnskap",
      "mal": <tall eller null: hva et godt selskap i denne bransjen ligger på>,
      "varsel": <tall eller null: verdien der eieren bør reagere>}}
  ],
  "hovedtall": "<id-en som betyr mest av alle>"
}}

Velg fem til sju nøkkeltall, viktigst først. Sett mål og varsel som tall i samme
enhet som nøkkeltallet, basert på hva som faktisk er normalt i denne bransjen i
Norge — ikke på hva dette selskapet tilfeldigvis ligger på. La dem være null
bare hvis bransjen ikke har noe meningsfylt normalnivå.
Skriv alt på norsk, uten regnskapsord."""


def _menu(available: list[str]) -> str:
    return "\n".join(
        f"- {k.id} — {k.label} ({k.unit}, {'høyt er bra' if k.better == 'high' else 'lavt er bra'}): {k.plain}"
        for k in CATALOGUE if k.id in available)


def _computable(ctx: dict) -> list[str]:
    """Only offer what this company's data can actually produce."""
    out = []
    for k in CATALOGUE:
        try:
            if k.compute(ctx) is not None:
                out.append(k.id)
        except (TypeError, ZeroDivisionError, KeyError, calc.CalcError):
            continue
    return out


async def classify(ctx: dict, evidence: dict) -> dict:
    available = _computable(ctx)
    prompt = CLASSIFIER_PROMPT.format(
        evidence=json.dumps(evidence, ensure_ascii=False, indent=1),
        menu=_menu(available))
    msg = await client.messages.create(
        model=config.CFO_MODEL, max_tokens=2000,
        messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Klassifiseringen svarte ikke med JSON: {text[:200]}")
    data = json.loads(text[start:end + 1])

    # The model chose from a menu, but trust is not a substitute for checking:
    # anything it invented is dropped rather than rendered as a blank tile.
    chosen, seen = [], set()
    for item in data.get("nokkeltall") or []:
        kid = item.get("id")
        if kid in BY_ID and kid in available and kid not in seen:
            seen.add(kid)
            chosen.append(item)
        else:
            log.warning("Klassifiseringen foreslo ukjent nøkkeltall: %s", kid)
    if not chosen:
        raise ValueError("Klassifiseringen valgte ingen gyldige nøkkeltall")
    data["nokkeltall"] = chosen
    if data.get("hovedtall") not in seen:
        data["hovedtall"] = chosen[0]["id"]
    data["bestemt"] = date.today().isoformat()
    data["vurderte"] = available
    return data


# ------------------------------------------------------------------ profile

def _load_profile() -> dict | None:
    if not PROFILE_STORE.exists():
        return None
    try:
        return json.loads(PROFILE_STORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Bransjeprofilen er ulesbar (%s); den bygges på nytt", exc)
        return None


def _save_profile(data: dict) -> None:
    PROFILE_STORE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_STORE.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                             encoding="utf-8")


async def profile(refresh: bool = False, today: date | None = None,
                  gathered: tuple[dict, dict] | None = None) -> dict:
    """The industry and its KPIs. Decided once, then read from disk.

    It costs a model call and it is a judgement, so it is not re-decided on
    every page load — and it is stored with its reasoning, so a human who
    disagrees can see what it thought and overrule it.
    """
    today = today or date.today()
    if not refresh:
        cached = _load_profile()
        if cached:
            return cached
    # The dashboard has usually just gathered the same evidence; a second
    # round of six Tripletex calls to classify on identical inputs is waste.
    ctx, evidence = gathered if gathered is not None else await _gather(today)
    data = await classify(ctx, evidence)
    data["bevis"] = evidence
    _save_profile(data)
    log.info("Bransje bestemt: %s (%s)", data.get("bransje"), data.get("sikkerhet"))
    return data


# ---------------------------------------------------------------- dashboard

def _status(value, target, alert, better: str) -> str:
    """How this figure is doing against what the industry expects."""
    if value is None or (target is None and alert is None):
        return "unknown"
    if alert is not None:
        bad = value >= alert if better == "low" else value <= alert
        if bad:
            return "bad"
    if target is not None:
        good = value <= target if better == "low" else value >= target
        return "good" if good else "watch"
    return "watch"


async def dashboard(today: date | None = None) -> dict:
    today = today or date.today()
    now = time.time()
    if _values_cache.get("data") and now - _values_cache.get("at", 0) < VALUES_CACHE_SECONDS:
        return _values_cache["data"]

    gathered = await _gather(today)
    prof = await profile(today=today, gathered=gathered)
    ctx = gathered[0]

    tiles = []
    for item in prof["nokkeltall"]:
        kpi = BY_ID[item["id"]]
        try:
            value = kpi.compute(ctx)
        except (TypeError, ZeroDivisionError, KeyError, calc.CalcError):
            value = None
        tiles.append({
            "id": kpi.id, "label": kpi.label, "plain": kpi.plain,
            "unit": kpi.unit, "better": kpi.better,
            "value": round(value, 1) if isinstance(value, float) else value,
            "target": item.get("mal"), "alert": item.get("varsel"),
            "why": item.get("hvorfor"),
            "status": _status(value, item.get("mal"), item.get("varsel"), kpi.better),
            "headline": kpi.id == prof.get("hovedtall"),
        })

    data = {"as_of": today.isoformat(), "company": config.COMPANY_NAME,
            "industry": prof.get("bransje"), "description": prof.get("beskrivelse"),
            "reasoning": prof.get("begrunnelse"), "confidence": prof.get("sikkerhet"),
            "decided": prof.get("bestemt"), "kpis": tiles}
    _values_cache.update({"data": data, "at": now})
    return data
