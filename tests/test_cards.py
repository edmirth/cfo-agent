from datetime import date, timedelta

import cards
import memory
from tests import _tmp


def _card(key, title, amount=1000):
    return {"key": key, "kind": "collections", "urgency": "high", "amount": amount,
            "title": title, "body": "b", "evidence": [],
            "options": [{"id": "ok", "label": "Ok", "effect": "approve"},
                        {"id": "wait", "label": "Vent", "effect": "snooze", "days": 7}]}


def test_dedup_on_key():
    _tmp.store(cards); _tmp.store(memory)
    assert cards.add(_card("k1", "a")) is not None
    assert cards.add(_card("k1", "a")) is None


def test_snooze_wakes_only_for_real_reads():
    _tmp.store(cards); _tmp.store(memory)
    c = cards.add(_card("k1", "a"))
    cards.decide(c["id"], "wait")
    later = date.today() + timedelta(days=8)
    assert len(cards.deck(later)["open"]) == 1          # hypothetical: wakes in the copy
    assert cards.deck()["snoozed"][0]["id"] == c["id"]   # real read today: still snoozed


def test_decision_reaches_memory():
    _tmp.store(cards); _tmp.store(memory)
    c = cards.add(_card("k1", "Skanska er sen"))
    cards.decide(c["id"], "ok", note="ringt")
    assert any("Skanska" in d["decision"] for d in memory._load()["decisions"])


def test_reconcile_updates_and_closes_derived_cards():
    _tmp.store(cards); _tmp.store(memory)
    cards.add({**_card("collections:Skanska", "Skanska 70 d, 99 449 kr", 99449), "source": "auto"})
    cards.add({**_card("collections:Seby", "Seby 40 d", 94500), "source": "auto"})
    cards.add({**_card("agent:x", "agentens eget"), "source": "agent"})
    # Next refresh: Skanska still late but less; Seby has paid.
    cards.reconcile([_card("collections:Skanska", "Skanska 72 d, 75 644 kr", 75644)],
                    sources_ok=True)
    d = cards.deck()
    titles = {c["title"] for c in d["open"]}
    assert "Skanska 72 d, 75 644 kr" in titles, titles          # refreshed in place
    assert "agentens eget" in titles                             # untouched
    assert not any("Seby" in t for t in titles)                  # closed
    assert any(c["status"] == "resolved" for c in d["recent"])


def test_reconcile_closes_nothing_when_a_source_failed():
    _tmp.store(cards); _tmp.store(memory)
    cards.add({**_card("collections:Seby", "Seby 40 d", 94500), "source": "auto"})
    cards.reconcile([], sources_ok=False)
    assert len(cards.deck()["open"]) == 1


def test_propose_drops_invalid_effects():
    _tmp.store(cards); _tmp.store(memory)
    c = cards.propose("t", "b", options=[{"label": "Send", "effect": "launch_missiles"},
                                         {"label": "Ok", "effect": "approve"}])
    assert [o["effect"] for o in c["options"]] == ["approve"]


def test_approved_card_does_not_come_straight_back():
    # "Send påminnelsen", then the page reloads the deck: the customer is still
    # late, but the CEO has already acted. No new card.
    _tmp.store(cards); _tmp.store(memory)
    c = cards.add({**_card("collections:Skanska", "Skanska 70 d"), "source": "auto"})
    cards.decide(c["id"], "ok")
    cards.reconcile([_card("collections:Skanska", "Skanska 70 d")], sources_ok=True)
    assert cards.deck()["open"] == []


def test_approved_card_returns_once_the_condition_cleared_and_recurs():
    _tmp.store(cards); _tmp.store(memory)
    c = cards.add({**_card("collections:Skanska", "Skanska 70 d"), "source": "auto"})
    cards.decide(c["id"], "ok")
    cards.reconcile([], sources_ok=False)                  # unknown: still held
    cards.reconcile([_card("collections:Skanska", "x")], sources_ok=True)
    assert cards.deck()["open"] == []
    cards.reconcile([], sources_ok=True)                   # paid: key released
    cards.reconcile([_card("collections:Skanska", "Skanska 20 d")], sources_ok=True)
    assert [x["title"] for x in cards.deck()["open"]] == ["Skanska 20 d"]


def _approve_days_ago(card_id, days):
    cards.decide(card_id, "ok")
    data = cards._load()
    for c in data["cards"]:
        if c["id"] == card_id:
            c["closed"] = (date.today() - timedelta(days=days)).isoformat()
    cards._save(data)


