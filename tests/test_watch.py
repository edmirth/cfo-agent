"""The morning watch: what crosses a line, what the model may do about it.

The detectors are pinned against made-up figures. For a whole run, the model
is a script: it calls the watch's tools as the model would, through the same
`agent.tools.run`, and the test reads back what each call answered and what
was stored. So what is checked is the rules the tools enforce — candidates
only, numbers with a source, two findings at most, never twice.
"""
import asyncio
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import cards
import cashflow
import commitments
import company
import db
import job_runs
import memory
import overview
import preflight
import watch
from agent import core
from agent import tools as agent_tools
from tests import _tmp

TODAY = date(2026, 10, 9)
NAMES = {6300: "Leie lokale", 6400: "Leie maskiner", 6500: "Verktøy",
         6800: "Kontorrekvisita"}


def _rules():
    _tmp.store(company, "COMPANY_FILE")
    return company.rules(1_000_000)


def _com(free_now=-150_000.0):
    return {"as_of": "2026-10-09", "bank": 650_000.0, "free_now": free_now,
            "free_all": free_now - 200_000, "totals": {"within_30": 800_000.0},
            "items": [{"id": "mva_forrige_termin", "label": "Merverdiavgift",
                       "amount": 600_000.0, "due": "2026-10-12", "days": 3},
                      {"id": "aga", "label": "Arbeidsgiveravgift",
                       "amount": 200_000.0, "due": "2026-11-16", "days": 38}]}


def _ov(flows=None):
    """Months January to October; account 6300 at 20 000 a month, then
    September as given."""
    flows = flows or {6300: [20_000.0] * 8 + [52_000.0, 3_000.0],
                      6800: [5_000.0] * 8 + [9_000.0, 0.0]}
    return {"kpis": {"bank": 650_000.0, "driftsmargin_pct": 2.4},
            "cost_accounts": {"months": list(range(1, 11)), "accounts": [
                {"account": a, "name": NAMES.get(a, "Annen kostnad"), "flows": f}
                for a, f in flows.items()]}}


# ------------------------------------------------------------- detectors
def test_vat_money_in_use_is_a_candidate_above_the_alert_minimum():
    rules = _rules()
    c = watch.vat_candidate(_com(), rules)
    assert c["key"] == "watch:vat:2026-10-12" and c["amount"] == 150_000.0
    assert c["figures"]["poster"] == [{"hva": "Merverdiavgift", "kr": 600_000.0,
                                       "forfall": "2026-10-12"}]
    assert watch.vat_candidate(_com(free_now=-5_000.0), rules) is None   # under 10 000
    assert watch.vat_candidate(_com(free_now=40_000.0), rules) is None


def test_a_cost_well_above_its_usual_month_is_a_candidate():
    found = watch.cost_candidates(_ov(), _rules(), TODAY)
    # 6300: 52 000 against 20 000 is 160 % and 32 000 kr over. 6800: 9 000
    # against 5 000 is 80 % over, but only 4 000 kr: under the minimum.
    assert [c["key"] for c in found] == ["watch:cost:6300:2026-09"]
    f = found[0]["figures"]
    assert f["vanlig_niva_kr"] == 20_000.0 and f["over_vanlig_kr"] == 32_000.0
    assert f["over_vanlig_pct"] == 160.0 and f["maneder_i_snittet"] == 6


def test_a_rise_under_the_rulebooks_percentage_is_not():
    flows = {6300: [100_000.0] * 8 + [140_000.0, 0.0]}     # 40 % over, 40 000 kr
    assert watch.cost_candidates(_ov(flows), _rules(), TODAY) == []


def test_no_usual_level_no_candidate():
    assert watch.cost_candidates(_ov(), _rules(), date(2026, 1, 15)) == []   # last month was last year
    assert watch.cost_candidates(_ov(), _rules(), date(2026, 3, 9)) == []    # only January before February


