"""Forsidens oppsummering: hvordan det går, skrevet av Arvaka selv.

Dette er den ene teksten på forsiden som koster et modellkall. Alt annet der er
regnet ut. Derfor er den skrevet én gang per dag og lest fra disk resten av
døgnet — en sidelast skal fortsatt være gratis. Modellen får ferdig utregnede
tall og ingen verktøy: den skal formulere, ikke hente. Da kan den heller ikke
finne på et tall som ikke står i grunnlaget.
"""
import asyncio
import json
import logging
import time
from datetime import date

import cashflow
import company
import config
import memory
from agent import core
from commitments import cached as commitments_cached
# The saved profile, read from disk rather than re-decided: classifying the
# industry costs a model call, and this text already is one. Same reach into a
# sibling's private as cashflow.py makes into preflight, for the same reason —
# two readings of one profile that drift apart are worse than one import.
from industry import _load_profile
from overview import cached as overview_cached

log = logging.getLogger("cfo.summary")

STORE = config.STATE / "summary.json"
# A ceiling, not a budget: only what is written is paid for. 700 cut every
# answer off once the model in use wrote longer Norwegian than it was sized for.
MAX_TOKENS = 4000

# No tools: it is given the figures and asked to phrase them, not fetch them.
# Through the core so `verify` reads it like every other answer — a figure in
# the summary that is not in the grunnlag is logged as one.
SUMMARY = core.Job(name="oppsummering", max_tokens=MAX_TOKENS, output="json",
                   prompt_source="grunnlaget",
                   schema=core.obj(verdict=core.STR, text=core.STR))

# Ett kall om gangen. Uten dette skriver fem samtidige sidelaster den samme
# teksten fem ganger den første morgenen noen åpner forsiden.
_lock = asyncio.Lock()

# A failed attempt is remembered for this long. Only success was remembered,
# so while the text could not be written every front-page load and every
# "Oppdater" paid for another try: four cut-off answers at $0.044 each on
# 10–11 October, all from page loads. Half an hour is the scheduler's own
# retry gap, so its retries still get a real attempt; the rewrite button
# (refresh=true) always tries, being someone asking on purpose.
RETRY_AFTER_S = 30 * 60
_failed: dict = {}            # {"day", "at", "error"} of the last failed attempt
_clock = time.monotonic

PROMPT = """Du er finansdirektøren i {company}. Skriv dagens oppsummering til \
daglig leder — den korte teksten øverst på forsiden som sier hvordan det går.

Bransjen selskapet driver i, og hva som avgjør om det tjener penger der:
{industry}

Slik fungerer selskapet, skrevet av dem som driver det:
{company_context}

Grunnlaget, alt hittil i år om ikke annet står:
{facts}

Skriv tre til fem setninger, i sammenheng, på norsk. Krav:

- Begynn med hvordan det faktisk går. Ikke med en oppramsing av tall.
- Bruk bare tall som står i grunnlaget over. Finner du ikke et tall, la være å
  nevne det. Ikke rund av til noe som ser penere ut enn det er.
- Les tallene i lys av bransjen. Nevn et nøkkeltall fordi det avgjør noe i
  nettopp denne driften, ikke fordi det står i lista.
- Bruk selskapets egen beskrivelse til å forklare *hvorfor* tallene ser slik ut
  der den forklarer det. Den gjelder for mening, aldri for tall: står den mot
  regnskapet, har regnskapet rett på tallet og beskrivelsen på grunnen.
- Pek på det som har endret seg de siste månedene, ikke bare nivået nå.
- Mål mot selskapets egne regler i grunnlaget — likviditetsgulvet og målet
  for lønnsandel — ikke mot dine egne tommelfingerregler. Står det at en regel
  er antatt, og du bruker den, si at den er antatt.
- Si én ting som bør følges opp. Én, den viktigste.
- Skriv som til en daglig leder som ikke er regnskapsfører: ingen fagord, ingen
  forkortelser, ingen punktliste, ingen overskrift.

Svar med JSON og ingenting annet:
{{"verdict": "<to-fire ord: hvordan det står til>", "text": "<teksten>"}}

`verdict` er merkelappen som vises over teksten, for eksempel "Solid drift",
"Stram likviditet" eller "Presset margin"."""


def _shape(ov: dict, com: dict, months: list[dict],
           cf: dict | None = None) -> dict:
    k = ov.get("kpis") or {}
    recent = [m for m in months if m.get("revenue") is not None][-6:]
    rules = cashflow.rules(cf)
    floor, wage = rules["likviditetsgulv_kr"], rules["lonnsandel_mal_pct"]
    low = (cf or {}).get("low_committed") or {}
    hit = cashflow.below_floor(cf, floor["value"]) if cf else None
    return {
        "periode": ov.get("period"),
        "omsetning_hittil": k.get("omsetning"),
        "omsetning_budsjett": k.get("omsetning_budsjett"),
        "driftsresultat_hittil": k.get("driftsresultat"),
        "driftsmargin_pct": k.get("driftsmargin_pct"),
        "lonnsandel_pct": k.get("lonnsandel_pct"),
        "lonnsandel_budsjett_pct": k.get("lonnsandel_budsjett_pct"),
        "lonnsandel_mal_pct": wage["value"],
        "lonnsandel_mal_hvor_fra": company.said(wage),
        "penger_i_banken": k.get("bank"),
        "kundefordringer": k.get("kundefordringer"),
        "likviditetsgrad": k.get("likviditetsgrad"),
        "egenkapitalandel_pct": k.get("egenkapitalandel_pct"),
        "per_maaned": recent,
        "storste_kunde": ov.get("top_debtor"),
        "ubokfort_skatt": (ov.get("flags") or {}).get("ubokfort_skatt"),
        "fritt_paa_konto_naa": com.get("free_now"),
        "fritt_etter_alle_forpliktelser": com.get("free_all"),
        # Without the forecast there is no low point to hold the floor
        # against, and a floor on its own invites a comparison with today's
        # balance, which is the wrong one.
        "likviditetsgulv": ({"kr": floor["value"],
                             "hvor_fra": company.said(floor)} if cf else None),
        "laveste_bundne_saldo_13_uker": (
            {"uke": low.get("label"), "fra": low.get("start"),
             "kr": low.get("amount")} if low else None),
        "forste_uke_under_gulvet": hit,
        "apne_funn": [
            {"tema": f.get("topic"), "alvor": f.get("severity"),
             "sagt": f.get("statement"), "reist": f.get("opened")}
            for f in (memory.open_findings() or [])
        ][:8],
    }


