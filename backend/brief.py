"""The Monday cash brief: one phone screen, read in a minute or two.

The playbook's first deliverable. It answers, in this order, what a CEO asks
on a Monday: am I all right, when is it tightest, what moved, what do you need
from me, and can I trust the figures.

**The engine decides; the model phrases.** Everything a CEO could act on is
computed here without a model: the light, the low point against the floor,
the changes since a week ago, the decisions, the condition of the books and
the forecast's record. The model writes the one sentence after the light and
says the changes in words, from those figures only, through the shared core
so `verify` reads it. A light a model chose could be argued with; a light the
forecast and the rulebook chose can be checked.

**The light.** Measured on the forecast against the company's own floor:

- RED — even the expected line, the one that counts on customers paying as
  they usually do, goes under the floor within six weeks; or the committed
  line goes below zero within four.
- YELLOW — the committed line, money already invoiced and billed, goes under
  the floor within six weeks, or the expected line does later on.
- GREEN — neither: the committed line holds the floor for at least six weeks.
  A dip after that is said in the low-point line, not in the colour.

A forecast that could not be built whole, or books whose tie-outs are broken,
cannot be called green: the brief says yellow and why.

**Kept, not regenerated.** Each brief is a row in `reports` (`weekly_brief`,
period `2026-W41`), with the figures it was written from. A rewrite is a new
row. The web app shows the latest, and card 9 sends the same text.
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta

import cards
import cashflow
import company
import config
import db
import memory
import preflight
import scoring
import verify
from agent import core

log = logging.getLogger("cfo.brief")

KIND = "weekly_brief"
RED_WEEKS = 6            # expected line under the floor this soon is red
ZERO_WEEKS = 4           # committed line below zero this soon is red
SAFE_WEEKS = 6           # committed line must hold the floor this long for green
MAX_DECISIONS = 3
MAX_CHANGES = 3
MAX_BOOK_LINES = 3
MAX_TOKENS = 600

LIGHTS = {"green": "GRØNN", "yellow": "GUL", "red": "RØD"}
MONTHS = ("januar", "februar", "mars", "april", "mai", "juni", "juli",
          "august", "september", "oktober", "november", "desember")

# Named so the scheduler's own `weekly_brief` runs are not counted as the
# slot's attempts: `job_runs` tells a slot's runs by the job's name.
TEXT = core.Job(name="mandagsbrev", max_tokens=MAX_TOKENS, output="json",
                prompt_source="grunnlaget")


class BriefError(RuntimeError):
    """The brief could not be written. The message is for the front page."""


def period(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _kr(v) -> str:
    return f"{round(v):,}".replace(",", " ")


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day}. {MONTHS[d.month - 1]}"


# ------------------------------------------------------------------ the light
@dataclass(frozen=True)
class Light:
    colour: str
    why: str                     # in words, for the facts and the model
    safe_weeks: int              # weeks the committed line holds the floor


def _first(weeks: list[dict], key: str, below: float) -> int | None:
    return next((i for i, w in enumerate(weeks) if w[key] < below), None)


def light(cf: dict, floor: float, books: str = "clean") -> Light:
    """The colour, from the forecast and the floor. See the module doc."""
    weeks = cf.get("weeks") or []
    c_floor = _first(weeks, "committed_close", floor)
    e_floor = _first(weeks, "expected_close", floor)
    c_zero = _first(weeks, "committed_close", 0)
    safe = len(weeks) if c_floor is None else c_floor

    if e_floor is not None and e_floor < RED_WEEKS:
        out = Light("red", "Selv om kundene betaler som de pleier, går saldoen "
                    "under gulvet innen seks uker.", safe)
    elif c_zero is not None and c_zero < ZERO_WEEKS:
        out = Light("red", "Pengene som allerede er fakturert og regningene som "
                    "allerede er kommet, tar kontoen under null innen fire uker.",
                    safe)
    elif c_floor is not None and c_floor < SAFE_WEEKS:
        out = Light("yellow", "Uten innbetalinger utover det som er fakturert, "
                    "går saldoen under gulvet innen seks uker.", safe)
    elif e_floor is not None:
        out = Light("yellow", "Saldoen går under gulvet senere i perioden, selv "
                    "om kundene betaler som de pleier.", safe)
    else:
        out = Light("green", f"Saldoen holder gulvet i minst {safe} uker på det "
                    f"som allerede er fakturert.", safe)

    if out.colour == "green" and cf.get("partial"):
        return Light("yellow", "Prognosen mangler noe fra Tripletex, så den kan "
                     "ikke kalles grønn.", safe)
    if out.colour == "green" and books == "broken":
        return Light("yellow", "En avstemming i regnskapet stemmer ikke, så "
                     "prognosen kan ikke kalles grønn.", safe)
    return out


def low_point(cf: dict, floor_rule: dict) -> dict:
    """The tightest week on the committed line, held against the floor."""
    weeks = cf.get("weeks") or []
    floor = floor_rule["value"]
    low = min(weeks, key=lambda w: w["committed_close"])
    first = next((w for w in weeks if w["committed_close"] < floor), None)
    under = low["committed_close"] < floor
    short = round(floor - low["committed_close"], 2) if under else None
    if under:
        text = (f"Laveste punkt: {low['label'].lower()} (fra {_day(low['start'])}), "
                f"{_kr(low['committed_close'])} kr — {_kr(short)} kr "
                f"under gulvet på {_kr(floor)} kr.")
        if first is not None and first is not low:
            text += f" Første uke under gulvet er {first['label'].lower()}."
    else:
        text = (f"Laveste punkt: {low['label'].lower()} (fra {_day(low['start'])}), "
                f"{_kr(low['committed_close'])} kr — over gulvet på {_kr(floor)} kr "
                f"alle {len(weeks)} ukene.")
    if floor_rule.get("assumed"):
        text += f" Gulvet er {company.said(floor_rule)}."
    return {"week": low["label"], "start": low["start"],
            "amount": low["committed_close"], "floor": floor,
            "floor_assumed": bool(floor_rule.get("assumed")),
            "under_floor": under, "short_of_floor": short,
            "first_under": first and {"week": first["label"], "start": first["start"],
                                      "amount": first["committed_close"]},
            "text": text}


# ------------------------------------------------------------ what changed
def changes(today: date) -> dict:
    """What moved since a week ago, from the stored figures. No model."""
    out: dict = {"since": None, "kpis": [], "low_point": None,
                 "cards": {"opened": 0, "decided": 0}, "findings": {"opened": 0,
                                                                   "closed": 0}}
    snaps = memory._load()["snapshots"]
    now = snaps[-1] if snaps else None
    then = memory._at_or_before(snaps, today - timedelta(days=7))
    if now and then and then["date"] != now["date"]:
        out["since"] = then["date"]
        same_defs = now.get("definitions_hash") == then.get("definitions_hash")
        for key, label, unit in memory.TRENDED:
            a, b = then["kpis"].get(key), now["kpis"].get(key)
            if a is None or b is None or round(b - a, 2) == 0:
                continue
            out["kpis"].append({
                "kpi": key, "label": label, "unit": unit, "before": a, "now": b,
                "change": round(b - a, 2),
                # Cumulative since 1 January: the difference is what the week
                # added, not a change in a level.
                "cumulative": key in memory.CUMULATIVE,
                "comparable": same_defs})

    week_ago = (today - timedelta(days=7)).isoformat()
    cid = db.company_id()
    with db.read() as conn:
        last = conn.execute(
            "SELECT made_on, low_committed_ore, low_committed_week FROM forecast_runs "
            "WHERE company_id = ? AND purpose = 'weekly' AND made_on <= ? "
            "ORDER BY made_on DESC, id DESC LIMIT 1", (cid, week_ago)).fetchone()
        out["cards"]["opened"] = conn.execute(
            "SELECT count(*) FROM card_events WHERE company_id = ? AND event = 'created' "
            "AND substr(at, 1, 10) > ?", (cid, week_ago)).fetchone()[0]
        out["cards"]["decided"] = conn.execute(
            "SELECT count(*) FROM card_events WHERE company_id = ? AND event = 'decided' "
            "AND substr(at, 1, 10) > ?", (cid, week_ago)).fetchone()[0]
        out["findings"]["opened"] = conn.execute(
            "SELECT count(*) FROM findings WHERE company_id = ? AND opened_on > ?",
            (cid, week_ago)).fetchone()[0]
        out["findings"]["closed"] = conn.execute(
            "SELECT count(*) FROM findings WHERE company_id = ? AND closed_on > ?",
            (cid, week_ago)).fetchone()[0]
    if last and last["low_committed_ore"] is not None:
        out["low_point"] = {"made_on": last["made_on"],
                            "amount": db.to_kr(last["low_committed_ore"]),
                            "start": last["low_committed_week"]}
    return out


def _fmt(value: float, unit: str) -> str:
    if unit == "kr":
        return f"{_kr(value)} kr"
    if unit == "%":
        return f"{value:.1f} %".replace(".", ",")
    return f"{value:.2f}".replace(".", ",")


def _change_lines(ch: dict, low: dict) -> list[str]:
    """The changes said plainly: what the brief says when the model cannot
    phrase them, and what the model is shown to start from. The low point
    first, since the brief is about cash; then the levels that moved most,
    relative to where they were; the year-to-date sums last, because a week
    added to them is the ordinary course of things."""
    lines = []
    prev = ch.get("low_point")
    if prev and prev["amount"] is not None and round(low["amount"] - prev["amount"]) != 0:
        diff = low["amount"] - prev["amount"]
        lines.append(f"Laveste punkt er {_kr(abs(diff))} kr "
                     f"{'høyere' if diff > 0 else 'lavere'} enn i prognosen fra "
                     f"{_day(prev['made_on'])} ({_kr(prev['amount'])} kr).")
    moved = [k for k in ch["kpis"] if k["comparable"]]
    levels = sorted((k for k in moved if not k["cumulative"]),
                    key=lambda k: -abs(k["change"]) / (abs(k["before"]) or 1))
    lines += [f"{k['label']}: {_fmt(k['now'], k['unit'])}, fra "
              f"{_fmt(k['before'], k['unit'])}." for k in levels]
    lines += [f"{k['label']} {'økte' if k['change'] > 0 else 'falt'} med "
              f"{_fmt(abs(k['change']), k['unit'])} siste uke."
              for k in moved if k["cumulative"]]
    return lines


# ---------------------------------------------------------- what needs you
def decisions(deck: dict) -> dict:
    """The open cards, most pressing first, at most three. The deck's own
    order: urgency, then amount."""
    open_cards = deck.get("open") or []
    top = [{"id": c["id"], "title": c["title"], "urgency": c.get("urgency"),
            "amount": c.get("amount"), "link": f"#saker/{c['id']}"}
           for c in open_cards[:MAX_DECISIONS]]
    return {"count": len(open_cards), "top": top,
            "more": max(0, len(open_cards) - MAX_DECISIONS)}


def books(pf: dict | None) -> dict:
    """How current the books are, from the pre-flight."""
    if not pf:
        return {"condition": "unknown", "lines": [],
                "text": "Bøkene: kontrollen kunne ikke kjøres, så om de er ajour "
                        "er ukjent."}
    flagged = [c for c in pf.get("checks") or [] if c.get("status") in ("warn", "note")]
    flagged.sort(key=lambda c: c["status"] != "warn")
    unknown = [c for c in pf.get("checks") or [] if c.get("status") == "unavailable"]
    lines = [c["headline"] for c in flagged[:MAX_BOOK_LINES]]
    condition = pf.get("condition") or "clean"
    if not flagged and not unknown:
        text = "Bøkene er ajour."
    else:
        head = preflight.CONDITION_TEXT.get(condition, preflight.CONDITION_TEXT["clean"])[0]
        text = f"Bøkene: {head}"
        if unknown:
            text += (f" {len(unknown)} kontroll{'er' if len(unknown) > 1 else ''} "
                     f"kunne ikke kjøres.")
    return {"condition": condition, "lines": lines, "text": text}


def accuracy(today: date) -> dict:
    """The forecast's record, once there is one."""
    rec = scoring.track_record(today)
    h = scoring.STREAK_HORIZON
    latest = rec["latest"].get(h)
    if not latest:
        when = f" Første måling rundt {_day(rec['next'])}." if rec.get("next") else ""
        return {"scored": False, "kept": rec["weekly_forecasts_kept"],
                "text": f"Treffsikkerhet: ikke målt ennå "
                        f"({rec['weekly_forecasts_kept']} ukeprognose"
                        f"{'r' if rec['weekly_forecasts_kept'] != 1 else ''} lagret).{when}"}
    mean = rec["mean_abs_error_pct"].get(h)
    text = (f"Treffsikkerhet: prognosen fire uker fram bommet med "
            f"{latest['error_pct']:+.1f} % sist".replace(".", ","))
    if mean is not None:
        text += f", ±{mean:.1f} % i snitt".replace(".", ",")
    text += (f". Innenfor ±{rec['within_pct']:.0f} % {rec['streak']} uke"
             f"{'r' if rec['streak'] != 1 else ''} på rad; målet er 8.")
    return {"scored": True, "latest_error_pct": latest["error_pct"],
            "mean_abs_error_pct": mean, "streak": rec["streak"], "text": text}


