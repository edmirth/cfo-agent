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
import copy
import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import cashflow
import company
import config
import db
import memory
import preflight

log = logging.getLogger("cfo.cards")

# How long an approved card answers its check. "Send påminnelsen" is a promise
# to act, not proof the customer paid; still late two weeks on, it comes back.
FOLLOW_UP_DAYS = 14

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


# ---------------------------------------------------------------- storage
# The deck is stored in `cards`, one row per card, and every change to a card
# is appended to `card_events`. The logic below still works on the deck as a
# list of dicts — dedup, follow-ups and reconcile read across every card at
# once — so `_editing` loads it inside a write transaction and writes back what
# changed. The transaction holds the write lock from load to save, which is
# what the thread lock did, now across processes too. Nothing is deleted: the
# deck shows the latest closed cards, the database keeps them all.

# Card field -> column, for the ones that are not JSON.
COLUMNS = {"key": "key", "source": "source", "kind": "kind", "urgency": "urgency",
           "title": "title", "body": "body", "status": "status",
           "created": "created_on", "refreshed": "refreshed_on",
           "snooze_until": "snooze_until", "woke": "woke_on",
           "closed": "closed_on", "released": "released_on"}
JSON_COLUMNS = {"options": "[]", "draft": None, "evidence": "[]",
                "follow_up": None, "decided": None}


def _row(card: dict) -> dict:
    """A card as the columns store it."""
    out = {col: card.get(field) for field, col in COLUMNS.items()}
    out["source"] = out["source"] or "agent"
    out["urgency"] = out["urgency"] or "medium"
    out["status"] = out["status"] or "open"
    out["created_on"] = out["created_on"] or _now()
    out["amount_ore"] = db.to_ore(card.get("amount"))
    for field, empty in JSON_COLUMNS.items():
        value = card.get(field)
        out[field] = db.dumps(value) if value is not None else empty
    return out


def _card(r) -> dict:
    """A row as the rest of this module reads a card: the same dict as ever."""
    card = {"id": r["ref"], "amount": db.to_kr(r["amount_ore"])}
    for field, col in COLUMNS.items():
        if r[col] is not None or field in ("key", "kind", "body"):
            card[field] = r[col]
    for field in JSON_COLUMNS:
        if r[field] is not None:
            card[field] = db.loads(r[field])
    return card


def insert_row(conn, cid: int, card: dict, event: str = "created",
               actor: str = "system") -> None:
    """Store a new card, the run that raised it, and the event that brought it."""
    row = {**_row(card), "job_run_id": db.job_run.get()}
    cols = ["company_id", "ref", *row]
    card_id = conn.execute(
        f"INSERT INTO cards ({', '.join(cols)}) VALUES "
        f"({', '.join('?' * len(cols))}) RETURNING id",
        (cid, card["id"], *row.values())).fetchone()[0]
    _event(conn, cid, card_id, event, actor=actor, at=card.get("created"))


def _event(conn, cid: int, card_id: int, event: str, actor: str = "system",
           at: str | None = None, decided: dict | None = None) -> None:
    d = decided or {}
    conn.execute(
        "INSERT INTO card_events (company_id, card_id, at, event, option_id, "
        "effect, label, note, actor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (cid, card_id, at or db.now(), event, d.get("option"), d.get("effect"),
         d.get("label"), d.get("note"), actor))


def _events_for(before: dict, after: dict) -> list[tuple[str, str, dict | None]]:
    """What happened to a card between two states: (event, actor, decision)."""
    out = []
    if after.get("decided") != before.get("decided") and after.get("decided"):
        d = after["decided"]
        if d.get("effect") == "resolved":
            out.append(("resolved", "system", d))
        else:
            out.append(("decided", "ceo", d))
    if before.get("status") == "snoozed" and after.get("status") == "open":
        out.append(("woke", "system", None))
    if after.get("released") and not before.get("released"):
        out.append(("released", "system", None))
    if after.get("refreshed") != before.get("refreshed") and not out:
        out.append(("refreshed", "system", None))
    return out


def _read(conn) -> dict:
    cid = db.company_id()
    rows = conn.execute("SELECT * FROM cards WHERE company_id = ? ORDER BY id",
                        (cid,)).fetchall()
    counter = conn.execute("SELECT value FROM counters WHERE company_id = ? "
                           "AND series = 'cards'", (cid,)).fetchone()
    return {"counter": counter[0] if counter else 0,
            "cards": [_card(r) for r in rows]}


