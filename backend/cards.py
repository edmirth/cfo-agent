"""Work the CFO has prepared, waiting for the CEO to say yes.

The chat box asks the owner to know what to ask. He does not — that is the
whole reason he needs a CFO. So the agent does the work first and leaves it as
a card: what it found, in plain words, with the draft already written and two
or three buttons. The CEO spends his morning tapping, not prompting.

A card is only honest if every button does what it says. This product does not
write to Tripletex and has no mail server, so nothing here sends an invoice,
posts a voucher or transfers money. What the buttons do is real but modest:
approving hands over a finished draft and records that it was approved,
deferring genuinely brings the card back on the day, and every decision is
written to the CFO's memory so the next conversation starts from it instead of
re-arguing it.

Cards come from two places:

- **Derived** — from the pre-flight, the commitments and the cash forecast.
  These need no model and appear on their own, which is what makes the deck
  fill up overnight rather than when someone asks.
- **Proposed by the agent** — during a conversation, through `propose_card`,
  when it finds something worth acting on and can draft the response.

Deduplicated on `key`, so the same overdue customer does not stack up a new
card every time the deck is rebuilt.
"""
import asyncio
import json
import logging
import os
import tempfile
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import cashflow
import config
import memory
import preflight

log = logging.getLogger("cfo.cards")

STORE = config.ROOT / "state" / "cards.json"
MAX_CLOSED = 200

_lock = threading.Lock()

# What a button is allowed to do. Anything not on this list would be a promise
# the product cannot keep.
EFFECTS = {
    "approve",    # yes: hand over the draft, mark it done, remember the decision
    "snooze",     # not now: bring it back on a named day
    "delegate",   # the CEO is handling it himself, off-system
    "dismiss",    # no, and do not raise it again
}


def _now() -> str:
    return date.today().isoformat()


def _load() -> dict:
    if not STORE.exists():
        return {"counter": 0, "cards": []}
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Kortene er ulesbare (%s); starter på nytt", exc)
        try:
            STORE.rename(STORE.with_suffix(".corrupt.json"))
        except OSError:
            pass
        return {"counter": 0, "cards": []}
    data.setdefault("counter", 0)
    data.setdefault("cards", [])
    return data


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STORE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _kr(v) -> str:
    if v is None:
        return "—"
    return f"{round(v):,}".replace(",", " ")


def _wake(cards: list[dict], today: date) -> bool:
    """Bring deferred cards back on their day. 'Wait a week' has to mean it."""
    changed = False
    for c in cards:
        if c.get("status") == "snoozed" and c.get("snooze_until"):
            try:
                if date.fromisoformat(c["snooze_until"]) <= today:
                    c["status"] = "open"
                    c["woke"] = today.isoformat()
                    changed = True
            except ValueError:
                continue
    return changed


def add(card: dict) -> dict | None:
    """Store a card unless its key is already live.

    Returns the stored card, or None when an open or deferred card already
    covers it — a deck that repeats itself is a deck nobody reads.
    """
    with _lock:
        data = _load()
        key = card.get("key")
        if key:
            for existing in data["cards"]:
                if existing.get("key") == key and existing.get("status") in (
                        "open", "snoozed"):
                    return None
                # Dismissed means "stop telling me this".
                if existing.get("key") == key and existing.get("status") == "dismissed":
                    return None
        data["counter"] += 1
        card = {**card, "id": f"K{data['counter']:03d}", "created": _now(),
                "status": "open"}
        data["cards"].append(card)
        _save(data)
    log.info("Kort %s laget: %s", card["id"], card.get("title", "")[:60])
    return card


