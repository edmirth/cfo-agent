"""The morning watch: what the CEO needs to see, prepared before he asks.

The playbook's service is push, not pull — "act, don't just answer", alerts
"only when a threshold is crossed; always with a suggested action", and quiet
when things are fine. Every working morning, after the deck is rebuilt, this
looks again.

**The engine decides what crossed a line; the model decides what to do about
it.** The detectors here are arithmetic on figures already fetched, measured
against the company's own rulebook. Each crossing is a *candidate* with a
fixed key. The model — the `vakt` job on the shared core — is shown the
candidates, the open findings and today's figures, and may do four things,
each a tool of its own and nothing else:

- raise a card for a candidate, with the suggested action and its draft;
- open a finding for a candidate worth watching that has no action yet — two
  a morning at most;
- set a candidate aside, with the reason (a quarterly bill is not unusual);
- close an open finding that no longer holds, with the figure that settles it.

It cannot raise anything that is not a candidate, so it cannot alert below a
threshold. Every number in what it writes is checked by `verify` against the
figures it was given before anything is stored; a number with no source is
refused back to it with the reason, and it tries again or leaves it.

**Never twice.** A candidate it has dealt with is recorded in `watch_seen` and
not put to it again; the deck itself refuses a key already open, snoozed or
dismissed. A watch card whose condition has gone is closed by the engine as
resolved, the way the derived cards are.

**Quiet costs nothing.** With no new candidate, and no open finding due for
review, no model is called.

Two alerts the playbook lists are already raised every morning without a
model — cash below the floor and late customers (`cards.py`) — so they are not
candidates here. The ones added here: VAT and tax money being spent as
operating cash, and an unusual cost.
"""
import asyncio
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import cards
import cashflow
import commitments
import company
import config
import db
import job_runs
import memory
import overview
import preflight
import verify
from agent import core

log = logging.getLogger("cfo.watch")

JOB = "vakt"
PREFIX = "watch:"
MAX_FINDINGS = 2              # a morning; agreed with the CEO
REVIEW_EVERY_DAYS = 7         # open findings are looked at again at least weekly
PRIOR_MONTHS = 6              # the usual level of a cost is its average over these
MIN_PRIOR_MONTHS = 3          # fewer than this, and there is no usual level yet
MAX_TOKENS = 4000

TOOLS = frozenset({"watch_card", "watch_finding", "watch_skip", "watch_close_finding"})


def _kr(v) -> str:
    return f"{round(v):,}".replace(",", " ")


# ------------------------------------------------------------- the detectors
def vat_candidate(com: dict, rules: dict) -> dict | None:
    """VAT and tax money spent as operating cash: the bank does not cover what
    falls due to the state and staff within 30 days."""
    free_now = com.get("free_now")
    if free_now is None or free_now >= 0:
        return None
    short = round(-free_now, 2)
    minimum = rules["varsel_minimum_kr"]["value"]
    if short < minimum:
        return None
    near = [i for i in com.get("items") or [] if i.get("days", 999) <= commitments.NEAR_DAYS]
    first_due = min((i["due"] for i in near), default=com.get("as_of"))
    return {
        "key": f"{PREFIX}vat:{first_due}", "kind": "vat", "amount": short,
        "what": "Pengene i banken dekker ikke det som skal betales til staten og "
                "de ansatte de neste 30 dagene: momsen og skattene er brukt i driften.",
        "figures": {"bank_kr": com.get("bank"),
                    "forfaller_innen_30_dager_kr": (com.get("totals") or {}).get("within_30"),
                    "mangler_kr": short,
                    "forste_forfall": first_due,
                    "poster": [{"hva": i.get("label"), "kr": i.get("amount"),
                                "forfall": i.get("due")} for i in near]},
        "rule": f"varsel over {_kr(minimum)} kr ({company.said(rules['varsel_minimum_kr'])})",
    }


