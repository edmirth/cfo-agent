"""The health check and the clean-up list, pinned against made-up books.

The model is a stand-in that answers with what the test hands it, or fails;
what is checked is the engine: the facts per section, the clean-up items, what
is kept, the card, and what happens when the model is not there.
"""
import asyncio
from contextlib import contextmanager
from datetime import date

import cards
import cashflow
import commitments
import company
import db
import health
import overview
import preflight
import scheduler
from agent import core
from tests import _tmp

TODAY = date(2026, 10, 10)

OV = {"kpis": {"kundefordringer": 2_710_464.0, "lonnsandel_pct": 71.2},
      "monthly": [{"month": m, "revenue": 1_500_000.0, "wages": w}
                  for m, w in (("Jan", 1_000_000.0), ("Feb", 1_050_000.0),
                               ("Mars", 1_100_000.0), ("April", 1_000_000.0),
                               ("Mai", 1_000_000.0), ("Juni", 1_200_000.0),
                               ("Juli", 700_000.0), ("Aug", 1_050_000.0),
                               ("Sept", 1_150_000.0), ("Okt", 200_000.0))]}
COM = {"bank": 3_140_405.87, "free_now": -113_053.98, "free_all": -900_000.0,
       "totals": {"within_30": 3_253_459.85, "within_90": 500_000.0, "later": 0.0},
       "items": [{"label": "Merverdiavgift", "amount": 797_571.0, "due": "2026-10-12",
                  "days": 2, "estimated": False}], "anomalies": []}
CF = {"weeks": [{"label": "Uke 42", "start": "2026-10-12", "committed_close": 900_000.0,
                 "expected_close": 1_200_000.0}],
      "low_committed": {"label": "Uke 42", "start": "2026-10-12", "amount": 900_000.0},
      "low_expected": {"label": "Uke 42", "start": "2026-10-12", "amount": 1_200_000.0},
      "assumptions": {}, "ar_complete": True,
      "ar_open": [{"name": "Skanska Norge AS", "amount": 32_560.0, "due": "2026-07-25"},
                  {"name": "Backe Romerike AS", "amount": 23_813.0, "due": "2026-01-06"},
                  {"name": "Seby AS", "amount": 57_056.0, "due": "2026-09-30"},
                  {"name": "Skanska Norge AS", "amount": 100_000.0, "due": "2026-11-01"}],
      "bank": {"booked": 2_754_000.0, "adjustment": 386_405.87, "lines": 9,
               "latest": "2026-10-09", "unknown": [
                   "Bankavstemmingen for konto 1920, mai–september, er ikke lukket."],
               "stale": False},
      "warnings": []}
PF = {"condition": "provisional", "checks": [
    {"id": "approval", "label": "Til godkjenning", "status": "note",
     "headline": "3 leverandørfakturaer venter på godkjenning.", "detail": ""},
    {"id": "inbox", "label": "Bilagsinnboks", "status": "warn",
     "headline": "12 bilag i innboksen er ikke bokført.", "detail": "Eldste fra 2. sept."},
    {"id": "ar_tie", "label": "Kundereskontro", "status": "ok", "headline": "Stemmer."}]}


@contextmanager
def _books(answer=None, ov=OV, com=COM, cf=CF, pf=PF, fail=()):
    """A fresh database; the books as given; the model answering `answer`
    (a dict, or an exception to raise). Yields the prompts it was sent."""
    _tmp.db()
    _tmp.store(company, "COMPANY_FILE")
    real = (overview.cached, commitments.cached, cashflow.cached, preflight.cached,
            core.complete)
    sent = []

    def source(value, name):
        async def get():
            if name in fail:
                raise RuntimeError(f"{name} feilet")
            return value
        return get

    async def model(job, prompt, triggered_by=None):
        sent.append(prompt)
        if isinstance(answer, BaseException):
            raise answer
        return core.Result(text="", data=answer or {}, check={"unverified": []})

    overview.cached, commitments.cached = source(ov, "ov"), source(com, "com")
    cashflow.cached, preflight.cached = source(cf, "cf"), source(pf, "pf")
    core.complete = model
    try:
        yield sent
    finally:
        (overview.cached, commitments.cached, cashflow.cached, preflight.cached,
         core.complete) = real


ANSWER = {
    "summary": "Driften går, men momsen er brukt i driften.",
    "sections": {"cash": "Det står 3 140 406 kr i banken.", "payroll": "Lønnsandelen var høy i september.",
                 "receivables": "Tre kunder står for det meste.", "tax": "Momsen forfaller 12. oktober.",
                 "gaps": "Bankavstemmingen er ikke lukket for mai–september."},
    "cleanup_intro": "Dette fant vi i regnskapet.",
    "cleanup": [{"id": "inbox", "text": "Bokfør de 12 bilagene i innboksen."},
                {"id": "made_up", "text": "Noe som ikke ble funnet."}],
}


