"""The health check, and the clean-up list for the regnskapsfører.

What the Cash tier sells on to a new customer: two or three pages that say
where the company stands — cash and how long it lasts, the payroll share over
the year, who owes what and how much rides on a few customers, VAT and tax,
and what in the books cannot be trusted yet. Beside it, the list of what the
regnskapsfører has to fix, in their own terms, ready to send.

**The engine gathers; the model writes.** Every figure here is computed
without a model, from what the forecast, the commitments, the overview and
the pre-flight already fetch. The `helsesjekk` job turns each section's facts
into a few plain sentences for the CEO, and each clean-up item into an
instruction a regnskapsfører can act on, through the shared core so `verify`
reads it. The whole text is checked again against the facts before it is
kept. Without the model, both are written from the figures in the engine's
own words — plainer, but never missing.

**Kept.** Both are rows in `reports` (`health_check`, `cleanup_list`), dated,
with the facts they were written from; a new run is a new row. A card puts
the list in front of the CEO with the text ready to copy, and replaces the
card from the run before.
"""
import asyncio
import json
import logging
from datetime import date

import cards
import cashflow
import commitments
import company
import config
import db
import overview
import preflight
import verify
from agent import core

log = logging.getLogger("cfo.health")

KINDS = {"health": "health_check", "cleanup": "cleanup_list"}
CARD_PREFIX = "cleanup:"
MAX_TOKENS = 8000
SECTIONS = (("cash", "Penger og hvor lenge de rekker"),
            ("payroll", "Lønnsandelen gjennom året"),
            ("receivables", "Kundefordringer og avhengighet av få kunder"),
            ("tax", "Moms og skatt"),
            ("gaps", "Det vi ikke kan stole på ennå"))
BUCKETS = ((1, 30), (31, 60), (61, 90), (91, None))
MONTHS = ("januar", "februar", "mars", "april", "mai", "juni", "juli",
          "august", "september", "oktober", "november", "desember")


class HealthError(RuntimeError):
    """Nothing to write from. The message is for the front page."""


def _kr(v) -> str:
    return f"{round(v):,}".replace(",", " ")


def _pct(part, whole) -> float | None:
    return round(part / whole * 100, 1) if whole else None


# ------------------------------------------------------------ the facts
def _cash(cf: dict | None, com: dict, rules: dict) -> dict:
    floor = rules["likviditetsgulv_kr"]
    bank = (cf or {}).get("bank") or {}
    low_c = (cf or {}).get("low_committed") or {}
    low_e = (cf or {}).get("low_expected") or {}
    under = cashflow.below_floor(cf, floor["value"]) if cf else None
    dry = (cf or {}).get("goes_negative_committed")
    return {
        "penger_i_banken_kr": com.get("bank"),
        "bokfort_bank_kr": bank.get("booked"),
        "banken_foran_bokene_kr": bank.get("adjustment"),
        "fritt_naa_kr": com.get("free_now"),
        "fritt_etter_alt_kr": com.get("free_all"),
        "gulv_kr": floor["value"], "gulv_hvor_fra": company.said(floor),
        "laveste_bundne": low_c and {"uke": low_c.get("label"), "fra": low_c.get("start"),
                                     "kr": low_c.get("amount")},
        "laveste_forventede": low_e and {"uke": low_e.get("label"), "fra": low_e.get("start"),
                                         "kr": low_e.get("amount")},
        "forste_uke_under_gulvet": under,
        "bundne_linje_under_null": dry,
        "uker_i_prognosen": len((cf or {}).get("weeks") or []),
    }


def _payroll(ov: dict, rules: dict, today: date) -> dict:
    rows = []
    for m in ov.get("monthly") or []:
        rev, wages = m.get("revenue"), m.get("wages")
        if rev is None or wages is None:
            continue
        rows.append({"maned": m.get("month"), "omsetning_kr": rev, "lonn_kr": wages,
                     "lonnsandel_pct": _pct(wages, rev) if rev > 0 else None})
    # The month running now is not finished; it would read as a collapse.
    rows = rows[:max(0, today.month - 1)]
    target = rules["lonnsandel_mal_pct"]
    k = ov.get("kpis") or {}
    return {"per_maned": rows, "hittil_i_aar_pct": k.get("lonnsandel_pct"),
            "budsjett_pct": k.get("lonnsandel_budsjett_pct"),
            "mal_pct": target["value"], "mal_hvor_fra": company.said(target)}