def decide(card_id: str, option_id: str, note: str = "") -> dict:
    """Record what the CEO chose, and do what that choice actually means."""
    with _lock:
        data = _load()
        card = next((c for c in data["cards"]
                     if c["id"].upper() == card_id.upper()), None)
        if card is None:
            raise KeyError(f"Fant ikke kort {card_id}")
        option = next((o for o in card.get("options", [])
                       if o["id"] == option_id), None)
        if option is None:
            raise KeyError(f"Kortet {card['id']} har ikke valget {option_id}")

        effect = option.get("effect")
        card["decided"] = {"at": datetime.now().isoformat(timespec="seconds"),
                           "option": option_id, "label": option.get("label"),
                           "effect": effect, "note": note}
        if effect == "snooze":
            days = int(option.get("days") or 7)
            card["status"] = "snoozed"
            card["snooze_until"] = (date.today() + timedelta(days=days)).isoformat()
        elif effect == "dismiss":
            card["status"] = "dismissed"
        else:                                   # approve, delegate
            card["status"] = "done"
            card["closed"] = _now()

        closed = [c for c in data["cards"] if c["status"] in ("done", "dismissed", "resolved")]
        if len(closed) > MAX_CLOSED:
            drop = {id(c) for c in closed[: len(closed) - MAX_CLOSED]}
            data["cards"] = [c for c in data["cards"] if id(c) not in drop]
        _save(data)

    # The CFO should not re-argue something already settled, so the choice goes
    # into its memory as well as into the deck.
    try:
        memory.add_decision(
            f"{option.get('label')} — {card.get('title')}",
            context=f"Kort {card['id']}" + (f": {note}" if note else ""))
    except Exception:  # noqa: BLE001 — the decision itself is already saved
        log.exception("Kunne ikke skrive beslutningen til hukommelsen")
    return card


def deck(today: date | None = None) -> dict:
    """Everything waiting, most pressing first.

    `today` is for asking what the deck *would* look like on some other day.
    Waking a deferred card is a real event, so a hypothetical read is never
    allowed to write one back — otherwise checking what happens next week
    quietly makes it happen now.
    """
    hypothetical = today is not None
    today = today or date.today()
    with _lock:
        data = _load()
        if _wake(data["cards"], today) and not hypothetical:
            _save(data)
        cards = json.loads(json.dumps(data["cards"])) if hypothetical \
            else list(data["cards"])

    rank = {"high": 0, "medium": 1, "low": 2}
    open_cards = [c for c in cards if c.get("status") == "open"]
    open_cards.sort(key=lambda c: (rank.get(c.get("urgency"), 1),
                                   -(c.get("amount") or 0)))
    return {
        "as_of": today.isoformat(),
        "open": open_cards,
        "snoozed": [c for c in cards if c.get("status") == "snoozed"],
        "recent": [c for c in cards if c.get("status") in ("done", "dismissed", "resolved")][-8:],
    }


# ------------------------------------------------------------- the generators
# Derived cards need no model: they come straight out of the checks that
# already run. Thresholds keep the deck to things worth a morning's attention —
# a card for every small thing trains the CEO to ignore all of them.

LATE_DAYS = 14
LATE_AMOUNT = 10_000
CASH_FLOOR = 500_000


def _reminder_draft(invoices: list[dict], total: float) -> dict:
    lines = "\n".join(
        f"- Faktura {i.get('number') or '—'}, forfalt {i['due']}, "
        f"{_kr(i['amount'])} kr" for i in invoices)
    return {
        "kind": "e-post",
        "to": next((i.get("email") for i in invoices if i.get("email")), ""),
        "subject": f"Påminnelse – forfalte fakturaer fra {config.COMPANY_NAME}",
        "text": (
            f"Hei,\n\n"
            f"Vi ser at følgende fakturaer står som ubetalte hos oss:\n\n"
            f"{lines}\n\n"
            f"Til sammen {_kr(total)} kr.\n\n"
            f"Er det noe som er uklart, eller har det skjedd noe med "
            f"faktureringen, så si fra — ellers setter vi pris på at beløpet "
            f"blir gjort opp.\n\n"
            f"Vennlig hilsen\n{config.COMPANY_NAME}"),
    }