# ------------------------------------------------------------- the facts
def test_each_section_is_built_from_the_engines_figures():
    with _books():
        f = asyncio.run(health.facts(TODAY))
    s = f["seksjoner"]
    assert s["cash"]["fritt_naa_kr"] == -113_053.98 and s["cash"]["banken_foran_bokene_kr"] == 386_405.87
    # The month running now is not finished, and is left out.
    assert [m["maned"] for m in s["payroll"]["per_maned"]][-1] == "Sept"
    assert s["payroll"]["per_maned"][-1]["lonnsandel_pct"] == 76.7
    r = s["receivables"]
    assert r["apne_fakturaer"] == 4 and r["apne_fakturaer_kr"] == 213_429.0
    assert r["storste_kunder"][0] == {"kunde": "Skanska Norge AS", "kr": 132_560.0,
                                     "andel_pct": 62.1}
    late = {b["dager_forfalt"]: b["antall"] for b in r["forfalt"]}
    # Seby 10 days late, Skanska's July invoice 77, Backe 277; the November one is not due.
    assert late == {"1–30": 1, "31–60": 0, "61–90": 1, "over 90": 1}
    assert s["tax"]["poster"][0]["kr"] == 797_571.0


def test_the_clean_up_list_is_the_checks_findings_warnings_first():
    items = health.cleanup_items(PF, CF)
    assert [i["id"] for i in items] == ["inbox", "approval", "bank_unbooked", "reconciliation_1"]
    assert items[2]["funnet"].startswith("9 banklinjer ligger ubokført")
    assert "mai–september" in items[3]["funnet"]


def test_nothing_to_read_no_health_check():
    with _books(fail=("ov", "com", "cf", "pf")):
        try:
            asyncio.run(health.write(TODAY))
            raise AssertionError("a health check from nothing")
        except health.HealthError as exc:
            assert "Ingen tall" in str(exc)


# ------------------------------------------------------------- the writing
def test_both_are_kept_and_a_card_carries_the_list_to_send():
    with _books(ANSWER) as sent:
        out = asyncio.run(health.write(TODAY))
        kept = health.latest()
        deck = cards.deck(TODAY)
    assert out["written_by"] == "model" and out["unverified"] == []
    assert '"penger_i_banken_kr": 3140405.87' in sent[0]
    assert kept["summary"] == ANSWER["summary"]
    assert [s["key"] for s in kept["sections"]] == ["cash", "payroll", "receivables", "tax", "gaps"]
    # Every item the checks found gets a point; one the model made up does not.
    ids = [c["id"] for c in kept["cleanup"]]
    assert ids == ["inbox", "approval", "bank_unbooked", "reconciliation_1"]
    assert kept["cleanup"][0]["text"] == "Bokfør de 12 bilagene i innboksen."
    assert kept["cleanup"][1]["text"].startswith("3 leverandørfakturaer")
    text = kept["cleanup_text"]
    assert text.startswith("Hei,") and "1. Bokfør de 12 bilagene" in text
    card = next(c for c in deck["open"] if c["key"] == "cleanup:2026-10-10")
    assert card["title"] == "Send oppryddingslisten til regnskapsfører (4 punkter)"
    assert card["draft"]["text"] == text


def test_without_the_model_both_are_written_from_the_figures():
    with _books(core.JobError("credit balance is too low")):
        out = asyncio.run(health.write(TODAY))
        kept = health.latest()
    assert out["written_by"] == "engine" and "credit" in out["problem"]
    cash = next(s for s in kept["sections"] if s["key"] == "cash")["text"]
    assert cash.startswith("Det står 3 140 406 kr i banken.")
    assert kept["cleanup"][0]["text"].startswith("12 bilag i innboksen er ikke bokført.")
    assert kept["unverified"] == []


def test_a_new_run_replaces_the_card_from_the_one_before():
    with _books(ANSWER):
        first = asyncio.run(health.write(TODAY))
        second = asyncio.run(health.write(TODAY))
        deck = cards.deck(TODAY)
    assert second["replaced"] == [first["card"]]
    assert [c["id"] for c in deck["open"] if c["key"].startswith("cleanup:")] == [second["card"]]


def test_clean_books_no_list_and_no_card():
    clean = {"condition": "clean", "checks": []}
    quiet_bank = {**CF, "bank": {**CF["bank"], "lines": 0, "unknown": []}}
    with _books(ANSWER, cf=quiet_bank, pf=clean):
        out = asyncio.run(health.write(TODAY))
        kept = health.latest()
        deck = cards.deck(TODAY)
    assert out["card"] is None and kept["cleanup_text"] == ""
    assert not [c for c in deck["open"] if c["key"].startswith("cleanup:")]


# ------------------------------------------------------------- the schedule
def test_made_on_the_sixth_working_day_of_the_month():
    # October 2026: 1, 2, 5, 6, 7 and then 8.
    assert scheduler.health_day(date(2026, 10, 8))
    assert not scheduler.health_day(date(2026, 10, 7))
    assert not scheduler.health_day(date(2026, 10, 9))
    assert scheduler.HEALTH in scheduler.JOBS


def test_the_step_says_partial_when_the_model_did_not_write_it():
    with _books(core.JobError("Your credit balance is too low to access the Anthropic API.")):
        real = health.write
        health.write = lambda: real(TODAY)
        try:
            out = asyncio.run(scheduler._health())
        finally:
            health.write = real
    assert out["partial"] and "ut fra tallene alene" in out["cause"]