def _receivables(ov: dict, cf: dict | None, today: date) -> dict:
    ar = (cf or {}).get("ar_open") or []
    total = round(sum(i["amount"] for i in ar), 2)
    buckets = []
    for lo, hi in BUCKETS:
        items = []
        for i in ar:
            try:
                late = (today - date.fromisoformat(i["due"])).days
            except (KeyError, TypeError, ValueError):
                continue
            if late >= lo and (hi is None or late <= hi):
                items.append(i)
        buckets.append({"dager_forfalt": f"{lo}–{hi}" if hi else f"over {lo - 1}",
                        "antall": len(items),
                        "kr": round(sum(i["amount"] for i in items), 2)})
    by: dict[str, float] = {}
    for i in ar:
        by[i.get("name") or "Ukjent"] = by.get(i.get("name") or "Ukjent", 0.0) + i["amount"]
    top = sorted(by.items(), key=lambda x: -x[1])[:3]
    return {"kundefordringer_kr": (ov.get("kpis") or {}).get("kundefordringer"),
            "apne_fakturaer": len(ar), "apne_fakturaer_kr": total,
            "forfalt": buckets,
            "storste_kunder": [{"kunde": n, "kr": round(v, 2), "andel_pct": _pct(v, total)}
                               for n, v in top],
            "tre_storste_andel_pct": _pct(sum(v for _, v in top), total),
            "komplett": bool((cf or {}).get("ar_complete", True))}


def _tax(com: dict) -> dict:
    return {"poster": [{"hva": i.get("label"), "kr": i.get("amount"), "forfall": i.get("due"),
                        "dager_til": i.get("days"), "anslatt": bool(i.get("estimated"))}
                       for i in com.get("items") or []],
            "innen_30_dager_kr": (com.get("totals") or {}).get("within_30"),
            "innen_90_dager_kr": (com.get("totals") or {}).get("within_90"),
            "senere_kr": (com.get("totals") or {}).get("later"),
            "merknader": com.get("anomalies") or []}


def cleanup_items(pf: dict | None, cf: dict | None) -> list[dict]:
    """What the regnskapsfører has to fix, from the checks, most serious first."""
    items = []
    for c in sorted((pf or {}).get("checks") or [],
                    key=lambda c: c.get("status") != "warn"):
        if c.get("status") not in ("warn", "note"):
            continue
        items.append({"id": c["id"], "tema": c.get("label"), "funnet": c.get("headline"),
                      "detalj": c.get("detail") or "", "alvor": c["status"]})
    bank = (cf or {}).get("bank") or {}
    if bank.get("lines"):
        items.append({"id": "bank_unbooked", "tema": "Banklinjer som ikke er bokført",
                      "funnet": f"{bank['lines']} banklinjer ligger ubokført i "
                                f"bankavstemmingen" + (f", siste {bank['latest']}"
                                                       if bank.get("latest") else "") + ".",
                      "detalj": "", "alvor": "warn"})
    for n, sentence in enumerate(bank.get("unknown") or [], 1):
        items.append({"id": f"reconciliation_{n}", "tema": "Bankavstemming",
                      "funnet": sentence, "detalj": "", "alvor": "warn"})
    reg = (cf or {}).get("register") or {}
    if reg.get("no_org"):
        names = reg["no_org"]
        items.append({"id": "register_no_org", "tema": "Kunder uten organisasjonsnummer",
                      "funnet": f"{len(names)} kunde(r) med åpne fakturaer har ikke "
                                f"organisasjonsnummer i Tripletex, og kan derfor ikke "
                                f"sjekkes mot konkurs i Brønnøysund: {', '.join(names)}.",
                      "detalj": "", "alvor": "note"})
    for n, u in enumerate(reg.get("unclear") or [], 1):
        items.append({"id": f"register_{n}", "tema": "Kunde i Enhetsregisteret",
                      "funnet": f"{u['name']} (org.nr. {u['org']}) {u['said']}. Sjekk om "
                                f"kunden er fusjonert eller har fått nytt nummer, og rett "
                                f"kundekortet i Tripletex.",
                      "detalj": "", "alvor": "note"})
    for n, warning in enumerate((cf or {}).get("warnings") or [], 1):
        items.append({"id": f"forecast_{n}", "tema": "Fakturaer i fremmed valuta",
                      "funnet": warning, "detalj": "", "alvor": "note"})
    return items


