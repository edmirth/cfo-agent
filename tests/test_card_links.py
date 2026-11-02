"""A decision in the Monday email, opened and decided without a login.

The link is a key, so most of these check what it does not open: another
card, a card already decided, a link used, run out, or altered by a letter.
The routes are called through ASGI, past the same login gate a browser meets.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import brief
import brief_email
import card_links
import cards
import company
import config
import db
import job_runs
import mailer
import main
from tests import _tmp
from tests.test_brief_email import MON, _keep

NOW = datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc)


def _fresh():
    _tmp.db()
    _tmp.store(company, "COMPANY_FILE")


def _card(key: str) -> dict:
    return cards.add({
        "key": key, "kind": "collections", "title": f"Purr {key}", "body": "…",
        "source": "auto",
        "draft": {"kind": "e-post", "to": "", "subject": "Purring", "text": "Hei."},
        "options": [{"id": "send", "label": "Send påminnelsen", "effect": "approve"},
                    {"id": "wait", "label": "Vent en uke", "effect": "snooze", "days": 7}]})


def _refused(fn, *args, **kw) -> card_links.Refused:
    try:
        fn(*args, **kw)
    except card_links.Refused as exc:
        return exc
    raise AssertionError("the link opened")


def _post(path: str, body: dict):
    """One POST through the app, with no login. Returns (status, json)."""
    raw = json.dumps(body).encode()
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "client": ("127.0.0.1", 1),
             "headers": [(b"content-type", b"application/json"),
                         (b"content-length", str(len(raw)).encode())],
             "server": ("127.0.0.1", 8000), "root_path": ""}
    sent, asked = [], []

    async def receive():
        if asked:
            await asyncio.Future()
        asked.append(True)
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(main.app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    data = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(data)


# --------------------------------------------------------------- the link
def test_only_a_hash_of_the_link_is_kept():
    _fresh()
    k = _card("a")
    token = card_links.mint([k["id"]], None, at=NOW)[k["id"]]
    assert len(token) >= 40
    with db.read() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM card_links")]
    assert len(rows) == 1 and token not in json.dumps(rows)
    assert rows[0]["card_ref"] == k["id"] and rows[0]["used_at"] is None
    assert rows[0]["expires_at"] == (NOW + timedelta(days=7)).isoformat()


def test_a_link_opens_its_own_card_and_nothing_else():
    _fresh()
    a, b = _card("a"), _card("b")
    token = card_links.mint([a["id"]], None, at=NOW)[a["id"]]
    shown = card_links.show(token, at=NOW)
    assert shown["card"]["id"] == a["id"] and shown["card"]["title"] == "Purr a"
    assert shown["card"]["options"][0]["label"] == "Send påminnelsen"
    assert b["id"] not in json.dumps(shown)
    # Not the deck's bookkeeping either: only what the card says.
    assert "key" not in shown["card"] and "status" not in shown["card"]


def test_deciding_from_the_link_is_the_same_as_the_button_in_the_app():
    _fresh()
    k = _card("a")
    token = card_links.mint([k["id"]], None, at=NOW)[k["id"]]
    out = card_links.decide(token, "send", draft_text="Hei igjen.", at=NOW)
    assert out["card"]["status"] == "done"
    assert out["card"]["decided"]["label"] == "Send påminnelsen"
    assert out["card"]["decided"]["draft_edited"] is True
    with db.read() as conn:
        event = conn.execute("SELECT event, actor, option_id FROM card_events "
                             "WHERE event = 'decided'").fetchone()
        link = conn.execute("SELECT used_at, option_id FROM card_links").fetchone()
        remembered = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    assert tuple(event) == ("decided", "ceo", "send")
    assert link["used_at"] == NOW.isoformat() and link["option_id"] == "send"
    assert remembered == 1


def test_a_link_decides_once():
    _fresh()
    k = _card("a")
    token = card_links.mint([k["id"]], None, at=NOW)[k["id"]]
    card_links.decide(token, "wait", at=NOW)
    for fn, args in ((card_links.show, (token,)), (card_links.decide, (token, "send"))):
        exc = _refused(fn, *args, at=NOW)
        assert exc.status == 410 and "brukt" in str(exc) and "Logg inn" in str(exc)
    assert cards.deck()["snoozed"][0]["id"] == k["id"]


def test_a_link_runs_out_after_a_week():
    _fresh()
    k = _card("a")
    token = card_links.mint([k["id"]], None, at=NOW)[k["id"]]
    assert card_links.show(token, at=NOW + timedelta(days=6, hours=23))
    exc = _refused(card_links.decide, token, "send", at=NOW + timedelta(days=7))
    assert exc.status == 410 and "gått ut" in str(exc) and "7 dager" in str(exc)
    assert cards.deck()["open"][0]["id"] == k["id"]


def test_an_altered_or_made_up_link_opens_nothing():
    _fresh()
    k = _card("a")
    token = card_links.mint([k["id"]], None, at=NOW)[k["id"]]
    altered = ("A" if token[0] != "A" else "B") + token[1:]
    for bad in (altered, token + "x", "", k["id"], "x" * 500):
        exc = _refused(card_links.show, bad, at=NOW)
        assert exc.status == 404 and "virker ikke" in str(exc), bad


def test_a_card_decided_in_the_app_closes_its_link():
    _fresh()
    k = _card("a")
    token = card_links.mint([k["id"]], None, at=NOW)[k["id"]]
    cards.decide(k["id"], "send")
    exc = _refused(card_links.decide, token, "wait", at=NOW)
    assert exc.status == 409 and "ikke åpen" in str(exc)


def test_a_choice_the_card_does_not_have_leaves_the_link_working():
    _fresh()
    k = _card("a")
    token = card_links.mint([k["id"]], None, at=NOW)[k["id"]]
    assert _refused(card_links.decide, token, "pay-it", at=NOW).status == 400
    assert card_links.decide(token, "send", at=NOW)["card"]["status"] == "done"


# ------------------------------------------------------------- the routes
def test_the_link_routes_answer_without_a_login_but_only_to_a_token():
    _fresh()
    k = _card("a")
    token = card_links.mint([k["id"]], None)[k["id"]]
    status, body = _post("/api/link", {"token": token})
    assert status == 200 and body["card"]["id"] == k["id"]
    status, body = _post("/api/link", {"token": "gjettet"})
    assert status == 404 and "virker ikke" in body["detail"]
    status, _ = _post("/api/link", {})
    assert status == 422
    status, body = _post("/api/link/decide", {"token": token, "option": "send"})
    assert status == 200 and body["card"]["status"] == "done"
    status, body = _post("/api/link/decide", {"token": token, "option": "send"})
    assert status == 410
    # The rest of the app is still behind the login.
    status, _ = _post("/api/cards/K001/decide", {"option": "send"})
    assert status == 401


# -------------------------------------------------------------- the email
def test_the_email_sent_links_each_decision_to_its_card_without_a_login():
    _fresh()
    ks = [_card(x) for x in "abc"]
    decisions = {"count": 3, "more": 0, "top": [
        {"id": k["id"], "title": k["title"], "amount": None,
         "link": f"#saker/{k['id']}"} for k in ks]}
    b = _keep(decisions=decisions)
    outbox = []

    async def fake(to, subject, html, text, key):
        outbox.append(html)
        return "mail-1"

    real, mailer.send = mailer.send, fake
    saved, config.APP_URL = config.APP_URL, "https://app.example.no"
    token = job_runs.trigger.set("user")
    try:
        asyncio.run(brief_email.send(MON))
    finally:
        mailer.send, config.APP_URL = real, saved
        job_runs.trigger.reset(token)
    page = outbox[0]
    prefix = f'href="https://app.example.no/?fra=brev&amp;b={b["id"]}#godkjenn/'
    assert page.count(prefix) == 3 and "#saker/K" not in page
    # Each one opens its own card.
    tokens = [part.split('"', 1)[0] for part in page.split(prefix)[1:]]
    assert [card_links.show(t)["card"]["id"] for t in tokens] == [k["id"] for k in ks]
    # The brief as kept is untouched: the links belong to this one email.
    assert "godkjenn" not in json.dumps(brief.latest(MON))


def test_without_an_app_address_no_links_are_made():
    _fresh()
    _keep()

    async def fake(to, subject, html, text, key):
        return "mail-1"

    real, mailer.send = mailer.send, fake
    saved, config.APP_URL = config.APP_URL, ""
    try:
        asyncio.run(brief_email.send(MON, force=True))
    finally:
        mailer.send, config.APP_URL = real, saved
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM card_links").fetchone()[0] == 0