# ------------------------------------------------------------ the writing
PROMPT = """Du er finansdirektøren i {company}. Skriv mandagsbrevet om \
likviditeten til daglig leder. Det leses på telefonen på et minutt.

Fargen er bestemt av prognosen og selskapets eget likviditetsgulv, ikke av deg:
{colour} — {why}

Grunnlaget, regnet ut her:
{facts}

Skriv to ting, på norsk, til en daglig leder som ikke er regnskapsfører:

1. `sentence`: én setning som følger etter fargen og sier hva den betyr for
   ham denne uka. Ikke gjenta fargen. Ikke start med «Kontantene er».
2. `changed`: inntil {max_changes} korte linjer om hva som har endret seg
   siden forrige mandag, det viktigste først. Bruk `endringer` i grunnlaget;
   `forslag` er de samme endringene sagt rett fram, som du kan bruke eller
   skrive bedre. Hopp over det som ikke betyr noe for pengene. Er det ingen
   endringer, gi en tom liste.

Bruk bare tall som står i grunnlaget, slik de står. Ingen tall du har regnet
ut selv. Ingen fagord, ingen forkortelser.

Svar med JSON og ingenting annet:
{{"sentence": "<setningen>", "changed": ["<linje>", ...]}}"""


async def _phrase(lt: Light, facts: dict, suggested: list[str]) -> tuple[dict, dict]:
    """The model's sentence and change lines, and verify's check of them."""
    shown = {k: v for k, v in facts.items() if k not in ("decisions",)}
    shown["forslag"] = suggested
    result = await core.complete(TEXT, PROMPT.format(
        company=config.COMPANY_NAME, colour=LIGHTS[lt.colour], why=lt.why,
        max_changes=MAX_CHANGES,
        facts=json.dumps(shown, ensure_ascii=False, indent=1)))
    data = result.data or {}
    sentence = (data.get("sentence") or "").strip()
    if not sentence:
        raise core.JobError("Mandagsbrevet kom uten setning")
    changed = [str(c).strip() for c in data.get("changed") or [] if str(c).strip()]
    return {"sentence": sentence, "changed": changed[:MAX_CHANGES]}, result.check


