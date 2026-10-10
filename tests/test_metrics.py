"""The product owner's measures, pinned against a made-up few weeks.

Each test writes the raw record the product keeps — card events, activity
minutes, job runs, bank balances and forecasts — and reads the measure back.
"""
from datetime import date, datetime, timedelta, timezone

import cards
import company
import db
import forecasts
import job_runs
import metrics
from tests import _tmp

MON = date(2026, 10, 12)


def _fresh():
    _tmp.db()
    _tmp.store(company, "COMPANY_FILE")


def _card(key: str, draft: str | None = "Hei, fakturaen er forfalt.") -> dict:
    card = {"key": key, "kind": "collections", "title": f"Kort {key}", "body": "…",
            "source": "auto", "options": [
                {"id": "send", "label": "Send påminnelsen", "effect": "approve"},
                {"id": "wait", "label": "Vent en uke", "effect": "snooze", "days": 7}]}
    if draft is not None:
        card["draft"] = {"kind": "e-post", "to": "", "subject": "Purring", "text": draft}
    return cards.add(card)


def _edited(card_id: str):
    with db.read() as conn:
        return conn.execute(
            "SELECT e.draft_edited FROM card_events e JOIN cards c ON c.id = e.card_id "
            "WHERE c.ref = ? AND e.event = 'decided'", (card_id,)).fetchone()[0]


# ------------------------------------------------------------- recording
def test_a_changed_draft_is_recorded_as_edited_and_kept():
    _fresh()
    edited, as_is, plain = _card("a"), _card("b"), _card("c", draft=None)
    cards.decide(edited["id"], "send", draft_text="Hei! Fakturaen er forfalt, kan dere betale?")
    cards.decide(as_is["id"], "send", draft_text="Hei, fakturaen er forfalt.  ")
    cards.decide(plain["id"], "send")
    assert (_edited(edited["id"]), _edited(as_is["id"]), _edited(plain["id"])) == (1, 0, None)
    done = {c["id"]: c for c in cards.deck()["recent"]}
    assert done[edited["id"]]["draft"]["text"].startswith("Hei! Fakturaen")


def test_time_in_the_app_is_counted_in_minutes_once_each():
    _fresh()
    t = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
    for s in (0, 20, 40, 65, 130):                       # seconds: three distinct minutes
        metrics.ping("ceo@example.no", t + timedelta(seconds=s))
    metrics.ping("ceo@example.no", t + timedelta(days=7))
    with db.read() as conn:
        assert metrics.minutes(conn, db.company_id()) == {"2026-W42": 3, "2026-W43": 1}


# ------------------------------------------------------------- measuring
def test_decisions_per_week_with_the_share_approved_as_written():
    _fresh()
    a, b, c = _card("a"), _card("b"), _card("c")
    cards.decide(a["id"], "send", draft_text="Hei, fakturaen er forfalt.")
    cards.decide(b["id"], "send", draft_text="Endret tekst.")
    cards.decide(c["id"], "wait")
    with db.read() as conn:
        week = metrics.decisions(conn, db.company_id())[metrics._week(date.today())]
    assert week["decided"] == 3 and week["approved"] == 2
    assert week["approved_unedited"] == 1 and week["unedited_pct"] == 50.0
    assert week["median_hours_to_decide"] is not None and week["median_hours_to_decide"] >= 0


def test_agent_cost_per_week_and_job():
    _fresh()
    for job, usd in (("vakt", 0.12), ("mandagsbrev", 0.30), ("vakt", 0.08), ("chat", None)):
        run = job_runs.start(job)
        job_runs.finish(run, "ok", cost_usd=usd)
    with db.read() as conn:
        week = metrics.cost(conn, db.company_id())[metrics._week(date.today())]
    assert week["usd"] == 0.5 and week["runs"] == 4 and week["unpriced"] == 1
    assert week["by_job"] == {"vakt": 0.2, "mandagsbrev": 0.3}


def _bank(on: date, kr: float):
    with db.tx() as conn:
        conn.execute("INSERT INTO bank_balances (company_id, on_date, account, source, "
                     "balance_ore) VALUES (?, ?, '1920', 'bank_feed', ?)",
                     (db.company_id(), on.isoformat(), db.to_ore(kr)))


def _forecast(made_on: date, closes: dict[str, float]):
    """A saved forecast whose committed line closes the given weeks as given."""
    monday = made_on - timedelta(days=made_on.weekday())
    weeks = [{"index": i, "start": (monday + timedelta(weeks=i)).isoformat(),
              "committed_close": closes.get((monday + timedelta(weeks=i)).isoformat(), 2_000_000.0),
              "expected_close": 2_000_000.0, "items": []} for i in range(13)]
    with db.tx() as conn:
        forecasts._forecast(conn, {"opening": 2_000_000.0, "weeks": weeks, "assumptions": {},
                                   "low_committed": {}, "low_expected": {}, "bank": {}},
                            made_on, None)


def test_a_cash_dip_is_measured_against_the_first_forecast_that_saw_it():
    _fresh()
    dip_week = MON + timedelta(weeks=3)                  # Monday 2 November
    _forecast(MON - timedelta(days=7), {})               # did not see it
    _forecast(MON, {dip_week.isoformat(): 400_000.0})    # first to see it: 3 weeks ahead
    _forecast(MON + timedelta(days=7), {dip_week.isoformat(): 300_000.0})
    _bank(dip_week + timedelta(days=4), 450_000.0)       # Friday: under a 500 000 floor
    _bank(MON + timedelta(days=4), 900_000.0)            # a week that held
    with db.read() as conn:
        found = metrics.dips(conn, db.company_id(), 500_000.0)
    assert found == [{"week": "2026-W45", "on": "2026-11-06", "balance": 450_000.0,
                      "floor": 500_000.0, "first_flagged": "2026-10-12", "weeks_ahead": 3}]


def test_a_dip_no_forecast_saw_says_so():
    _fresh()
    _forecast(MON, {})
    _bank(MON + timedelta(days=11), 100_000.0)
    with db.read() as conn:
        found = metrics.dips(conn, db.company_id(), 500_000.0)
    assert found[0]["first_flagged"] is None and found[0]["weeks_ahead"] is None


def test_the_report_has_eight_weeks_newest_first_and_the_floor_it_used():
    _fresh()
    out = metrics.report(MON)
    assert [w["week"] for w in out["weeks"]][:2] == ["2026-W42", "2026-W41"]
    assert len(out["weeks"]) == 8 and out["target_minutes"] == 10
    assert out["floor"]["said"].startswith("antatt")