# ------------------------------------------------------------- a whole run
@contextmanager
def _morning(com=None, ov=None, script=(), fail=()):
    """A fresh database, today's figures as given, and the model as `script`:
    a list of (tool, args). Yields what each call answered and whether the
    model was called at all."""
    _tmp.db()
    _tmp.store(company, "COMPANY_FILE")
    real = (overview.cached, commitments.cached, cashflow.cached, preflight.cached,
            core.complete)
    said, called = [], []

    def source(value, name):
        async def get():
            if name in fail:
                raise RuntimeError(f"{name} feilet")
            return value
        return get

    async def model(job, prompt, triggered_by=None):
        called.append(prompt)
        for name, args in script:
            said.append(await agent_tools.run(name, args))
        return core.Result(text="Ferdig.", data=None, check={"unverified": []})

    overview.cached = source(ov if ov is not None else _ov(), "overview")
    commitments.cached = source(com if com is not None else _com(), "commitments")
    cashflow.cached = source({"weeks": [], "assumptions": {}}, "cashflow")
    preflight.cached = source({"condition": "clean", "checks": []}, "preflight")
    core.complete = model
    try:
        yield said, called
    finally:
        (overview.cached, commitments.cached, cashflow.cached, preflight.cached,
         core.complete) = real


def _run():
    return asyncio.run(watch.run(TODAY))


CARD = {"candidate": "watch:vat:2026-10-12", "urgency": "high",
        "title": "Momsen er brukt i driften: det mangler 150 000 kr",
        "body": "Banken har 650 000 kr, men 800 000 kr forfaller innen 30 dager.",
        "options": [{"label": "Forstått", "effect": "approve"}]}


def test_quiet_when_nothing_has_crossed_a_line_and_no_model_is_called():
    calm = {6300: [20_000.0] * 10}
    with _morning(com=_com(free_now=90_000.0), ov=_ov(calm)) as (said, called):
        out = _run()
    assert out["quiet"] and not called


def test_a_card_is_raised_for_a_candidate_with_its_amount_and_the_rule_behind_it():
    with _morning(script=[("watch_card", CARD)]) as (said, called):
        out = _run()
        deck = cards.deck(TODAY)
    assert said == [f"Card {out['cards'][0]} is on the deck."]
    card = next(c for c in deck["open"] if c["key"] == "watch:vat:2026-10-12")
    assert card["amount"] == 150_000.0 and card["kind"] == "vat"
    assert any(e["label"] == "Regel" for e in card["evidence"])
    # The other candidate, untouched, stays for tomorrow.
    assert out["left"] == ["watch:cost:6300:2026-09"]


def test_what_it_has_dealt_with_is_not_put_to_it_again():
    with _morning(script=[("watch_card", CARD),
                          ("watch_skip", {"candidate": "watch:cost:6300:2026-09",
                                          "reason": "Husleien for et kvartal."})]) as (_, called):
        _run()
        job_runs.finish(job_runs.start(watch.JOB), "ok")    # the review just happened
        again = _run()
    assert len(called) == 1 and again["quiet"] and again["new"] == 0


def test_a_number_with_no_source_is_refused_and_nothing_is_stored():
    made_up = dict(CARD, title="Det mangler 175 000 kr på momsen")
    with _morning(script=[("watch_card", made_up)]) as (said, _):
        out = _run()
        deck = cards.deck(TODAY)
    assert said[0].startswith("Not stored: 175 000 is not in grunnlaget")
    assert not deck["open"] and out["refused"][0]["unsourced"] == ["175 000"]


def test_only_candidates_can_be_raised():
    stray = dict(CARD, candidate="watch:cost:9999:2026-09")
    with _morning(script=[("watch_card", stray)]) as (said, _):
        _run()
        assert not cards.deck(TODAY)["open"]
    assert "not a candidate this morning" in said[0]