def _write(conn, data: dict, before: dict) -> None:
    """Write back every card that changed, with the events that changed it."""
    cid = db.company_id()
    old = {c["id"]: c for c in before["cards"]}
    ids = {r["ref"]: r["id"] for r in conn.execute(
        "SELECT id, ref FROM cards WHERE company_id = ?", (cid,))}
    # Updates before inserts: a card leaving the live set must make way for a
    # new one on the same key, or the unique index refuses the newcomer.
    fresh = []
    for card in data["cards"]:
        prev = old.get(card["id"])
        if prev is None:
            fresh.append(card)
            continue
        if _row(card) == _row(prev):
            continue
        row = _row(card)
        conn.execute(
            f"UPDATE cards SET {', '.join(f'{c} = ?' for c in row)} "
            f"WHERE company_id = ? AND ref = ?",
            (*row.values(), cid, card["id"]))
        for event, actor, decided in _events_for(prev, card):
            _event(conn, cid, ids[card["id"]], event, actor=actor,
                   at=(decided or {}).get("at"), decided=decided)
    for card in fresh:
        insert_row(conn, cid, card,
                   actor="agent" if card.get("source") == "agent" else "system")


@contextmanager
def _editing():
    """The deck, loaded under the write lock, written back on the way out."""
    with db.tx() as conn:
        data = _read(conn)
        before = copy.deepcopy(data)
        yield conn, data
        _write(conn, data, before)


def _load() -> dict:
    """The deck as it stands. A read: nothing is held."""
    with db.read() as conn:
        return _read(conn)


def _save(data: dict) -> None:
    """Write a deck back that was read with `_load`. Kept for the tests and
    for one-off repairs; the module itself edits through `_editing`."""
    with db.tx() as conn:
        _write(conn, data, _read(conn))


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


def _due_for_follow_up(card: dict, today: date | None = None) -> bool:
    try:
        closed = date.fromisoformat(card.get("closed") or "")
    except ValueError:
        return False
    return ((today or date.today()) - closed).days >= FOLLOW_UP_DAYS


def _answered_before(cards: list[dict], key: str | None) -> dict | None:
    """The approved card this one follows up, if the check outlived it."""
    if not key:
        return None
    held = [c for c in cards if c.get("key") == key and c.get("status") == "done"
            and c.get("source") == "auto" and not c.get("released")]
    return max(held, key=lambda c: c.get("closed") or "") if held else None


def _with_follow_up(card: dict, body: str) -> str:
    """Say what was already done. A follow-up that reads like a first notice
    asks the CEO to decide again what he decided two weeks ago."""
    f = card.get("follow_up")
    if not f:
        return body
    try:
        ago = (date.today() - date.fromisoformat(f.get("closed") or "")).days
        when = f"for {ago} dager siden"
    except ValueError:
        when = "tidligere"
    return (f"Oppfølging: du valgte «{f.get('label') or 'å ta det'}» {when}, "
            f"og det står fortsatt ved lag. " + body)


def add(card: dict) -> dict | None:
    """Store a card unless its key is already live.

    Returns the stored card, or None when an open, deferred, dismissed or
    still-standing approved card already covers it — a deck that repeats itself
    is a deck nobody reads.
    """
    with _editing() as (conn, data):
        key = card.get("key")
        if key:
            for existing in data["cards"]:
                if existing.get("key") == key and existing.get("status") in (
                        "open", "snoozed"):
                    return None
                # Dismissed means "stop telling me this".
                if existing.get("key") == key and existing.get("status") == "dismissed":
                    return None
                # Approved means "I'm on it". The check keeps firing until the
                # customer pays, so the card stays answered until it stops —
                # `reconcile` releases the key then — or until FOLLOW_UP_DAYS
                # have passed and it has not, when it comes back as a follow-up.
                if (existing.get("key") == key and existing.get("status") == "done"
                        and existing.get("source") == "auto"
                        and not existing.get("released")
                        and not _due_for_follow_up(existing)):
                    return None
            previous = _answered_before(data["cards"], key)
            if previous is not None:
                card = {**card, "follow_up": {
                    "of": previous["id"], "closed": previous.get("closed"),
                    "label": (previous.get("decided") or {}).get("label")}}
                card["body"] = _with_follow_up(card, card.get("body", ""))
        card = {**card, "id": db.next_ref(conn, "cards", "K"),
                "created": _now(), "status": "open"}
        data["cards"].append(card)
    log.info("Kort %s laget: %s", card["id"], card.get("title", "")[:60])
    return card