def render(b: dict) -> str:
    """The brief as plain text: what the email sends and the archive keeps."""
    out = [f"{LIGHTS[b['light']]} — {b['sentence']}", b["low_point"]["text"], ""]
    out.append("Endret siden forrige mandag")
    out += [f"- {c}" for c in b["changed"]] or ["- Ingen endringer verdt å nevne."]
    out.append("")
    d = b["decisions"]
    if d["count"]:
        out.append(f"Trenger deg ({d['count']})")
        for c in d["top"]:
            amount = f" — {_kr(c['amount'])} kr" if c.get("amount") else ""
            out.append(f"- {c['title']}{amount}")
        if d["more"]:
            out.append(f"- og {d['more']} til under Saker")
    else:
        out.append("Ingenting trenger deg denne uka.")
    out.append("")
    out.append(b["books"]["text"])
    out += [f"- {line}" for line in b["books"]["lines"]]
    out.append(b["accuracy"]["text"])
    return "\n".join(out)


async def build(today: date | None = None) -> dict:
    """Gather the figures, decide the light, have the sentence written."""
    today = today or date.today()
    cf, pf = await asyncio.gather(cashflow.cached(), preflight.cached(),
                                  return_exceptions=True)
    if isinstance(cf, Exception) or not (cf or {}).get("weeks"):
        raise BriefError("Prognosen kunne ikke bygges, så mandagsbrevet ble ikke "
                         "skrevet.") from (cf if isinstance(cf, Exception) else None)
    pf = None if isinstance(pf, Exception) else pf

    floor_rule = cashflow.rules(cf)["likviditetsgulv_kr"]
    bk = books(pf)
    lt = light(cf, floor_rule["value"], bk["condition"])
    low = low_point(cf, floor_rule)
    ch = changes(today)
    dec = decisions(cards.deck())
    acc = accuracy(today)

    facts = {"farge": lt.colour, "hvorfor": lt.why,
             "uker_over_gulvet": lt.safe_weeks,
             "laveste_punkt": {k: low[k] for k in ("week", "start", "amount",
                                                   "floor", "under_floor",
                                                   "short_of_floor",
                                                   "first_under")},
             "endringer": ch, "decisions": dec, "bokene": bk, "treffsikkerhet": acc,
             "prognose_ufullstendig": bool(cf.get("partial"))}
    suggested = _change_lines(ch, low)

    written_by, check, problem = "model", {}, None
    try:
        words, check = await _phrase(lt, facts, suggested)
    except Exception as exc:  # noqa: BLE001 — the figures are the brief
        log.exception("Mandagsbrevet ble skrevet uten modellen")
        written_by, problem = "engine", str(exc)
        words = {"sentence": lt.why, "changed": suggested[:MAX_CHANGES]}

    b = {"light": lt.colour, "why": lt.why, "sentence": words["sentence"],
         "low_point": low, "changed": words["changed"], "decisions": dec,
         "books": bk, "accuracy": acc, "written_by": written_by,
         "period": period(today), "made_on": today.isoformat(),
         "forecast_partial": bool(cf.get("partial"))}
    b["body"] = render(b)
    # The whole text against the figures it was written from, the parts the
    # engine wrote included: a figure in the brief nobody gave it is a bug
    # whoever wrote it.
    corpus = verify.Corpus()
    corpus.add(json.dumps({**facts, "forslag": suggested}, ensure_ascii=False),
               "grunnlaget")
    corpus.add(json.dumps(cf.get("weeks") or [], ensure_ascii=False), "prognosen")
    b["unverified"] = [verify.fmt(v) for v in
                       verify.check(b["body"], corpus).get("unverified", [])]
    if problem:
        b["problem"] = problem
    return b


