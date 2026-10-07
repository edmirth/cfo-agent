"""The forecast record, pinned against a known history.

Four weeks, made up but exact. Monday 12 October's forecast expected Skanska's
50 000 kr in that week and Seby's 30 000 the next, and our 20 000 kr bill to
Tingstad paid on the 14th. Skanska paid late, and so did we. The bank showed
960 000 kr on Friday the 16th against a forecast of 1 000 000.
"""
from datetime import date, timedelta

import cashflow
import db
import forecasts
import scoring
from tests import _tmp

MON = date(2026, 10, 12)

ITEMS_12 = {
    "ar": [{"number": 1, "name": "Skanska Norge AS", "amount": 50000.0,
            "parts": [["2026-10-16", 50000.0]]},
           {"number": 2, "name": "Seby AS", "amount": 30000.0,
            "parts": [["2026-10-23", 30000.0]]}],
    "ap": [{"number": None, "name": "Tingstad Emballasje AS", "amount": 20000.0,
            "parts": [["2026-10-14", 20000.0]]}]}
# A week on: Skanska still owes all of it, Seby is not yet due, and the bill to
# Tingstad is still unpaid.
ITEMS_19 = {
    "ar": [{"number": 1, "name": "Skanska Norge AS", "amount": 50000.0,
            "parts": [["2026-10-26", 50000.0]]},
           {"number": 2, "name": "Seby AS", "amount": 30000.0,
            "parts": [["2026-10-23", 30000.0]]}],
    "ap": [{"number": None, "name": "Tingstad Emballasje AS", "amount": 20000.0,
            "parts": [["2026-10-19", 20000.0]]}]}


def _save(made_on: date, closes: dict[int, float], items=None):
    """A saved forecast: the expected close per week number."""
    monday = made_on - timedelta(days=made_on.weekday())
    weeks = [{"index": i, "start": (monday + timedelta(weeks=i)).isoformat(),
              "committed_close": closes.get(i, 0.0) - 100000,
              "expected_close": closes.get(i, 0.0), "items": []} for i in range(13)]
    data = {"partial": False, "opening": 1.0, "weeks": weeks, "assumptions": {},
            "low_committed": {}, "low_expected": {}, "bank": {}, "items": items}
    with db.tx() as conn:
        forecasts._forecast(conn, data, made_on, None)


def _bank(on: str, kr: float, account: str = "1920"):
    with db.tx() as conn:
        conn.execute("INSERT INTO bank_balances VALUES (?, ?, ?, 'bank_feed', ?)",
                     (db.company_id(), on, account, db.to_ore(kr)))


def _history():
    _tmp.db()
    _save(MON, {0: 1_000_000, 1: 1_100_000, 3: 1_300_000}, ITEMS_12)
    _save(MON + timedelta(days=1), {0: 9_999_999})        # same week: not scored
    _save(MON + timedelta(days=7), {0: 1_050_000}, ITEMS_19)
    _save(date(2026, 10, 26), {0: 2_000_000, 1: 1_310_000})   # week 0: no bank figure
    _bank("2026-10-16", 960_000)                         # Friday, week of the 12th
    _bank("2026-10-24", 1_000_000)                       # Saturday, week of the 19th
    _bank("2026-10-24", 89_000, account="1940")          # a second account, same day
    _bank("2026-11-06", 1_300_000)                       # Friday, week of 2 Nov


def test_each_horizon_is_scored_against_the_bank_at_the_close_of_its_week():
    _history()
    assert scoring.score(date(2026, 11, 10)) == 5
    rec = scoring.track_record(date(2026, 11, 10))
    got = {(s["made_on"], s["horizon_weeks"]): s for s in rec["scores"]}
    one = got[("2026-10-12", 1)]
    assert (one["target_date"], one["actual_on"]) == ("2026-10-18", "2026-10-16")
    assert (one["forecast"], one["actual"]) == (1_000_000.0, 960_000.0)
    assert one["error_pct"] == 4.17
    assert one["committed"] == 900_000.0
    two = got[("2026-10-12", 2)]
    assert two["actual"] == 1_089_000.0             # both accounts, summed
    assert two["error_pct"] == 1.01
    assert got[("2026-10-12", 4)]["error_pct"] == 0.0
    assert got[("2026-10-19", 1)]["error_pct"] == -3.58     # next Monday's own
    assert ("2026-10-26", 1) not in got              # no bank figure that week
    assert got[("2026-10-26", 2)]["error_pct"] == 0.77      # but there is two on
    assert rec["weekly_forecasts_kept"] == 3         # the Tuesday re-run is not one