def cost_candidates(ov: dict, rules: dict, today: date) -> list[dict]:
    """Cost accounts last month well above their usual level this year."""
    ca = ov.get("cost_accounts") or {}
    months = ca.get("months") or []
    last = today.month - 1
    if last < 1 or last not in months:
        return []                      # January: last month is last year's
    i = months.index(last)
    prior_idx = [j for j, m in enumerate(months) if m is not None and m < last][-PRIOR_MONTHS:]
    if len(prior_idx) < MIN_PRIOR_MONTHS:
        return []
    pct_rule, min_rule = rules["kostnadsavvik_pct"], rules["varsel_minimum_kr"]
    pct, minimum = pct_rule["value"], min_rule["value"]
    out = []
    for acct in ca.get("accounts") or []:
        flows = acct.get("flows") or []
        if acct.get("account") is None or i >= len(flows):
            continue
        now = flows[i] or 0.0
        usual = sum((flows[j] or 0.0) for j in prior_idx) / len(prior_idx)
        diff = now - usual
        if now <= 0 or diff < minimum:
            continue
        above = None if usual <= 0 else diff / usual * 100
        if above is not None and above <= pct:
            continue
        month = f"{today.year}-{last:02d}"
        out.append({
            "key": f"{PREFIX}cost:{acct['account']}:{month}", "kind": "cost",
            "amount": round(diff, 2),
            "what": f"Konto {acct['account']} {acct.get('name') or ''} var uvanlig "
                    f"høy forrige måned.".replace("  ", " "),
            "figures": {"konto": acct["account"], "navn": acct.get("name"),
                        "maned": month, "forrige_maned_kr": round(now, 2),
                        "vanlig_niva_kr": round(usual, 2),
                        "over_vanlig_kr": round(diff, 2),
                        "over_vanlig_pct": None if above is None else round(above, 1),
                        "maneder_i_snittet": len(prior_idx)},
            "rule": (f"over {pct} % ({company.said(pct_rule)}) og minst "
                     f"{_kr(minimum)} kr ({company.said(min_rule)}) over snittet "
                     f"for månedene før i år"),
        })
    out.sort(key=lambda c: -c["amount"])
    return out


# ------------------------------------------------------------- the record
def seen() -> set[str]:
    with db.read() as conn:
        return {r[0] for r in conn.execute(
            "SELECT key FROM watch_seen WHERE company_id = ?", (db.company_id(),))}


def _record(key: str, outcome: str, ref: str | None = None,
            reason: str | None = None) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO watch_seen (company_id, key, outcome, ref, "
            "reason, seen_on, job_run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (db.company_id(), key, outcome, ref, reason, date.today().isoformat(),
             db.job_run.get()))


def _review_due(now: datetime | None = None) -> bool:
    """Whether the open findings are due for a look: a week since the watch
    last finished a run with the model."""
    runs = [r for r in job_runs.recent(JOB, 20) if r["status"] in ("ok", "partial")]
    if not runs:
        return True
    last = datetime.fromisoformat(runs[0]["started_at"])
    now = now or datetime.now(timezone.utc)
    return now - last >= timedelta(days=REVIEW_EVERY_DAYS)


# ------------------------------------------------------------- one run
@dataclass
class Run:
    """What one morning's watch may act on, and what it did. The tools read
    this; outside a run they refuse."""
    candidates: dict[str, dict]
    findings: set[str]
    corpus: verify.Corpus
    done: dict[str, list] = field(default_factory=lambda: {
        "cards": [], "findings": [], "skipped": [], "closed": [], "refused": []})


_run: ContextVar[Run | None] = ContextVar("watch_run", default=None)


def _unsourced(*texts: str) -> list[str]:
    run = _run.get()
    found = verify.check(" ".join(t for t in texts if t), run.corpus)
    return [verify.fmt(v) for v in found.get("unverified", [])]


def _refuse(run: Run, what: str, bad: list[str]) -> str:
    run.done["refused"].append({"what": what, "unsourced": bad})
    return (f"Not stored: {', '.join(bad)} is not in grunnlaget. Use only figures "
            f"exactly as grunnlaget gives them, or leave the number out.")


