"""The Monday brief, pinned against a made-up forecast.

A floor of 500 000 kr. The forecast opens at 900 000 and each test bends the
weeks it needs: a dip in week 7, a dip in week 3, a line that goes dry. The
model is a stand-in that answers with what the test hands it, so what is
checked is the engine: the light, the low point, the decisions, what is kept.
"""
import asyncio
from contextlib import contextmanager
from datetime import date, timedelta

import brief
import cards
import cashflow
import db
import memory
import preflight
import scheduler
import scoring
from agent import core
from tests import _tmp

MON = date(2026, 10, 12)
FLOOR = 500000.0
FLOOR_RULE = {"value": FLOOR, "assumed": False, "basis": "company.md",
              "label": "Likviditetsgulv"}


def _cf(committed: dict[int, float] | None = None,
        expected: dict[int, float] | None = None, partial=False) -> dict:
    """Thirteen weeks at 900 000 kr unless told otherwise."""
    committed, expected = committed or {}, expected or {}
    weeks = []
    for i in range(13):
        start = MON + timedelta(weeks=i)
        c = committed.get(i, 900000.0)
        weeks.append({"index": i, "label": f"Uke {start.isocalendar().week}",
                      "start": start.isoformat(), "committed_close": c,
                      "expected_close": expected.get(i, max(c, 900000.0)),
                      "items": []})
    return {"weeks": weeks, "partial": partial, "assumptions": {}}


def _deck(n: int) -> dict:
    return {"open": [{"id": f"K{i:03d}", "title": f"Sak {i}", "urgency": "high",
                      "amount": 10000.0 * i} for i in range(1, n + 1)]}


PF_CLEAN = {"condition": "clean", "checks": [
    {"id": "inbox", "label": "Bilagsinnboks", "status": "ok", "headline": "Tom."}]}
PF_BEHIND = {"condition": "provisional", "checks": [
    {"id": "approval", "label": "Til godkjenning", "status": "note",
     "headline": "3 leverandørfakturaer venter på godkjenning."},
    {"id": "inbox", "label": "Bilagsinnboks", "status": "warn",
     "headline": "12 bilag i innboksen er ikke bokført."}]}


@contextmanager
def _world(cf: dict, deck: dict, pf: dict = PF_CLEAN, answer=None):
    """A fresh database, and the forecast, checks, deck and model as given.
    `answer` is the model's JSON, or an exception it raises."""
    _tmp.db()
    real = (cashflow.cached, cashflow.rules, preflight.cached, cards.deck,
            core.complete)
    sent = []

    async def cf_cached():
        return cf

    async def pf_cached():
        return pf

    async def complete(job, prompt, triggered_by=None):
        sent.append(prompt)
        if isinstance(answer, BaseException):
            raise answer
        data = answer or {"sentence": "Ingen grunn til uro denne uka.", "changed": []}
        return core.Result(text="", data=data, check={"unverified": []})

    cashflow.cached = cf_cached
    cashflow.rules = lambda data: {"likviditetsgulv_kr": FLOOR_RULE}
    preflight.cached = pf_cached
    cards.deck = lambda today=None: deck
    core.complete = complete
    try:
        yield sent
    finally:
        (cashflow.cached, cashflow.rules, preflight.cached, cards.deck,
         core.complete) = real


# ------------------------------------------------------------------ the light
def test_green_when_the_committed_line_holds_six_weeks_and_a_later_dip_is_said():
    cf = _cf(committed={7: 420000.0})
    lt = brief.light(cf, FLOOR)
    assert lt.colour == "green" and lt.safe_weeks == 7
    low = brief.low_point(cf, FLOOR_RULE)
    assert low["under_floor"] and low["week"] == "Uke 49"
    assert "80 000 kr under gulvet på 500 000 kr" in low["text"]


def test_yellow_when_only_money_not_yet_invoiced_keeps_it_above_the_floor():
    assert brief.light(_cf(committed={3: 400000.0}), FLOOR).colour == "yellow"


def test_yellow_when_even_the_expected_line_dips_but_only_late():
    cf = _cf(committed={9: 300000.0}, expected={9: 450000.0})
    assert brief.light(cf, FLOOR).colour == "yellow"


def test_red_when_even_customers_paying_as_usual_is_not_enough():
    cf = _cf(committed={2: 200000.0}, expected={2: 300000.0})
    assert brief.light(cf, FLOOR).colour == "red"