def test_the_miss_is_put_down_to_who_paid_when():
    _history()
    scoring.score(date(2026, 11, 10))
    one = next(s for s in scoring.track_record()["scores"]
               if s["made_on"] == "2026-10-12" and s["horizon_weeks"] == 1)
    a = one["attribution"]
    assert a["available"]
    assert a["receipts_late"] == 50_000.0 and a["payments_late"] == 20_000.0
    # Skanska paying late takes 50 000 off the bank; our paying Tingstad late
    # leaves 20 000 on it. That explains 30 000 of the 40 000 miss.
    assert a["explained"] == 30_000.0 and a["not_in_forecast"] == 10_000.0
    assert a["names"][0] == {"name": "Skanska Norge AS", "kind": "kunde",
                             "amount": 50_000.0}
    assert {"name": "Tingstad Emballasje AS", "kind": "leverandør",
            "amount": -20_000.0} in a["names"]


def test_without_a_forecast_the_week_after_the_miss_is_not_explained():
    _history()
    scoring.score(date(2026, 11, 10))
    four = next(s for s in scoring.track_record()["scores"]
                if s["made_on"] == "2026-10-12" and s["horizon_weeks"] == 4)
    assert four["attribution"]["available"] is False


def test_nothing_is_scored_before_its_week_is_over_or_twice():
    _history()
    assert scoring.score(date(2026, 10, 18)) == 0     # the Sunday itself
    assert scoring.score(date(2026, 10, 19)) == 1
    assert scoring.score(date(2026, 10, 19)) == 0


def test_the_streak_counts_weeks_in_a_row_within_ten_percent():
    def s(target, err):
        return {"target_date": target, "error_pct": err}
    four = [s("2026-12-27", 2.0), s("2026-12-20", -9.9), s("2026-12-13", 4.0),
            s("2026-12-06", 15.0), s("2026-11-29", 1.0)]
    assert scoring._streak(four) == 3                 # the 15 % miss ends it
    gap = [s("2026-12-27", 2.0), s("2026-12-13", 1.0)]
    assert scoring._streak(gap) == 1                  # a missing week ends it too
    assert scoring._streak([]) == 0


def test_the_briefing_never_claims_an_accuracy_nobody_measured():
    _tmp.db()
    text = scoring.briefing(MON)
    assert "No forecast has been scored yet" in text and "never state" in text
    # Nothing kept on the 12th: the first is the 19th's, scored when its week closes.
    assert "due around 2026-10-26" in text
    _history()
    scoring.score(date(2026, 11, 10))
    text = scoring.briefing(date(2026, 11, 10))
    # The latest per horizon: the 19th's 1-week, the 26th's 2-week, the 12th's 4-week.
    assert "-3.6 %" in text and "+0.8 %" in text and "+0.0 %" in text
    assert "1 uke(r) på rad" in text


# --------------------------------------------- the forecast keeps its invoices
def test_the_invoice_list_kept_matches_what_the_forecast_scheduled():
    today = date(2026, 10, 12)
    late = {"name": "Seby AS", "due": "2026-09-30", "amount": 30000.0, "number": 7}
    due = {"name": "Skanska Norge AS", "due": "2026-10-20", "amount": 50000.0, "number": 8}
    bill = {"name": "Tingstad", "due": "2026-10-01", "amount": 20000.0, "number": None}
    items = cashflow._expected_items([late, due], [bill], today)
    flows = cashflow._schedule_receipts([late, due], today)
    assert sum(p[1] for i in items["ar"] for p in i["parts"]) == \
        sum(f["amount"] for f in flows)
    assert [p[0] for p in items["ar"][0]["parts"]] == \
        ["2026-10-19", "2026-10-26", "2026-11-02"]   # overdue: spread over 3 weeks
    assert items["ar"][1]["parts"] == [["2026-10-27", 50000.0]]   # due + 7 days
    assert items["ap"][0]["parts"] == [["2026-10-12", 20000.0]]   # overdue: now