def tool(name: str, args: dict) -> str:
    """Run one of the watch's tools. Called from `agent.tools.run`."""
    run = _run.get()
    if run is None:
        return "This tool works only in the morning watch."

    if name == "watch_close_finding":
        fid = (args.get("finding_id") or "").strip()
        outcome = (args.get("outcome") or "").strip()
        if fid not in run.findings:
            return f"{fid} is not an open finding in grunnlaget."
        if not outcome:
            return "Say in `outcome` how it ended, with the figure that settles it."
        bad = _unsourced(outcome)
        if bad:
            return _refuse(run, fid, bad)
        rec = memory.resolve_finding(fid, outcome, "resolved")
        run.findings.discard(fid)
        run.done["closed"].append(rec["id"])
        return f"{rec['id']} closed."

    key = (args.get("candidate") or "").strip()
    cand = run.candidates.get(key)
    if cand is None:
        return (f"{key or 'That'} is not a candidate this morning. You may only act "
                f"on the candidates in grunnlaget.")

    if name == "watch_skip":
        reason = (args.get("reason") or "").strip()
        if not reason:
            return "Say in `reason` why it needs nothing."
        _record(key, "skipped", reason=reason)
        run.candidates.pop(key)
        run.done["skipped"].append(key)
        return f"{key} set aside."

    if name == "watch_finding":
        if len(run.done["findings"]) >= MAX_FINDINGS:
            return (f"No more findings this morning ({MAX_FINDINGS} is the limit). "
                    f"Raise a card, set it aside, or leave it for tomorrow.")
        statement = (args.get("statement") or "").strip()
        bad = _unsourced(args.get("topic", ""), statement)
        if bad:
            return _refuse(run, key, bad)
        rec = memory.add_finding(
            topic=args.get("topic") or cand["kind"],
            severity=args.get("severity") if args.get("severity") in ("low", "medium", "high")
            else "medium",
            statement=statement, metric=cand["kind"], value=cand.get("amount"))
        _record(key, "finding", ref=rec["id"])
        run.candidates.pop(key)
        run.done["findings"].append(rec["id"])
        return f"Opened {rec['id']}."

    if name == "watch_card":
        title, body = (args.get("title") or "").strip(), (args.get("body") or "").strip()
        if not title or not body:
            return "A card needs a `title` and a `body`."
        bad = _unsourced(title, body, args.get("draft_subject", ""),
                         args.get("draft_text", ""))
        if bad:
            return _refuse(run, key, bad)
        figures = cand.get("figures") or {}
        evidence = [{"label": k.replace("_", " "), "value": str(v)}
                    for k, v in figures.items() if not isinstance(v, (list, dict)) and v is not None]
        evidence.append({"label": "Regel", "value": cand["rule"]})
        rec = cards.propose(
            title=title, body=body, urgency=args.get("urgency", "medium"),
            kind=cand["kind"], options=args.get("options"),
            draft_subject=args.get("draft_subject", ""),
            draft_text=args.get("draft_text", ""), evidence=evidence, key=key,
            amount=cand.get("amount"))
        if rec is None:
            _record(key, "card")
            run.candidates.pop(key)
            return "Already on the deck, or dismissed by the CEO. Nothing new raised."
        _record(key, "card", ref=rec["id"])
        run.candidates.pop(key)
        run.done["cards"].append(rec["id"])
        return f"Card {rec['id']} is on the deck."

    return f"Unknown watch tool {name}."


PROMPT = """Du er finansdirektøren i {company}, og dette er morgenvakten: \
ingen har spurt, men du ser over tallene før daglig leder gjør det.

Grunnlaget, regnet ut her i dag:
{facts}

`kandidater` er det motoren har funnet som har krysset en terskel i selskapets \
egne regler. Ta stilling til hver av dem, med ett verktøy:

- `watch_card`: noe han bør gjøre. Skriv tittelen med tallet i, og to-tre \
setninger om hva det betyr for ham og hvorfor nå. Er handlingen en melding, \
skriv den ferdig i `draft_text`. Gi to eller tre knapper.
- `watch_finding`: verdt å følge med på, men uten noe å gjøre ennå. Høyst \
{max_findings} i dag.
- `watch_skip`: trenger ingenting, med grunnen — for eksempel en kvartalsvis \
eller årlig regning som er normal for den måneden.

`apne_funn` er det du har notert tidligere. Lukk med `watch_close_finding` de \
som ikke lenger stemmer etter tallene i grunnlaget, og si hvilket tall som viser \
det. Står det ikke noe i grunnlaget som avgjør et funn, la det stå.

Bruk bare tall som står i grunnlaget, slik de står. Ikke regn ut nye. Skriv på \
norsk, uten fagord, til en daglig leder som ikke er regnskapsfører. Når du er \
ferdig, svar med én linje om hva du gjorde."""


VAKT = core.Job(name=JOB, tools=TOOLS, max_tokens=MAX_TOKENS,
                prompt_source="grunnlaget")