def decide(card_id: str, option_id: str, note: str = "") -> dict:
    """Record what the CEO chose, and do what that choice actually means."""
    with _editing() as (conn, data):
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

    # The CFO should not re-argue something already settled, so the choice goes
    # into its memory as well as into the deck.
    try:
        memory.add_decision(
            f"{option.get('label')} — {card.get('title')}",
            context=f"Kort {card['id']}" + (f": {note}" if note else ""),
            card=card["id"])
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
    if hypothetical:
        cards = copy.deepcopy(_load()["cards"])
        _wake(cards, today)
    else:
        with _editing() as (conn, data):
            _wake(data["cards"], today)
            cards = list(data["cards"])

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
# a card for every small thing trains the CEO to ignore all of them. They are
# the company's own rules, read from company.md through `company.rules()`, so
# a card and the brief can never disagree about where the floor is.


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


def _collections(invoices: list[dict], today: date,
                 rules: dict | None = None) -> list[dict]:
    """One card per customer who is materially late, with the chase written."""
    rules = rules or company.rules()
    days_rule, min_rule = rules["purring_etter_dager"], rules["varsel_minimum_kr"]
    late_days, minimum = days_rule["value"], min_rule["value"]
    by: dict[str, list[dict]] = {}
    for inv in invoices:
        try:
            due = date.fromisoformat(inv["due"])
        except (ValueError, TypeError, KeyError):
            continue
        late = (today - due).days
        if late < late_days:
            continue
        by.setdefault(inv["name"], []).append({**inv, "late": late})

    cards = []
    for customer, items in by.items():
        total = sum(i["amount"] for i in items)
        if total < minimum:
            continue
        worst = max(i["late"] for i in items)
        cards.append({
            "key": f"collections:{customer}",
            "kind": "collections", "amount": total,
            "urgency": "high" if worst >= 30 or total >= 100_000 else "medium",
            "title": f"{customer} er {worst} dager på etterskudd med {_kr(total)} kr",
            "body": (f"{len(items)} faktura(er) har stått ubetalt i {late_days} "
                     f"dager eller mer. Lønnen din går ut hver måned uansett, "
                     f"så det er dine penger som finansierer ventetiden."),
            "evidence": [{"label": f"Faktura {i.get('number') or '—'}",
                          "value": f"{_kr(i['amount'])} kr, forfalt {i['due']} "
                                   f"({i['late']} d siden)"} for i in items[:6]]
            # The rule that raised it, so a card the CEO thinks came too early
            # tells him where to change that.
            + [{"label": "Regel", "value": (
                f"purring etter {late_days} dager ({company.said(days_rule)}), "
                f"over {_kr(minimum)} kr ({company.said(min_rule)})")}],
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
            # The check judges the month that just closed, never the open one.
            "title": "Forrige måneds fakturering har ikke gått ut",
            "body": (revenue["headline"] + " Måneden er over, arbeidet er "
                     "utført og lønnen er betalt, men pengene er ikke bedt om "
                     "ennå. Dette er den enkleste kronen du henter inn denne uka."),
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


def _from_cashflow(cf: dict, rules: dict | None = None) -> list[dict]:
    low = cf.get("low_committed") or {}
    floor = (rules or cashflow.rules(cf))["likviditetsgulv_kr"]
    if low.get("amount") is None or low["amount"] >= floor["value"]:
        return []
    assumed = (f" Gulvet er {company.said(floor)}; sett deres eget i Selskapet "
               f"om det skal ligge et annet sted." if floor["assumed"] else "")
    return [{
        "key": f"cash:{low.get('start')}",
        "kind": "cash", "urgency": "high", "amount": low["amount"],
        "title": (f"Under gulvet i {low.get('label')}: {_kr(low['amount'])} kr "
                  f"igjen hvis ingenting nytt faktureres"),
        "body": (f"Gulvet er {_kr(floor['value'])} kr. Dette er den bundne "
                 f"linjen — bare det som allerede er avtalt inn og ut. "
                 f"Fakturerer du som vanlig ligger du høyere, men da er det "
                 f"faktureringen som må skje i tide." + assumed),
        "evidence": [{"label": "Uke", "value": f"{low.get('label')} ({low.get('start')})"},
                     {"label": "Bundet saldo", "value": f"{_kr(low['amount'])} kr"},
                     {"label": "Gulv", "value": f"{_kr(floor['value'])} kr "
                                                f"({company.said(floor)})"}],
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
        # Resolved once, against this forecast's wages, so every card in one
        # rebuild is measured against the same rules.
        rules = cashflow.rules(cf)
        candidates += _from_cashflow(cf, rules)
        # The forecast already fetched the open invoices; reusing them keeps
        # the deck and the forecast on the same figures.
        candidates += _collections(cf.get("ar_open") or [], today, rules)

    reconcile(candidates, sources_ok=True, unknown=_unknown(pf, cf))
    return deck(today)


# Which derived cards each check produces, by key prefix. A check that could
# not run says nothing about whether its cards still hold.
CHECK_KEYS = {"inbox": "vouchers:", "revenue_month": "invoicing:",
              "ar_tie": "reconcile:ar_tie", "ap_tie": "reconcile:ap_tie",
              "ap_posting": "reconcile:ap_posting"}


def _unknown(pf: dict | None, cf: dict | None) -> set[str]:
    """Key prefixes whose source did not answer this time."""
    unknown: set[str] = set()
    if not pf:
        unknown |= set(CHECK_KEYS.values())
    else:
        unknown |= {CHECK_KEYS[c["id"]] for c in pf.get("checks", [])
                    if c["status"] == "unavailable" and c["id"] in CHECK_KEYS}
    if not cf:
        unknown |= {"cash:", "collections:"}
    elif not cf.get("ar_complete", True):
        unknown.add("collections:")
    return unknown


def reconcile(candidates: list[dict], sources_ok: bool,
              unknown: set[str] | tuple = ()) -> None:
    """Make the derived cards match what the checks say *now*.

    A card raised by a check is a claim about the present — "Skanska is 70
    days late on 99 449 kr". Left alone it goes stale two ways: the figures
    freeze at the moment it was written, and it stays open after the customer
    has paid. So a regenerated card refreshes the one already on the deck, and
    a card whose condition no longer produces a candidate is closed as
    resolved — distinct from anything the CEO decided. Agent-proposed cards
    are not touched; only the agent knows whether those still hold.

    When a source could not be read at all, nothing is closed: the absence of
    a candidate then means "unknown", not "fixed". `unknown` narrows that to
    the cards whose own check did not run — key prefixes, from `_unknown` —
    so one failed report does not freeze the whole deck.
    """
    by_key = {c["key"]: c for c in candidates if c.get("key")}
    live = set(by_key)
    with _editing() as (conn, data):
        for card in data["cards"]:
            if card.get("source") != "auto":
                continue
            if any((card.get("key") or "").startswith(u) for u in unknown):
                by_key.pop(card.get("key"), None)
                continue
            # An approved card holds its key while the condition persists. Once
            # the check stops firing it lets go, so the next time the same
            # customer is late is a new card, not a repeat of the old one.
            if (card.get("status") == "done" and not card.get("released")
                    and sources_ok and card.get("key") not in live):
                card["released"] = _now()
                continue
            if card.get("status") not in ("open", "snoozed"):
                continue
            fresh = by_key.pop(card.get("key"), None)
            if fresh is not None:
                if "body" in fresh:
                    fresh = {**fresh, "body": _with_follow_up(card, fresh["body"])}
                for field in ("title", "body", "amount", "urgency", "evidence",
                              "draft", "options"):
                    if field in fresh and fresh[field] != card.get(field):
                        card[field] = fresh[field]
                card["refreshed"] = _now()
            elif sources_ok:
                card["status"] = "resolved"
                card["closed"] = _now()
                card["decided"] = {"at": datetime.now().isoformat(timespec="seconds"),
                                   "effect": "resolved", "label": "Løste seg selv",
                                   "note": "Kontrollen som laget kortet finner ikke "
                                           "lenger noe å melde."}
                log.info("Kort %s lukket: forholdet er borte", card["id"])
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