# ------------------------------------------------------------ the archive
def save(b: dict) -> int:
    with db.tx() as conn:
        return conn.execute(
            "INSERT INTO reports (company_id, kind, period, written_at, verdict, "
            "body, facts, status, job_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, 'final', ?) "
            "RETURNING id",
            (db.company_id(), KIND, b["period"], db.now(), b["light"], b["body"],
             db.dumps({k: v for k, v in b.items() if k != "body"}),
             db.job_run.get())).fetchone()[0]


def latest(today: date | None = None) -> dict | None:
    """The newest brief, and whether it is this week's."""
    today = today or date.today()
    with db.read() as conn:
        r = conn.execute(
            "SELECT * FROM reports WHERE company_id = ? AND kind = ? "
            "ORDER BY written_at DESC, id DESC LIMIT 1",
            (db.company_id(), KIND)).fetchone()
    if r is None:
        return None
    facts = db.loads(r["facts"], {})
    return {**facts, "id": r["id"], "body": r["body"], "written_at": r["written_at"],
            "status": r["status"], "current": r["period"] == period(today)}


async def write(today: date | None = None) -> dict:
    """Build this week's brief and keep it. Returns it as stored."""
    b = await build(today)
    rid = save(b)
    log.info("Mandagsbrevet for %s skrevet: %s, %d beslutning(er), %s",
             b["period"], LIGHTS[b["light"]], b["decisions"]["count"], b["written_by"])
    return {**b, "id": rid}