def test_red_when_what_is_already_billed_takes_the_account_below_zero():
    # The expected line holds above the floor only on invoicing not yet sent;
    # the money already agreed goes dry in week 2.
    cf = _cf(committed={2: -50000.0}, expected={2: 600000.0})
    assert brief.light(cf, FLOOR).colour == "red"


def test_never_green_on_a_partial_forecast_or_broken_books():
    assert brief.light(_cf(partial=True), FLOOR).colour == "yellow"
    assert brief.light(_cf(), FLOOR, books="broken").colour == "yellow"
    # ...but they do not soften a red.
    assert brief.light(_cf(committed={1: 100000.0}, expected={1: 100000.0},
                           partial=True), FLOOR).colour == "red"


def test_an_assumed_floor_is_said_to_be_one():
    rule = dict(FLOOR_RULE, assumed=True, basis="én månedslønn")
    text = brief.low_point(_cf(), rule)["text"]
    assert "over gulvet på 500 000 kr alle 13 ukene" in text
    assert "antatt: én månedslønn" in text


# -------------------------------------------------------------- the content
def test_at_most_three_decisions_each_linked_to_its_card():
    d = brief.decisions(_deck(5))
    assert d["count"] == 5 and d["more"] == 2
    assert [c["link"] for c in d["top"]] == ["#saker/K001", "#saker/K002", "#saker/K003"]


def test_an_amount_the_title_already_says_is_not_said_twice():
    deck = {"open": [{"id": "K016", "title": "Seby AS skylder 57 056 kr",
                      "amount": 57056.0}]}
    with _world(_cf(), deck):
        b = asyncio.run(brief.build(MON))
    assert "- Seby AS skylder 57 056 kr\n" in b["body"]


def test_nothing_needs_you_is_said_when_nothing_does():
    with _world(_cf(), {"open": []}):
        b = asyncio.run(brief.build(MON))
    assert "Ingenting trenger deg denne uka." in b["body"]
    assert "Trenger deg" not in b["body"]


def test_the_books_say_what_is_not_posted_warnings_first():
    bk = brief.books(PF_BEHIND)
    assert bk["lines"][0] == "12 bilag i innboksen er ikke bokført."
    assert bk["text"].startswith("Bøkene: Tallene er foreløpige.")
    assert brief.books(PF_CLEAN)["text"] == "Bøkene er ajour."
    assert "ukjent" in brief.books(None)["text"]


def test_what_changed_comes_from_the_figures_kept_a_week_ago():
    _tmp.db()
    memory.snapshot({"bank": 800000.0, "lonnsandel_pct": 75.0,
                     "omsetning": 1000000.0}, on=(MON - timedelta(days=7)).isoformat())
    memory.snapshot({"bank": 650000.0, "lonnsandel_pct": 79.0,
                     "omsetning": 1300000.0}, on=MON.isoformat())
    ch = brief.changes(MON)
    assert ch["since"] == "2026-10-05"
    by = {k["kpi"]: k for k in ch["kpis"]}
    assert by["bank"]["change"] == -150000.0 and not by["bank"]["cumulative"]
    assert by["omsetning"]["cumulative"]
    lines = brief._change_lines(ch, {"amount": 0.0})
    # Levels by how far they moved relative to where they were; the
    # year-to-date sum last.
    assert lines[0] == "Bank: 650 000 kr, fra 800 000 kr."
    assert lines[1] == "Lønnsandel: 79,0 %, fra 75,0 %."
    assert lines[-1] == "Omsetning hittil i år økte med 300 000 kr siste uke."


def test_the_first_brief_of_the_year_does_not_call_new_year_a_fall():
    """Revenue since 1 January starts again at New Year. December's total
    against a week of January read as revenue falling by most of a year's."""
    _tmp.db()
    memory.snapshot({"bank": 800000.0, "omsetning": 15_000_000.0},
                    on="2026-12-28")
    memory.snapshot({"bank": 700000.0, "omsetning": 300_000.0}, on="2027-01-04")
    ch = brief.changes(date(2027, 1, 4))
    assert [k["kpi"] for k in ch["kpis"]] == ["bank"]
    table = memory.briefing(date(2027, 1, 4))
    row = next(line for line in table.splitlines() if line.startswith("| Omsetning"))
    assert row == "| Omsetning hittil i år | 300 000 | — |"