def _figures(ov: dict, com: dict, cf: dict | None, pf: dict | None, rules: dict) -> dict:
    k = ov.get("kpis") or {}
    low = (cf or {}).get("low_committed") or {}
    return {
        "nokkeltall": {key: k.get(key) for key in (
            "omsetning", "driftsresultat", "driftsmargin_pct", "lonnsandel_pct",
            "bank", "kundefordringer", "likviditetsgrad", "egenkapitalandel_pct")},
        "fritt": {"bank_kr": com.get("bank"), "fritt_naa_kr": com.get("free_now"),
                  "fritt_etter_alt_kr": com.get("free_all"),
                  "forfaller_innen_30_dager_kr": (com.get("totals") or {}).get("within_30")},
        "prognose": {"laveste_bundne_uke": low.get("label"),
                     "laveste_bundne_kr": low.get("amount"),
                     "gulv_kr": rules["likviditetsgulv_kr"]["value"]} if cf else None,
        "bokene": ({"tilstand": pf.get("condition"),
                    "merknader": [c["headline"] for c in pf.get("checks") or []
                                  if c.get("status") in ("warn", "note")]} if pf else None),
    }


async def run(today: date | None = None) -> dict:
    """One morning's watch. Returns what it found and did."""
    today = today or date.today()
    ov, com, cf, pf = await asyncio.gather(
        overview.cached(), commitments.cached(), cashflow.cached(), preflight.cached(),
        return_exceptions=True)
    failed = [name for name, x in (("nøkkeltallene", ov), ("forpliktelsene", com),
                                    ("prognosen", cf), ("kontrollene", pf))
              if isinstance(x, Exception)]
    ov, com = ({} if isinstance(ov, Exception) else ov), ({} if isinstance(com, Exception) else com)
    cf = None if isinstance(cf, Exception) else cf
    pf = None if isinstance(pf, Exception) else pf
    rules = cashflow.rules(cf)

    found: list[dict] = []
    if com:
        vat = vat_candidate(com, rules)
        found += [vat] if vat else []
    if ov:
        found += cost_candidates(ov, rules, today)
    live = {c["key"] for c in found}

    # A watch card whose condition is gone closes itself — only when both
    # detectors could look, so a failed fetch is not read as "fixed".
    closed_cards = [] if (not com or not ov) else cards.resolve_gone(PREFIX, live)

    already = seen()
    new = {c["key"]: c for c in found if c["key"] not in already}
    open_findings = memory.open_findings() or []
    out = {"candidates": len(found), "new": len(new), "closed_cards": closed_cards,
           "failed": failed, "quiet": False}

    if not new and not (open_findings and _review_due()):
        out["quiet"] = True
        log.info("Morgenvakten: ingenting nytt%s", f" ({len(found)} kjent)" if found else "")
        return out

    facts = {"dato": today.isoformat(),
             "kandidater": [{"id": c["key"], "hva": c["what"], "tall": c["figures"],
                             "regel": c["rule"]} for c in new.values()],
             "apne_funn": [{"id": f.get("id"), "tema": f.get("topic"),
                            "sagt": f.get("statement"), "reist": f.get("opened"),
                            "malt": f.get("metric"), "verdi": f.get("value")}
                           for f in open_findings],
             "i_dag": _figures(ov, com, cf, pf, rules),
             "regler": {k: {"verdi": r["value"], "hvor_fra": company.said(r)}
                        for k, r in rules.items()}}
    text = json.dumps(facts, ensure_ascii=False, indent=1)
    corpus = verify.Corpus()
    corpus.add(text, "grunnlaget")
    state = Run(candidates=dict(new), findings={f.get("id") for f in open_findings},
                corpus=corpus)
    token = _run.set(state)
    try:
        await core.complete(VAKT, PROMPT.format(company=config.COMPANY_NAME,
                                                facts=text, max_findings=MAX_FINDINGS))
    finally:
        _run.reset(token)
    out.update({k: v for k, v in state.done.items()},
               left=sorted(state.candidates))
    log.info("Morgenvakten: %d kort, %d funn åpnet, %d lukket, %d satt til side, %d avvist",
             len(state.done["cards"]), len(state.done["findings"]),
             len(state.done["closed"]), len(state.done["skipped"]),
             len(state.done["refused"]))
    return out