def _collections(invoices: list[dict], today: date) -> list[dict]:
    """One card per customer who is materially late, with the chase written."""
    by: dict[str, list[dict]] = {}
    for inv in invoices:
        try:
            due = date.fromisoformat(inv["due"])
        except (ValueError, TypeError, KeyError):
            continue
        late = (today - due).days
        if late < LATE_DAYS:
            continue
        by.setdefault(inv["name"], []).append({**inv, "late": late})

    cards = []
    for customer, items in by.items():
        total = sum(i["amount"] for i in items)
        if total < LATE_AMOUNT:
            continue
        worst = max(i["late"] for i in items)
        cards.append({
            "key": f"collections:{customer}",
            "kind": "collections", "amount": total,
            "urgency": "high" if worst >= 30 or total >= 100_000 else "medium",
            "title": f"{customer} er {worst} dager på etterskudd med {_kr(total)} kr",
            "body": (f"{len(items)} faktura(er) har stått ubetalt i mer enn "
                     f"{LATE_DAYS} dager. Lønnen din går ut hver måned uansett, "
                     f"så det er dine penger som finansierer ventetiden."),
            "evidence": [{"label": f"Faktura {i.get('number') or '—'}",
                          "value": f"{_kr(i['amount'])} kr, forfalt {i['due']} "
                                   f"({i['late']} d siden)"} for i in items[:6]],
            "draft": _reminder_draft(items, total),
            "options": [
                {"id": "send", "label": "Send påminnelsen", "effect": "approve"},
                {"id": "wait", "label": "Vent en uke", "effect": "snooze", "days": 7},
                {"id": "call", "label": "Jeg ringer dem", "effect": "delegate"},
            ],
        })
    return cards


def _from_preflight(pf: dict) -> list[dict]:
    cards = []
    checks = {c["id"]: c for c in pf.get("checks", [])}

    revenue = checks.get("revenue_month")
    if revenue and revenue["status"] == "warn":
        cards.append({
            "key": f"invoicing:{pf.get('as_of', '')[:7]}",
            "kind": "invoicing", "urgency": "high", "amount": None,
            "title": "Månedens fakturering har ikke gått ut",
            "body": (revenue["headline"] + " Arbeidet er utført og lønnen er "
                     "bokført, men pengene er ikke bedt om ennå. Dette er den "
                     "enkleste kronen du henter inn denne uka."),
            "evidence": [{"label": "Kontroll", "value": revenue["headline"]}],
            "options": [
                {"id": "done", "label": "Fakturaene er sendt", "effect": "approve"},
                {"id": "week", "label": "Minn meg på fredag", "effect": "snooze", "days": 4},
                {"id": "mine", "label": "Jeg tar det selv", "effect": "delegate"},
            ],
        })

    inbox = checks.get("inbox")
    if inbox and inbox["status"] == "warn":
        cards.append({
            "key": f"vouchers:{pf.get('as_of', '')[:7]}",
            "kind": "bookkeeping", "urgency": "medium", "amount": None,
            "title": inbox["headline"],
            "body": ("Bokføringen er regnskapsførers jobb, ikke vår — men så "
                     "lenge bilagene ligger der, vet verken du eller jeg hva "
                     "som faktisk skal ut. Tallene mine er for snille til det "
                     "er gjort."),
            "evidence": [{"label": "Bilagsinnboks", "value": inbox["headline"]}],
            "draft": {
                "kind": "melding", "to": "", "subject": "Bilag til bokføring",
                "text": ("Hei,\n\nKan du få bokført bilagene som ligger i "
                         "innboksen? Jeg får ikke et riktig bilde av kostnadene "
                         "før de er inne.\n\nTakk!"),
            },
            "options": [
                {"id": "ask", "label": "Send til regnskapsfører", "effect": "approve"},
                {"id": "later", "label": "Vent en uke", "effect": "snooze", "days": 7},
                {"id": "known", "label": "Dette er under kontroll", "effect": "dismiss"},
            ],
        })

    for cid in ("ar_tie", "ap_tie", "ap_posting"):
        check = checks.get(cid)
        if check and check["status"] == "warn":
            cards.append({
                "key": f"reconcile:{cid}",
                "kind": "bookkeeping", "urgency": "medium", "amount": None,
                "title": check["label"] + " stemmer ikke",
                "body": check["headline"] + " " + (check.get("detail") or ""),
                "evidence": [{"label": check["label"], "value": check["headline"]}],
                "options": [
                    {"id": "ask", "label": "Be regnskapsfører se på det",
                     "effect": "approve"},
                    {"id": "later", "label": "Vent en uke", "effect": "snooze",
                     "days": 7},
                    {"id": "known", "label": "Dette er kjent", "effect": "dismiss"},
                ],
            })
    return cards