def _industry(prof: dict | None) -> str:
    """The trade and what decides profitability in it, from the saved profile.

    The KPI list carries each figure's target, its alarm level and the reason it
    matters *for this trade* — which is what turns "lønnsandel 83.8 %" from a
    number into a finding. Without it the model has to guess what is normal for
    a cleaning contractor, and it guesses like a generalist.
    """
    if not prof:
        return ("Ikke bestemt ennå — les tallene som de står, uten å anta noe om "
                "bransjen.")
    out = [f"Bransje: {prof.get('bransje') or 'ukjent'}"]
    if prof.get("beskrivelse"):
        out.append(f"Slik tjener selskapet penger: {prof['beskrivelse']}")
    head = prof.get("hovedtall")
    kpis = prof.get("nokkeltall") or []
    if kpis:
        out.append("Nøkkeltallene som avgjør driften, med mål og varselnivå:")
        for k in kpis:
            mark = " [viktigste]" if k.get("id") == head else ""
            target = k.get("mal")
            alert = k.get("varsel")
            bounds = (f" (mål {target}, varsel ved {alert})"
                      if target is not None or alert is not None else "")
            out.append(f"- {k.get('id')}{mark}{bounds}: {k.get('hvorfor') or ''}".rstrip())
    return "\n".join(out)


def _human_error(exc: Exception) -> str:
    """What the front page is allowed to say. The provider keeps its own words
    in the log — a billing URL and a request id are not news to a CEO."""
    detail = str(exc)
    if "credit balance is too low" in detail:
        return ("Ingen kreditt på Anthropic-kontoen, så Arvaka får ikke skrevet "
                "oppsummeringen. Tallene under er uberørt.")
    if "Ingen tall å oppsummere" in detail:
        return "Ingen tall å oppsummere ennå."
    return ("Arvaka fikk ikke skrevet oppsummeringen i dag. Detaljene ligger i "
            "serverloggen.")


def _read() -> dict | None:
    if not STORE.exists():
        return None
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Oppsummeringen på disk er ulesbar (%s)", exc)
        return None


def _write(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                     encoding="utf-8")


async def build(today: date | None = None) -> dict:
    today = today or date.today()
    ov, com, cf = await asyncio.gather(overview_cached(), commitments_cached(),
                                       cashflow.cached(), return_exceptions=True)
    ov = {} if isinstance(ov, Exception) else ov
    com = {} if isinstance(com, Exception) else com
    cf = None if isinstance(cf, Exception) else cf
    if not (ov.get("kpis") or {}).get("omsetning"):
        raise ValueError("Ingen tall å oppsummere ennå")

    facts = _shape(ov, com, ov.get("monthly") or [], cf)
    result = await core.complete(SUMMARY, PROMPT.format(
        company=config.COMPANY_NAME,
        industry=_industry(_load_profile()),
        company_context=company.briefing() or "Ikke skrevet ennå.",
        facts=json.dumps(facts, ensure_ascii=False, indent=1)))
    data = result.data
    text = (data.get("text") or "").strip()
    if not text:
        raise ValueError("Oppsummeringen kom tom tilbake")
    return {"verdict": (data.get("verdict") or "").strip() or None,
            "text": text, "written": today.isoformat(),
            # Kept with the text, so a figure the grunnlag does not hold can be
            # found again after the log has rolled over.
            "unverified": list(result.check.get("unverified", []))}


async def cached(refresh: bool = False) -> dict:
    """Dagens tekst. Skrives én gang per dag; refresh=true tvinger en ny."""
    today = date.today().isoformat()
    stored = _read()
    if not refresh and stored and stored.get("written") == today:
        return stored
    if not refresh and _resting(today):
        return _after_failure(stored)
    async with _lock:
        stored = _read()          # en annen forespørsel kan ha rukket det
        if not refresh and stored and stored.get("written") == today:
            return stored
        if not refresh and _resting(today):
            return _after_failure(stored)
        try:
            fresh = await build()
        except Exception as exc:  # noqa: BLE001
            log.exception("Kunne ikke skrive dagens oppsummering")
            _failed.update(day=today, at=_clock(), error=_human_error(exc))
            return _after_failure(stored)
        _failed.clear()
        _write(fresh)
        return fresh


def _resting(today: str) -> bool:
    """Whether today's last attempt failed too recently to try again."""
    return _failed.get("day") == today and _clock() - _failed["at"] < RETRY_AFTER_S


def _after_failure(stored: dict | None) -> dict:
    # En gårsdagstekst med dato på er bedre enn et tomt kort. Er det
    # ingenting på disk heller, sier kortet fra i stedet.
    if stored:
        return dict(stored, stale=True)
    return {"error": _failed.get("error") or _human_error(RuntimeError())}