def _gaps(pf: dict | None, cf: dict | None, failed: list[str]) -> dict:
    bank = (cf or {}).get("bank") or {}
    checks = (pf or {}).get("checks") or []
    return {"tilstand": (pf or {}).get("condition") or "ukjent",
            "merknader": [c.get("headline") for c in checks if c.get("status") in ("warn", "note")],
            "ikke_kontrollert": [c.get("label") for c in checks if c.get("status") == "unavailable"],
            "bankfeeden_har_stoppet": bool(bank.get("stale")),
            "bankfeed_siste_dag": bank.get("latest"),
            "kunne_ikke_hentes": failed}


async def facts(today: date | None = None) -> dict:
    """Everything the two documents are written from. No model."""
    today = today or date.today()
    ov, com, cf, pf = await asyncio.gather(
        overview.cached(), commitments.cached(), cashflow.cached(), preflight.cached(),
        return_exceptions=True)
    failed = [n for n, x in (("nøkkeltallene", ov), ("forpliktelsene", com),
                             ("prognosen", cf), ("kontrollene", pf)) if isinstance(x, Exception)]
    if len(failed) == 4:
        raise HealthError("Ingen tall kunne hentes fra Tripletex, så helsesjekken ble "
                          "ikke laget.")
    ov = {} if isinstance(ov, Exception) else ov
    com = {} if isinstance(com, Exception) else com
    cf = None if isinstance(cf, Exception) else cf
    pf = None if isinstance(pf, Exception) else pf
    rules = cashflow.rules(cf)
    return {"selskap": config.COMPANY_NAME, "dato": today.isoformat(),
            "seksjoner": {"cash": _cash(cf, com, rules), "payroll": _payroll(ov, rules, today),
                          "receivables": _receivables(ov, cf, today), "tax": _tax(com),
                          "gaps": _gaps(pf, cf, failed)},
            "opprydding": cleanup_items(pf, cf)}


# ------------------------------------------------------------ the writing
PROMPT = """Du er finansdirektøren i {company}. Skriv helsesjekken for \
selskapet — det daglig leder får når selskapet er koblet til, og så en gang i \
måneden — og oppryddingslisten til regnskapsføreren.

Grunnlaget, regnet ut her i dag:
{facts}

Svar med JSON og ingenting annet:
{{"summary": "<to-tre setninger: hvordan selskapet står, det viktigste først>",
  "sections": {{"cash": "...", "payroll": "...", "receivables": "...", "tax": "...", "gaps": "..."}},
  "cleanup_intro": "<én-to setninger til regnskapsføreren om hva listen er>",
  "cleanup": [{{"id": "<id fra opprydding>", "text": "<hva som må gjøres>"}}]}}

Hver seksjon: tre til seks setninger til en daglig leder som ikke er \
regnskapsfører. Si hva tallene betyr for ham, ikke bare hva de er. Mål mot \
selskapets egne regler i grunnlaget; står det at en regel er antatt, si det. \
Står det ingenting om noe i grunnlaget, si at det ikke er kjent — ikke gjett.

Oppryddingslisten: ett punkt per element i `opprydding`, med samme id. Skriv \
til en regnskapsfører, med regnskapsord der det er presist: hva som er funnet, \
hvilken konto eller måned det gjelder, og hva som må gjøres. Kort og konkret.

Bruk bare tall som står i grunnlaget, slik de står. Ikke regn ut nye."""


HELSESJEKK = core.Job(
    name="helsesjekk", max_tokens=MAX_TOKENS, output="json",
    prompt_source="grunnlaget",
    schema=core.obj(
        summary=core.STR,
        sections=core.obj(cash=core.STR, payroll=core.STR, receivables=core.STR,
                          tax=core.STR, gaps=core.STR),
        cleanup_intro=core.STR,
        cleanup=core.array(core.obj(id=core.STR, text=core.STR))))