def _from_cashflow(cf: dict) -> list[dict]:
    low = cf.get("low_committed") or {}
    if low.get("amount") is None or low["amount"] > CASH_FLOOR:
        return []
    return [{
        "key": f"cash:{low.get('start')}",
        "kind": "cash", "urgency": "high", "amount": low["amount"],
        "title": (f"Tynnest i {low.get('label')}: {_kr(low['amount'])} kr igjen "
                  f"hvis ingenting nytt faktureres"),
        "body": ("Dette er gulvet — bare det som allerede er avtalt inn og ut. "
                 "Fakturerer du som vanlig ligger du høyere, men da er det "
                 "faktureringen som må skje i tide."),
        "evidence": [{"label": "Uke", "value": f"{low.get('label')} ({low.get('start')})"},
                     {"label": "Bundet saldo", "value": f"{_kr(low['amount'])} kr"}],
        "options": [
            {"id": "seen", "label": "Forstått", "effect": "approve"},
            {"id": "later", "label": "Følg opp om en uke", "effect": "snooze", "days": 7},
        ],
    }]


async def refresh(today: date | None = None) -> dict:
    """Rebuild the derived cards, then return the deck.

    Every source is optional: a check that cannot run should cost its own card,
    not the whole deck.
    """
    today = today or date.today()

    async def _try(coro, what):
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001
            log.warning("Kortkilde %s feilet: %s", what, exc)
            return None

    pf, cf = await asyncio.gather(
        _try(preflight.cached(), "preflight"),
        _try(cashflow.cached(), "cashflow"))

    candidates: list[dict] = []
    if pf:
        candidates += _from_preflight(pf)
    if cf:
        candidates += _from_cashflow(cf)
        # The forecast already fetched the open invoices; reusing them keeps
        # the deck and the forecast on the same figures.
        candidates += _collections(cf.get("ar_open") or [], today)

    reconcile(candidates, sources_ok=bool(pf and cf))
    return deck(today)


def reconcile(candidates: list[dict], sources_ok: bool) -> None:
    """Make the derived cards match what the checks say *now*.

    A card raised by a check is a claim about the present — "Skanska is 70
    days late on 99 449 kr". Left alone it goes stale two ways: the figures
    freeze at the moment it was written, and it stays open after the customer
    has paid. So a regenerated card refreshes the one already on the deck, and
    a card whose condition no longer produces a candidate is closed as
    resolved — distinct from anything the CEO decided. Agent-proposed cards
    are not touched; only the agent knows whether those still hold.

    When a source could not be read at all, nothing is closed: the absence of
    a candidate then means "unknown", not "fixed".
    """
    by_key = {c["key"]: c for c in candidates if c.get("key")}
    with _lock:
        data = _load()
        changed = False
        for card in data["cards"]:
            if card.get("source") != "auto" or card.get("status") not in ("open", "snoozed"):
                continue
            fresh = by_key.pop(card.get("key"), None)
            if fresh is not None:
                for field in ("title", "body", "amount", "urgency", "evidence",
                              "draft", "options"):
                    if field in fresh and fresh[field] != card.get(field):
                        card[field] = fresh[field]
                        changed = True
                card["refreshed"] = _now()
            elif sources_ok:
                card["status"] = "resolved"
                card["closed"] = _now()
                card["decided"] = {"at": datetime.now().isoformat(timespec="seconds"),
                                   "effect": "resolved", "label": "Løste seg selv",
                                   "note": "Kontrollen som laget kortet finner ikke "
                                           "lenger noe å melde."}
                changed = True
                log.info("Kort %s lukket: forholdet er borte", card["id"])
        if changed:
            _save(data)
    for card in by_key.values():
        add({**card, "source": "auto"})