def test_no_record_yet_is_said_and_no_accuracy_is_claimed():
    _tmp.db()
    acc = brief.accuracy(MON)
    assert not acc["scored"]
    assert acc["text"].startswith("Treffsikkerhet: ikke målt ennå (0 ukeprognoser")


def test_the_record_is_said_once_there_is_one():
    real = scoring.track_record
    scoring.track_record = lambda today=None: {
        "weekly_forecasts_kept": 9, "within_pct": 10.0, "streak": 3, "next": None,
        "latest": {1: None, 2: None, 4: {"error_pct": -4.2}},
        "mean_abs_error_pct": {1: None, 2: None, 4: 6.5}}
    try:
        acc = brief.accuracy(MON)
    finally:
        scoring.track_record = real
    assert acc["scored"]
    assert acc["text"] == ("Treffsikkerhet: prognosen fire uker fram bommet med "
                           "-4,2 % sist, ±6,5 % i snitt. Innenfor ±10 % 3 uker på "
                           "rad; målet er 8.")


# ---------------------------------------------------------- writing and keeping
def test_the_brief_opens_with_the_light_and_is_kept_for_the_web_app():
    answer = {"sentence": "Pengene holder de neste seks ukene.",
              "changed": ["Lønnsandelen steg."]}
    with _world(_cf(committed={7: 420000.0}), _deck(2), PF_BEHIND, answer) as sent:
        b = asyncio.run(brief.write(MON))
        kept = brief.latest(MON)
    lines = b["body"].splitlines()
    assert lines[0] == "GRØNN — Pengene holder de neste seks ukene."
    assert lines[1].startswith("Laveste punkt: uke 49")
    assert "Trenger deg (2)" in b["body"] and "- Sak 2 — 20 000 kr" in b["body"]
    assert "12 bilag i innboksen er ikke bokført." in b["body"]
    assert b["unverified"] == [], b["unverified"]
    # The model is told the colour; it does not choose it.
    assert "GRØNN" in sent[0]
    assert kept["id"] == b["id"] and kept["current"] and kept["body"] == b["body"]
    assert kept["decisions"]["top"][0]["link"] == "#saker/K001"
    assert not brief.latest(MON + timedelta(days=7))["current"]


def test_without_the_model_the_brief_is_still_written_from_the_figures():
    with _world(_cf(committed={3: 400000.0}), _deck(1),
                answer=core.JobError("credit balance is too low")):
        b = asyncio.run(brief.write(MON))
    assert b["written_by"] == "engine"
    assert b["body"].startswith("GUL — Uten innbetalinger utover det som er fakturert")


def test_no_forecast_no_brief():
    with _world({"weeks": []}, _deck(1)):
        try:
            asyncio.run(brief.build(MON))
            raise AssertionError("a brief was written without a forecast")
        except brief.BriefError as exc:
            assert "Prognosen" in str(exc)


def test_a_rewrite_is_a_new_row_and_the_latest_is_shown():
    with _world(_cf(), _deck(0)):
        first = asyncio.run(brief.write(MON))
        second = asyncio.run(brief.write(MON))
        with db.read() as conn:
            n = conn.execute("SELECT count(*) FROM reports WHERE kind = 'weekly_brief'"
                             ).fetchone()[0]
        assert n == 2 and brief.latest(MON)["id"] == second["id"] != first["id"]


# ---------------------------------------------------------------- the schedule
def test_written_on_the_first_working_day_of_the_week_after_the_morning():
    assert scheduler.JOBS[:2] == (scheduler.MORNING, scheduler.WEEKLY)
    on = scheduler.WEEKLY.runs_on
    assert on(date(2026, 10, 12)) and not on(date(2026, 10, 13))
    # Easter Monday 2027 and Whit Monday 2026: the Tuesday instead.
    assert not on(date(2027, 3, 29)) and on(date(2027, 3, 30))
    assert not on(date(2026, 5, 25)) and on(date(2026, 5, 26))
    assert scheduler.WEEKLY.at == scheduler.MORNING.at


def test_the_brief_step_says_partial_when_the_model_did_not_write_it():
    with _world(_cf(), _deck(0), answer=core.JobError("nope")):
        out = asyncio.run(scheduler._brief())
    assert out["partial"] and "uten Arvakas egne ord" in out["cause"]
    with _world({"weeks": []}, _deck(0)):
        try:
            asyncio.run(scheduler._brief())
            raise AssertionError("a brief without a forecast passed")
        except scheduler.StepFailed:
            pass