def _plain(f: dict) -> dict:
    """The documents in the engine's own words, from the facts only: what is
    kept when the model cannot write."""
    s = f["seksjoner"]
    c, p, r, t, g = s["cash"], s["payroll"], s["receivables"], s["tax"], s["gaps"]
    cash = [f"Det står {_kr(c['penger_i_banken_kr'])} kr i banken."] if c.get("penger_i_banken_kr") is not None else []
    if c.get("fritt_naa_kr") is not None:
        cash.append(f"Etter det som skal betales de neste 30 dagene er "
                    f"{_kr(c['fritt_naa_kr'])} kr fritt.")
    if c.get("laveste_bundne"):
        low = c["laveste_bundne"]
        cash.append(f"Laveste punkt de neste {c['uker_i_prognosen']} ukene er "
                    f"{low['uke'].lower()} med {_kr(low['kr'])} kr, mot et gulv på "
                    f"{_kr(c['gulv_kr'])} kr ({c['gulv_hvor_fra']}).")
    pay = []
    if p["per_maned"]:
        last = p["per_maned"][-1]
        pay.append(f"Lønnsandelen var {last['lonnsandel_pct']} % i {last['maned']}."
                   if last["lonnsandel_pct"] is not None else "")
    if p.get("hittil_i_aar_pct") is not None:
        pay.append(f"Hittil i år er den {p['hittil_i_aar_pct']} %.")
    pay.append(f"Målet er {p['mal_pct']} %." if p.get("mal_pct") is not None
               else "Selskapet har ikke satt et mål for lønnsandelen.")
    rec = [f"{r['apne_fakturaer']} fakturaer står åpne, til sammen "
           f"{_kr(r['apne_fakturaer_kr'])} kr."]
    late = [b for b in r["forfalt"] if b["antall"]]
    if late:
        rec.append("Forfalt: " + ", ".join(f"{b['antall']} på {b['dager_forfalt']} dager "
                                           f"({_kr(b['kr'])} kr)" for b in late) + ".")
    if r.get("tre_storste_andel_pct") is not None:
        rec.append(f"De tre største kundene står for {r['tre_storste_andel_pct']} % av det "
                   f"som er utestående.")
    tax = [f"{_kr(t['innen_30_dager_kr'])} kr i moms, skatt og avgifter forfaller innen "
           f"30 dager."] if t.get("innen_30_dager_kr") is not None else []
    tax += [f"{i['hva']}: {_kr(i['kr'])} kr, forfall {i['forfall']}." for i in t["poster"][:5]]
    gaps = (["Bøkene er ajour."] if not g["merknader"] else g["merknader"][:4])
    if g["ikke_kontrollert"]:
        gaps.append("Kunne ikke kontrolleres: " + ", ".join(g["ikke_kontrollert"]) + ".")
    return {"summary": "Helsesjekken er skrevet ut fra tallene alene denne gangen.",
            "sections": {"cash": " ".join(cash), "payroll": " ".join(x for x in pay if x),
                         "receivables": " ".join(rec), "tax": " ".join(tax),
                         "gaps": " ".join(gaps)},
            "cleanup_intro": "Dette er det vi har funnet i regnskapet som bør ryddes.",
            "cleanup": [{"id": i["id"], "text": f"{i['funnet']} {i['detalj']}".strip()}
                        for i in f["opprydding"]]}


def _words(f: dict, data: dict) -> dict:
    """The model's answer, with anything it left out filled from the engine.
    Clean-up points only for items that exist; every item gets one."""
    plain = _plain(f)
    sections = {k: (str((data.get("sections") or {}).get(k) or "").strip() or plain["sections"][k])
                for k, _ in SECTIONS}
    known = {i["id"] for i in f["opprydding"]}
    given = {str(c.get("id")): str(c.get("text") or "").strip()
             for c in data.get("cleanup") or [] if str(c.get("id")) in known}
    cleanup = [{"id": c["id"], "text": given.get(c["id"]) or c["text"]}
               for c in plain["cleanup"]]
    return {"summary": str(data.get("summary") or "").strip() or plain["summary"],
            "sections": sections,
            "cleanup_intro": str(data.get("cleanup_intro") or "").strip() or plain["cleanup_intro"],
            "cleanup": cleanup}


def render_health(w: dict, day: str) -> str:
    out = [f"Helsesjekk for {config.COMPANY_NAME}, {_date(day)}", "", w["summary"], ""]
    for key, title in SECTIONS:
        out += [title, w["sections"][key], ""]
    return "\n".join(out).rstrip()


def render_cleanup(w: dict, day: str) -> str:
    if not w["cleanup"]:
        return ""
    out = ["Hei,", "", w["cleanup_intro"], ""]
    out += [f"{n}. {c['text']}" for n, c in enumerate(w["cleanup"], 1)]
    out += ["", f"Listen er laget {_date(day)} fra tallene i Tripletex.", "", "Takk!"]
    return "\n".join(out)


