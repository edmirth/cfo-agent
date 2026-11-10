"""Card 20: each late customer against his own habit, the chase as a ladder of
two reminders and then the owner's decision, and the day's list. Made-up
customers."""
from datetime import date, timedelta

import cards
import innkreving
from tests import _tmp
from tests.test_rulebook import _company

TODAY = date(2026, 11, 9)


def _inv(name: str, days_late: int, amount: float, number: int = 1) -> dict:
    due = (TODAY - timedelta(days=days_late)).isoformat()
    return {"name": name, "due": due, "amount": amount, "number": number,
            "email": "post@example.no"}


HABITS = {"customers": {
    "Fjordvik Bygg AS": {"days": 2, "invoices": 8},      # pays on time
    "Nordlys Eiendom AS": {"days": 25, "invoices": 6},   # always about 25 days late
}, "company": 5}


def _one(invoices, history=None, block=""):
    with _company(block):
        out = cards._collections(invoices, TODAY, habits=HABITS, history=history or [])
    assert len(out) == 1, out
    return out[0]


def test_a_customer_who_pays_on_time_is_unusual_and_the_card_says_ring():
    c = _one([_inv("Fjordvik Bygg AS", 20, 40_000)])
    assert c["urgency"] == "high"
    assert c["options"][0]["id"] == "call"
    assert "uvanlig" in c["body"] and "Ring" in c["body"]
    assert any(e["label"] == "Betaler vanligvis" for e in c["evidence"])


def test_a_habitual_late_payer_gets_a_reminder_not_an_alarm():
    c = _one([_inv("Nordlys Eiendom AS", 30, 40_000)])
    assert c["urgency"] == "medium"
    assert c["options"][0]["id"] == "send"
    assert "fast sent" in c["body"] and "prognosen" in c["body"]


def test_a_habitual_late_payer_far_past_his_own_habit_is_unusual():
    c = _one([_inv("Nordlys Eiendom AS", 55, 40_000)])
    assert c["options"][0]["id"] == "call" and "uvanlig" in c["body"]


def test_a_customer_with_no_habit_is_as_before():
    c = _one([_inv("Havbris Catering AS", 20, 40_000)])
    assert c["options"][0]["id"] == "send"
    assert "uvanlig" not in c["body"] and "fast sent" not in c["body"]


def test_the_reminder_has_a_deadline_and_the_account_when_it_is_set():
    c = _one([_inv("Havbris Catering AS", 20, 40_000)], block="kontonummer: 1234.56.78903")
    text = c["draft"]["text"]
    assert "betales innen 16.11.2026 til konto 1234.56.78903" in text
    plain = _one([_inv("Havbris Catering AS", 20, 40_000)])["draft"]["text"]
    assert "til kontonummeret som står på fakturaen" in plain


def _sent(customer: str, closed: str, released: str | None = None) -> dict:
    card = {"id": f"K{closed}", "key": f"collections:{customer}", "status": "done",
            "closed": closed, "decided": {"option": "send", "label": "Send påminnelsen"}}
    if released:
        card["released"] = released
    return card


def test_after_one_reminder_the_second_is_firmer():
    c = _one([_inv("Havbris Catering AS", 35, 40_000)],
             history=[_sent("Havbris Catering AS", "2026-10-26")])
    assert c["title"].endswith("andre påminnelse")
    assert c["draft"]["subject"].startswith("Ny påminnelse")
    assert "påminnelse 26.10.2026" in c["draft"]["text"]
    assert "videre tiltak" in c["draft"]["text"]


def test_after_two_reminders_the_next_step_is_the_owners_and_nothing_is_drafted():
    c = _one([_inv("Havbris Catering AS", 50, 40_000)],
             history=[_sent("Havbris Catering AS", "2026-10-12"),
                      _sent("Havbris Catering AS", "2026-10-26")])
    assert "draft" not in c
    assert c["urgency"] == "high"
    assert [o["id"] for o in c["options"]] == ["inkasso", "call", "wait"]
    assert "Neste steg er ditt" in c["body"]


def test_a_reminder_from_an_earlier_round_of_lateness_does_not_count():
    c = _one([_inv("Havbris Catering AS", 20, 40_000)],
             history=[_sent("Havbris Catering AS", "2026-06-01", released="2026-06-20")])
    assert c["draft"]["subject"].startswith("Påminnelse")


def test_the_days_list_says_what_to_do_and_what_waits():
    _tmp.db()
    invoices = [_inv("Fjordvik Bygg AS", 20, 40_000), _inv("Havbris Catering AS", 20, 60_000),
                _inv("Nordlys Eiendom AS", 30, 80_000)]
    with _company():
        for c in cards._collections(invoices, TODAY, habits=HABITS, history=[]):
            cards.add({**c, "source": "auto"})
        nordlys = next(c for c in cards.deck()["open"] if "Nordlys" in c["key"])
        cards.decide(nordlys["id"], "send")
        history = cards._load()["cards"]
        late = cards._late(invoices, TODAY, habits=HABITS, history=history)
    out = innkreving.today_list(late, history, TODAY)
    rows = {r["customer"]: r for r in out["rows"]}
    assert out["today"] == 2
    assert rows["Fjordvik Bygg AS"]["action"] == "Ring dem"
    assert rows["Havbris Catering AS"]["action"] == "Send påminnelse"
    assert rows["Nordlys Eiendom AS"]["action"] == "Venter på betaling"
    assert not rows["Nordlys Eiendom AS"]["today"]
    # What to do today first, the unusual one at the top.
    assert out["rows"][0]["customer"] == "Fjordvik Bygg AS"
    assert out["rows"][-1]["customer"] == "Nordlys Eiendom AS"

