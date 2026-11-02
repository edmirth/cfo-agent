"""A decision in the Monday email, decided with one tap and no password.

The playbook's decision queue is reached "with no friction: magic links, no
password to approve a reminder". Each decision in the email links to its card
through a link of its own; opening it shows that card, and choosing a button
there records the choice exactly as the button in the app does
(`cards.decide`).

**The link is a key, so it opens as little as it can.** One card, at one
company, for LIFETIME_DAYS (that week's brief), and once: after it has decided
the card it opens nothing. A card decided in the app, deferred, or resolved
on its own closes every link to it. Seeing anything else still needs a login.
Anyone holding the email can use it, a forward included; that is accepted
while a choice here only records a decision. When card 42 lets a tap send a
reminder through Tripletex, a link must ask for a login before it does.

**Nothing to steal from the database.** The token is 256 random bits and only
its SHA-256 is kept, so a copy of the database cannot be turned back into
working links, and an altered link matches no row. There is no signing key to
configure, rotate or leak.

**Fails closed, in Norwegian.** Every refusal is `Refused`, with a sentence
for the screen that says what to do instead: log in.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import cards
import db

log = logging.getLogger("cfo.card_links")

LIFETIME_DAYS = 7
# token_urlsafe(32) is 43 characters; anything far from that is not ours.
TOKEN_MAX = 100

LOG_IN = "Logg inn i appen for å se saken."


class Refused(Exception):
    """The link does not open. `status` for the response, the message for the
    screen."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utc(at: datetime | None) -> datetime:
    return (at or datetime.now(timezone.utc)).astimezone(timezone.utc)


def mint(card_refs: list[str], report_id: int | None,
         at: datetime | None = None) -> dict[str, str]:
    """A fresh link for each card, as {card ref: token}. Called once per email
    sent; a brief sent again gets links of its own, and the old ones run out."""
    at = _utc(at)
    expires = at + timedelta(days=LIFETIME_DAYS)
    out = {}
    with db.tx() as conn:
        cid = db.company_id()
        for ref in card_refs:
            token = secrets.token_urlsafe(32)
            conn.execute(
                "INSERT INTO card_links (company_id, token_hash, card_ref, report_id, "
                "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (cid, _hash(token), ref, report_id, at.isoformat(timespec="seconds"),
                 expires.isoformat(timespec="seconds")))
            out[ref] = token
    return out


def _link(conn, token: str, at: datetime) -> dict:
    """The link's row, if it may still be used at `at`; Refused otherwise."""
    if not token or len(token) > TOKEN_MAX:
        raise Refused(f"Lenken virker ikke. {LOG_IN}", 404)
    row = conn.execute("SELECT * FROM card_links WHERE token_hash = ? AND company_id = ?",
                       (_hash(token), db.company_id())).fetchone()
    if row is None:
        raise Refused(f"Lenken virker ikke. Den kan være kopiert feil eller endret. "
                      f"{LOG_IN}", 404)
    if row["used_at"]:
        raise Refused(f"Lenken er brukt, og saken er avgjort. {LOG_IN}", 410)
    if datetime.fromisoformat(row["expires_at"]) <= at:
        raise Refused(f"Lenken har gått ut: lenkene i mandagsbrevet virker i "
                      f"{LIFETIME_DAYS} dager. {LOG_IN}", 410)
    return dict(row)


def _open_card(ref: str, conn=None) -> dict:
    """The card, if it is open. Through `conn` inside a write: `cards.deck()`
    takes the write lock itself, and would wait on ours."""
    if conn is None:
        card = next((c for c in cards.deck()["open"] if c["id"] == ref), None)
    else:
        row = conn.execute("SELECT * FROM cards WHERE company_id = ? AND ref = ?",
                           (db.company_id(), ref)).fetchone()
        card = cards._card(row) if row is not None else None
        if card is not None and card.get("status") != "open":
            card = None
    if card is None:
        raise Refused(f"Saken er ikke åpen lenger: den er avgjort i appen, utsatt, "
                      f"eller har løst seg selv. {LOG_IN}", 409)
    return card


def _shown(card: dict, link: dict) -> dict:
    """What the page shows: the card, and nothing about the rest of the deck."""
    keep = ("id", "kind", "urgency", "title", "body", "amount", "evidence",
            "draft", "options")
    return {"card": {k: card[k] for k in keep if k in card},
            "expires": link["expires_at"]}


def show(token: str, at: datetime | None = None) -> dict:
    """The card a link opens, while it may still be decided from it."""
    with db.read() as conn:
        link = _link(conn, token, _utc(at))
    return _shown(_open_card(link["card_ref"]), link)


def decide(token: str, option_id: str, draft_text: str | None = None,
           at: datetime | None = None) -> dict:
    """Decide the link's card, as the button in the app would, and use the link
    up. Taken under the write lock, so two taps on the same link cannot both
    decide."""
    at = _utc(at)
    with db.tx() as conn:
        link = _link(conn, token, at)
        card = _open_card(link["card_ref"], conn)
        if not any(o["id"] == option_id for o in card.get("options", [])):
            raise Refused("Saken har ikke det valget. Last siden på nytt.", 400)
        conn.execute("UPDATE card_links SET used_at = ?, option_id = ? WHERE id = ?",
                     (at.isoformat(timespec="seconds"), option_id, link["id"]))
    try:
        decided = cards.decide(card["id"], option_id, draft_text=draft_text)
    except Exception:
        # Not decided, so not used: the link should still work.
        with db.tx() as conn:
            conn.execute("UPDATE card_links SET used_at = NULL, option_id = NULL "
                         "WHERE id = ?", (link["id"],))
        raise
    log.info("Kort %s avgjort fra lenken i mandagsbrevet: %s", card["id"], option_id)
    return {"card": decided}