def _date(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d.day}. {MONTHS[d.month - 1]} {d.year}"


# ------------------------------------------------------------ the archive
def _save(kind: str, day: str, body: str, facts_: dict) -> int:
    with db.tx() as conn:
        return conn.execute(
            "INSERT INTO reports (company_id, kind, period, written_at, body, facts, "
            "status, job_run_id) VALUES (?, ?, ?, ?, ?, ?, 'final', ?) RETURNING id",
            (db.company_id(), kind, day, db.now(), body, db.dumps(facts_),
             db.job_run.get())).fetchone()[0]


def latest() -> dict | None:
    """The newest health check and the clean-up list made with it."""
    with db.read() as conn:
        rows = {k: conn.execute(
            "SELECT * FROM reports WHERE company_id = ? AND kind = ? "
            "ORDER BY written_at DESC, id DESC LIMIT 1", (db.company_id(), kind)).fetchone()
            for k, kind in KINDS.items()}
    if rows["health"] is None:
        return None
    h = rows["health"]
    out = {**db.loads(h["facts"], {}), "id": h["id"], "body": h["body"],
           "written_at": h["written_at"], "made_on": h["period"]}
    c = rows["cleanup"]
    out["cleanup_text"] = c["body"] if c is not None and c["period"] == h["period"] else ""
    return out


async def write(today: date | None = None) -> dict:
    """Make both documents, keep them, and put the list in front of the CEO."""
    today = today or date.today()
    f = await facts(today)
    text = json.dumps(f, ensure_ascii=False, indent=1)
    written_by, problem = "model", None
    try:
        result = await core.complete(HELSESJEKK, PROMPT.format(
            company=config.COMPANY_NAME, facts=text))
        words = _words(f, result.data or {})
    except Exception as exc:  # noqa: BLE001 — the figures are the document
        log.exception("Helsesjekken ble skrevet uten modellen")
        written_by, problem, words = "engine", str(exc), _plain(f)

    day = today.isoformat()
    health_text, cleanup_text = render_health(words, day), render_cleanup(words, day)
    corpus = verify.Corpus()
    corpus.add(text, "grunnlaget")
    unverified = [verify.fmt(v) for v in
                  verify.check(f"{health_text}\n{cleanup_text}", corpus).get("unverified", [])]
    kept = {"written_by": written_by, "summary": words["summary"],
            "sections": [{"key": k, "title": t, "text": words["sections"][k]} for k, t in SECTIONS],
            "cleanup": words["cleanup"], "cleanup_intro": words["cleanup_intro"],
            "unverified": unverified, "facts": f, **({"problem": problem} if problem else {})}
    hid = _save(KINDS["health"], day, health_text, kept)
    if cleanup_text:
        _save(KINDS["cleanup"], day, cleanup_text, {"items": f["opprydding"]})

    key = f"{CARD_PREFIX}{day}"
    # The list from the run before is out of date the moment this one exists —
    # an earlier run today included, whose text the new card would otherwise
    # be refused as a repeat of.
    replaced = cards.resolve_gone(CARD_PREFIX, set())
    card = None
    if cleanup_text:
        card = cards.propose(
            title=f"Send oppryddingslisten til regnskapsfører ({len(words['cleanup'])} "
                  f"punkt{'er' if len(words['cleanup']) != 1 else ''})",
            body="Helsesjekken fant det som står i listen. Kopier teksten og send den "
                 "til regnskapsføreren, så blir tallene du får fra meg riktigere.",
            urgency="medium", kind="cleanup", draft_subject="Opprydding i regnskapet",
            draft_text=cleanup_text, key=key,
            options=[{"label": "Sendt", "effect": "approve"},
                     {"label": "Vent en uke", "effect": "snooze", "days": 7},
                     {"label": "Ikke nå", "effect": "dismiss"}])
    log.info("Helsesjekk %s skrevet (%s): %d punkter til regnskapsfører%s", day,
             written_by, len(words["cleanup"]), f", {len(unverified)} tall uten kilde"
             if unverified else "")
    return {"id": hid, "made_on": day, "written_by": written_by, "problem": problem,
            "cleanup": len(words["cleanup"]), "card": card and card["id"],
            "replaced": replaced, "unverified": unverified}