def test_still_late_two_weeks_after_approval_comes_back_as_a_follow_up():
    _tmp.store(cards); _tmp.store(memory)
    c = cards.add({**_card("collections:Skanska", "Skanska 70 d"), "source": "auto"})
    _approve_days_ago(c["id"], 13)
    cards.reconcile([_card("collections:Skanska", "Skanska 83 d")], sources_ok=True)
    assert cards.deck()["open"] == []                    # day 13: still answered

    _approve_days_ago(c["id"], 14)
    cards.reconcile([_card("collections:Skanska", "Skanska 84 d")], sources_ok=True)
    [back] = cards.deck()["open"]
    assert back["id"] != c["id"] and back["title"] == "Skanska 84 d"
    assert back["follow_up"]["of"] == c["id"]
    assert back["body"].startswith("Oppfølging: du valgte «Ok» for 14 dager siden")


def test_a_follow_up_keeps_saying_so_when_refreshed():
    _tmp.store(cards); _tmp.store(memory)
    c = cards.add({**_card("collections:Skanska", "Skanska 70 d"), "source": "auto"})
    _approve_days_ago(c["id"], 20)
    cards.reconcile([_card("collections:Skanska", "x")], sources_ok=True)
    cards.reconcile([{**_card("collections:Skanska", "y"), "body": "ny tekst"}],
                    sources_ok=True)
    [back] = cards.deck()["open"]
    assert back["body"].startswith("Oppfølging:") and back["body"].endswith("ny tekst")
    assert back["body"].count("Oppfølging:") == 1


def test_approving_the_follow_up_starts_a_new_fortnight():
    _tmp.store(cards); _tmp.store(memory)
    c = cards.add({**_card("collections:Skanska", "Skanska 70 d"), "source": "auto"})
    _approve_days_ago(c["id"], 20)
    cards.reconcile([_card("collections:Skanska", "x")], sources_ok=True)
    [back] = cards.deck()["open"]
    cards.decide(back["id"], "ok")
    cards.reconcile([_card("collections:Skanska", "x")], sources_ok=True)
    assert cards.deck()["open"] == []


# ------------------------------------- a check that did not run closes nothing
def test_a_failed_check_does_not_close_its_cards():
    _tmp.store(cards); _tmp.store(memory)
    cards.add({**_card("reconcile:ar_tie", "Kundefordringer stemmer ikke"), "source": "auto"})
    cards.add({**_card("vouchers:2026-10", "12 bilag ubokført"), "source": "auto"})
    # Kundereskontro failed, the inbox answered and is now empty.
    pf = {"checks": [{"id": "ar_tie", "status": "unavailable"},
                     {"id": "inbox", "status": "ok"}]}
    cards.reconcile([], sources_ok=True, unknown=cards._unknown(pf, {"ar_complete": True}))
    d = cards.deck()
    assert [c["key"] for c in d["open"]] == ["reconcile:ar_tie"]    # unknown: kept
    assert [c["key"] for c in d["recent"]] == ["vouchers:2026-10"]  # answered: closed


def test_an_unread_invoice_list_does_not_mark_customers_as_paid():
    _tmp.store(cards); _tmp.store(memory)
    cards.add({**_card("collections:Skanska", "Skanska 70 d"), "source": "auto"})
    unknown = cards._unknown({"checks": []}, {"ar_complete": False})
    cards.reconcile([], sources_ok=True, unknown=unknown)
    assert [c["key"] for c in cards.deck()["open"]] == ["collections:Skanska"]


def test_an_approved_card_is_not_released_while_its_check_is_unknown():
    _tmp.store(cards); _tmp.store(memory)
    c = cards.add({**_card("collections:Skanska", "Skanska 70 d"), "source": "auto"})
    cards.decide(c["id"], "ok")
    cards.reconcile([], sources_ok=True, unknown={"collections:"})
    cards.reconcile([_card("collections:Skanska", "x")], sources_ok=True)
    assert cards.deck()["open"] == []


def test_refresh_keeps_cards_when_tripletex_fails():
    import asyncio
    _tmp.store(cards); _tmp.store(memory)
    cards.add({**_card("collections:Skanska", "Skanska 70 d"), "source": "auto"})
    cards.add({**_card("reconcile:ap_tie", "Leverandørgjeld stemmer ikke"), "source": "auto"})

    async def pf():
        return {"as_of": "2026-10-15", "condition": "incomplete",
                "checks": [{"id": "ap_tie", "status": "unavailable"}]}

    async def cf():
        return {"ar_open": [], "ar_complete": False, "low_committed": {}}

    originals = cards.preflight.cached, cards.cashflow.cached
    cards.preflight.cached, cards.cashflow.cached = pf, cf
    try:
        d = asyncio.run(cards.refresh())
    finally:
        cards.preflight.cached, cards.cashflow.cached = originals
    assert sorted(c["key"] for c in d["open"]) == ["collections:Skanska",
                                                   "reconcile:ap_tie"]
    assert not any(c.get("status") == "resolved" for c in d["recent"])