def test_two_findings_a_morning_at_most():
    flows = {a: [20_000.0] * 8 + [60_000.0, 0.0] for a in (6300, 6400, 6500)}
    ov = _ov(flows)
    finding = lambda a: ("watch_finding", {"candidate": f"watch:cost:{a}:2026-09",  # noqa: E731
                                          "topic": "Uvanlig kostnad", "severity": "medium",
                                          "statement": "60 000 kr mot vanlig 20 000 kr."})
    with _morning(com=_com(free_now=90_000.0), ov=ov,
                  script=[finding(6300), finding(6400), finding(6500)]) as (said, _):
        out = _run()
    assert len(out["findings"]) == 2 and "No more findings this morning" in said[2]


def test_a_finding_is_closed_with_the_figure_that_settles_it():
    with _morning(com=_com(free_now=90_000.0), ov=_ov({6300: [20_000.0] * 10}),
                  script=[("watch_close_finding", {
                      "finding_id": "F001",
                      "outcome": "Fritt nå er 90 000 kr, så momsen er dekket."})]) as (said, called):
        memory.add_finding("Moms brukt i drift", "high", "Fritt nå var negativt.")
        out = _run()
        assert not memory.open_findings()
    assert called and out["closed"] == ["F001"] and said == ["F001 closed."]


def test_a_watch_card_closes_itself_when_its_condition_is_gone():
    with _morning(script=[("watch_card", CARD)]):
        first = _run()
        commitments.cached = _async(_com(free_now=90_000.0))
        later = _run()
        card = next(c for c in cards.deck(TODAY)["recent"] if c["id"] == first["cards"][0])
    assert later["closed_cards"] == [first["cards"][0]] and card["status"] == "resolved"


def test_a_source_that_failed_closes_nothing():
    with _morning(script=[("watch_card", CARD)]):
        first = _run()
        commitments.cached = _async_fail()
        later = _run()
        assert any(c["id"] == first["cards"][0] for c in cards.deck(TODAY)["open"])
    assert later["closed_cards"] == [] and later["failed"] == ["forpliktelsene"]


def test_the_watchs_tools_do_nothing_outside_a_watch_run():
    _tmp.db()
    said = asyncio.run(agent_tools.run("watch_card", CARD))
    assert said == "This tool works only in the morning watch."


def _async(value):
    async def get():
        return value
    return get


def _async_fail():
    async def get():
        raise RuntimeError("Tripletex svarte ikke")
    return get


def test_without_the_model_the_warnings_are_still_raised_as_plain_cards():
    with _morning() as (said, called):
        async def no_credit(job, prompt, triggered_by=None):
            raise core.JobError("Your credit balance is too low to access the Anthropic API.")
        core.complete = no_credit
        out = _run()
        deck = cards.deck(TODAY)
    keys = {c["key"]: c for c in deck["open"]}
    vat = keys["watch:vat:2026-10-12"]
    assert vat["title"] == ("Momsen og skattene er brukt i driften: det mangler "
                            "150 000 kr de neste 30 dagene")
    assert vat["urgency"] == "high" and vat["amount"] == 150_000.0
    assert keys["watch:cost:6300:2026-09"]["title"] == (
        "Konto 6300 Leie lokale: 52 000 kr i 2026-09, mot vanlig 20 000 kr")
    assert len(out["cards"]) == 2 and "credit balance" in out["problem"]
    assert out["left"] == []


def test_the_step_says_partial_when_the_model_did_not_run():
    import scheduler
    with _morning():
        async def no_credit(job, prompt, triggered_by=None):
            raise core.JobError("Your credit balance is too low to access the Anthropic API.")
        core.complete = no_credit
        real = watch.run
        watch.run = lambda: real(TODAY)
        try:
            out = asyncio.run(scheduler._watch())
        finally:
            watch.run = real
    assert out["partial"] and "kreditt på Anthropic-kontoen" in out["cause"]
    assert "enkle kort" in out["cause"]
