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