# ------------------------------------------------- cards the agent proposes

MAX_OPTIONS = 4


def propose(title: str, body: str, urgency: str = "medium",
            kind: str = "other", options: list[dict] | None = None,
            draft_subject: str = "", draft_text: str = "",
            evidence: list[dict] | None = None, key: str = "") -> dict | None:
    """Validate and store a card the agent has prepared.

    The agent writes the words; it does not get to invent what a button does.
    Anything whose effect is not in EFFECTS is dropped rather than rendered as
    a control that quietly does nothing.
    """
    clean: list[dict] = []
    for i, opt in enumerate(options or []):
        effect = (opt.get("effect") or "").strip()
        label = (opt.get("label") or "").strip()
        if effect not in EFFECTS or not label:
            log.warning("Forkastet knapp uten gyldig effekt: %s", opt)
            continue
        entry = {"id": opt.get("id") or f"o{i + 1}", "label": label,
                 "effect": effect}
        if effect == "snooze":
            entry["days"] = int(opt.get("days") or 7)
        clean.append(entry)
        if len(clean) >= MAX_OPTIONS:
            break
    if not clean:
        clean = [{"id": "ok", "label": "Forstått", "effect": "approve"},
                 {"id": "later", "label": "Vent en uke", "effect": "snooze",
                  "days": 7}]

    card = {"key": key or f"agent:{title[:60]}", "kind": kind,
            "urgency": urgency if urgency in ("high", "medium", "low") else "medium",
            "amount": None, "title": title, "body": body,
            "evidence": evidence or [], "options": clean, "source": "agent"}
    if draft_text:
        card["draft"] = {"kind": "e-post", "to": "",
                         "subject": draft_subject or title, "text": draft_text}
    return add(card)


def briefing(today: date | None = None) -> str:
    """What is already waiting for the CEO, so the agent does not repeat it."""
    try:
        d = deck(today)
    except Exception:  # noqa: BLE001
        log.exception("Kortbriefen feilet")
        return ""
    if not (d["open"] or d["snoozed"] or d["recent"]):
        return ""

    out = ["## Det som allerede ligger til godkjenning\n",
           "Cards the CEO has waiting. He acts by tapping these, not by asking "
           "you — so do not re-raise what is already here, and do not propose a "
           "card for something the deck already covers. Refer to one by what it "
           "says, not by its id.\n"]
    if d["open"]:
        out.append("**Venter på ham**\n")
        out += [f"- `{c['id']}` {c['title']}" for c in d["open"]]
        out.append("")
    if d["snoozed"]:
        out.append("**Utsatt, kommer tilbake av seg selv**\n")
        out += [f"- `{c['id']}` {c['title']} — tilbake {c.get('snooze_until')}"
                for c in d["snoozed"]]
        out.append("")
    if d["recent"]:
        out.append("**Nylig avgjort** — treat these as settled:\n")
        out += [f"- {c['title']} → {(c.get('decided') or {}).get('label', '—')}"
                for c in d["recent"]]
        out.append("")
    out.append("When you find something worth acting on that is not here, and "
               "you can say what the CEO should do about it, raise it with "
               "`propose_card` and write the draft. A finding he has to turn "
               "into an action himself is half a finding.")
    return "\n".join(out)
