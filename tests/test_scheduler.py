"""The morning's work, run unasked: when, once, caught up, and never silently."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import db
import job_runs
import scheduler
import summary
import workdays
from mcp_client import McpError
from scheduler import Scheduled, Step
from tests import _tmp

OSLO = ZoneInfo("Europe/Oslo")
CREDIT = ("Error code: 400 - {'type': 'error', 'error': {'message': 'Your "
          "credit balance is too low to access the Anthropic API.'}}")


def _at(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=OSLO)


@contextmanager
def _clock(at: datetime):
    """The scheduler and the database on the same pretend moment, and a fresh
    database under both. `clock.at = ...` moves time on."""
    real = scheduler.now, db.now
    _tmp.db()
    scheduler._tried.clear()
    scheduler._running.clear()

    class Clock:
        pass
    clock = Clock()
    clock.at = at
    scheduler.now = lambda: clock.at
    db.now = lambda: clock.at.astimezone(timezone.utc).isoformat(timespec="seconds")
    try:
        yield clock
    finally:
        scheduler.now, db.now = real


def _job(*steps: Step) -> Scheduled:
    return Scheduled(name="test_morning", label="Morgenkjøringen", at=time(7, 0),
                     runs_on=workdays.is_working_day, days="virkedager",
                     steps=steps)


def _step(name: str, label: str, *outcomes):
    """A step that answers with each outcome in turn — a dict to return, or an
    exception to raise — and counts its calls."""
    calls = []

    async def run():
        out = outcomes[min(len(calls), len(outcomes) - 1)]
        calls.append(scheduler.now())
        if isinstance(out, BaseException):
            raise out
        return out
    return Step(name, label, run), calls


def _tick(clock, job):
    return asyncio.run(scheduler.tick(clock.at, (job,)))


def _attention(clock, job):
    return scheduler.status(clock.at, (job,))["jobs"][0]["attention"]


def test_the_morning_is_seven_on_norwegian_working_days_in_norwegian_time():
    j = _job()
    # Thursday before seven: the next run is today, the last was yesterday.
    assert scheduler.next_slot(j, _at(2026, 10, 8, 6, 59)) == _at(2026, 10, 8, 7)
    assert scheduler.last_slot(j, _at(2026, 10, 8, 6, 59)) == _at(2026, 10, 7, 7)
    assert scheduler.last_slot(j, _at(2026, 10, 8, 7)) == _at(2026, 10, 8, 7)
    # Friday's run done, the weekend is stepped over.
    assert scheduler.next_slot(j, _at(2026, 10, 9, 7)) == _at(2026, 10, 12, 7)
    # Christmas Day is a Friday; Christmas Eve is a working day.
    assert scheduler.next_slot(j, _at(2026, 12, 23, 8)) == _at(2026, 12, 24, 7)
    assert scheduler.next_slot(j, _at(2026, 12, 24, 8)) == _at(2026, 12, 28, 7)
    # Easter 2027: Maundy Thursday to Easter Monday off, five days in a row.
    assert scheduler.next_slot(j, _at(2027, 3, 24, 8)) == _at(2027, 3, 30, 7)
    # Seven in Norway either side of the clocks going back on 25 October.
    utc = timezone.utc
    assert _at(2026, 10, 23, 7).astimezone(utc).hour == 5
    assert scheduler.next_slot(j, _at(2026, 10, 23, 8)).astimezone(utc).hour == 6
    # A host whose own clock is UTC asks in UTC and still gets seven in Oslo.
    asked = datetime(2026, 10, 8, 4, 30, tzinfo=utc)
    assert scheduler.next_slot(j, asked) == _at(2026, 10, 8, 7)


def test_a_morning_runs_once_and_a_mac_that_slept_through_seven_catches_up():
    step, calls = _step("forecast", "Prognosen", {"low_point": 1_200_000})
    j = _job(step)
    with _clock(_at(2026, 10, 8, 6, 59)) as clock:
        assert _tick(clock, j) == []

        clock.at = _at(2026, 10, 8, 9, 30)          # the lid opens
        [ran] = _tick(clock, j)
        assert ran["status"] == "ok" and ran["slot"] == _at(2026, 10, 8, 7).isoformat()
        assert ran["steps"][0]["low_point"] == 1_200_000

        clock.at = _at(2026, 10, 8, 9, 31)
        assert _tick(clock, j) == []
        clock.at = _at(2026, 10, 8, 16, 0)
        assert _tick(clock, j) == []
        assert len(calls) == 1

        [row] = job_runs.recent("test_morning")
        assert (row["status"], row["triggered_by"]) == ("ok", "schedule")
        assert row["details"]["steps"][0]["status"] == "ok"
        assert _attention(clock, j) is None

        clock.at = _at(2026, 10, 9, 7, 0)
        assert [r["status"] for r in _tick(clock, j)] == ["ok"]
        assert len(calls) == 2


def test_a_morning_missed_altogether_is_said_and_not_run_the_next_day():
    step, calls = _step("forecast", "Prognosen", {})
    j = _job(step)
    # The Mac was off all Thursday. Friday before seven: yesterday's morning
    # is not owed any more, and the front page says it never ran.
    with _clock(_at(2026, 10, 9, 6, 30)) as clock:
        assert _tick(clock, j) == []
        assert calls == []
        assert _attention(clock, j) == (
            "Morgenkjøringen i går kl 07:00 ble ikke kjørt, fordi serveren ikke "
            "var i gang. Neste kjøring i dag kl 07:00.")
        # Today's, once it is due, is not a miss but a run about to happen.
        clock.at = _at(2026, 10, 9, 7, 0)
        assert _attention(clock, j) is None
        _tick(clock, j)
        assert _attention(clock, j) is None and len(calls) == 1


def test_a_failed_step_costs_that_step_and_the_run_is_tried_again():
    checks, _ = _step("checks", "Kontrollene", {"condition": "clean"})
    forecast, tries = _step("forecast", "Prognosen",
                            McpError("fetch_report svarte 502: <html>bad gateway"),
                            {"low_point": 900_000})
    later, after = _step("summary", "Oppsummeringen", {"verdict": "Solid drift"})
    j = _job(checks, forecast, later)
    with _clock(_at(2026, 10, 8, 7, 0)) as clock:
        [ran] = _tick(clock, j)
        # The step after the failure still ran.
        assert ran["status"] == "partial" and len(after) == 1
        assert [s["status"] for s in ran["steps"]] == ["ok", "failed", "ok"]
        [row] = job_runs.recent("test_morning")
        assert row["error"].startswith("forecast: fetch_report svarte 502")
        # The front page gets the reason in words, not the gateway's HTML.
        assert _attention(clock, j) == (
            "Morgenkjøringen i dag kl 07:00 ble ikke helt ferdig. Prognosen: "
            "Tripletex svarte ikke på oppslaget. Prøver igjen kl 07:30.")

        clock.at = _at(2026, 10, 8, 7, 29)
        assert _tick(clock, j) == []
        clock.at = _at(2026, 10, 8, 7, 30)
        assert [r["status"] for r in _tick(clock, j)] == ["ok"]
        assert len(tries) == 2
        assert _attention(clock, j) is None
        clock.at = _at(2026, 10, 8, 8, 30)
        assert _tick(clock, j) == []


def test_one_reason_is_said_once_for_every_step_it_stopped():
    forecast, _ = _step("forecast", "Prognosen", McpError("fetch_report: 503"))
    figures, _ = _step("figures", "Nøkkeltallene", McpError("fetch_report: 503"))
    later, _ = _step("summary", "Oppsummeringen",
                     scheduler.StepFailed("Ingen tall å oppsummere ennå."))
    with _clock(_at(2026, 10, 8, 7, 0)) as clock:
        _tick(clock, _job(forecast, figures, later))
        assert _attention(clock, _job(forecast, figures, later)) == (
            "Morgenkjøringen i dag kl 07:00 feilet. Prognosen og nøkkeltallene: "
            "Tripletex svarte ikke på oppslaget. Oppsummeringen: Ingen tall å "
            "oppsummere ennå. Prøver igjen kl 07:30.")


def test_a_dead_tripletex_login_is_named_with_its_fix_whatever_wrapped_it():
    checks, _ = _step("checks", "Kontrollene",
                      {"partial": True, "cause": "Tripletex svarte ikke på 5 av kontrollene."})
    # As cashflow.py words it: the login error inside its own.
    forecast, _ = _step("forecast", "Prognosen", RuntimeError(
        "Kunne ikke lese saldobalansen: Mangler TRIPLETEX_CLIENT_ID / "
        "TRIPLETEX_REFRESH_TOKEN. Kjør: ./.venv/bin/python scripts/oauth_login.py"))
    # As commitments.py words it: no cause at all.
    figures, _ = _step("figures", "Nøkkeltallene",
                       RuntimeError("Kunne ikke lese saldobalansen"))
    j = _job(checks, forecast, figures)
    with _clock(_at(2026, 10, 8, 7, 0)) as clock:
        [ran] = _tick(clock, j)
        assert ran["status"] == "partial"           # the checks half-ran
        assert _attention(clock, j) == (
            "Morgenkjøringen i dag kl 07:00 ble ikke helt ferdig. "
            "Tripletex-innloggingen virker "
            "ikke, så ingen tall kunne hentes. Kjør ./.venv/bin/python "
            "scripts/oauth_login.py. Prøver igjen kl 07:30.")


def test_after_three_failed_attempts_it_stops_and_says_when_it_runs_next():
    step, calls = _step("summary", "Oppsummeringen", RuntimeError(CREDIT))
    j = _job(step)
    with _clock(_at(2026, 10, 8, 7, 0)) as clock:
        for minute in (0, 30, 60):
            clock.at = _at(2026, 10, 8, 7 + minute // 60, minute % 60)
            assert [r["status"] for r in _tick(clock, j)] == ["failed"]
        clock.at = _at(2026, 10, 8, 8, 30)
        assert _tick(clock, j) == []
        clock.at = _at(2026, 10, 8, 12, 0)
        assert _tick(clock, j) == []
        assert len(calls) == 3
        assert _attention(clock, j) == (
            "Morgenkjøringen i dag kl 07:00 feilet. Oppsummeringen: Det er ikke "
            "kreditt på Anthropic-kontoen. Neste kjøring i morgen kl 07:00.")
        assert [r["status"] for r in job_runs.recent("test_morning")] == ["failed"] * 3


def test_a_run_the_server_stopped_in_is_closed_as_failed_and_run_again():
    step, calls = _step("forecast", "Prognosen", {})
    j = _job(step)
    with _clock(_at(2026, 10, 8, 7, 0)) as clock:
        # Started at seven; the Mac shut down a minute later.
        job_runs.start("test_morning", "schedule")
        assert _tick(clock, j) == []              # one is running, as far as anyone knows

        clock.at = _at(2026, 10, 8, 7, 40)        # the next server starts
        assert job_runs.close_orphans() == 1
        [dead] = job_runs.recent("test_morning")
        assert (dead["status"], dead["error"]) == ("failed", job_runs.ORPHANED)
        assert _attention(clock, j) == (
            "Morgenkjøringen i dag kl 07:00 feilet. Serveren stoppet før jobben "
            "ble ferdig. Prøver igjen straks.")
        assert [r["status"] for r in _tick(clock, j)] == ["ok"]
        assert len(calls) == 1 and _attention(clock, j) is None


def test_what_a_scheduled_run_causes_is_filed_under_it_as_the_schedules():
    seen = {}

    async def save_forecast():
        seen["job_run"] = db.job_run.get()
        inner = job_runs.start("forecast")
        job_runs.finish(inner, "ok")
        return {}
    j = _job(Step("forecast", "Prognosen", save_forecast))
    with _clock(_at(2026, 10, 8, 7, 0)) as clock:
        [ran] = _tick(clock, j)
        [inner] = job_runs.recent("forecast")
        assert inner["triggered_by"] == "schedule"
        assert seen["job_run"] == ran["id"]
        # And only for the length of the run.
        assert job_runs.trigger.get() == "user" and db.job_run.get() is None

        by_hand = asyncio.run(scheduler.run(j, triggered_by="user"))
        assert by_hand["slot"] is None
        assert job_runs.recent("forecast", 1)[0]["triggered_by"] == "user"


def test_a_job_already_running_is_not_started_twice():
    step, calls = _step("forecast", "Prognosen", {})
    j = _job(step)
    with _clock(_at(2026, 10, 8, 7, 0)) as clock:
        scheduler._running.add(j.name)
        try:
            asyncio.run(scheduler.run(j, triggered_by="user"))
            raise AssertionError("a second run was started")
        except scheduler.Busy:
            pass
        assert _tick(clock, j) == [] and calls == []
        scheduler._running.clear()


def test_a_database_that_will_not_record_cannot_make_it_run_every_minute():
    step, calls = _step("summary", "Oppsummeringen", {})
    j = _job(step)
    real = job_runs.start
    job_runs.start = lambda *a, **k: None         # nothing is ever recorded
    try:
        with _clock(_at(2026, 10, 8, 7, 0)) as clock:
            _tick(clock, j)
            for minute in (1, 2, 29):
                clock.at = _at(2026, 10, 8, 7, minute)
                assert _tick(clock, j) == []
            clock.at = _at(2026, 10, 8, 7, 30)
            _tick(clock, j)
            assert len(calls) == 2
    finally:
        job_runs.start = real


def test_the_summary_step_fails_when_todays_text_was_not_written():
    real = summary.cached
    try:
        async def no_credit(refresh=False):
            return {"error": "Ingen kreditt på Anthropic-kontoen, så CFO-en får "
                             "ikke skrevet oppsummeringen. Tallene under er uberørt."}
        summary.cached = no_credit
        try:
            asyncio.run(scheduler._summary())
            raise AssertionError("an unwritten summary passed")
        except scheduler.StepFailed as exc:
            assert str(exc).startswith("Ingen kreditt")

        async def yesterdays(refresh=False):
            return {"verdict": "Solid drift", "text": "…", "written": "2026-10-07",
                    "stale": True}
        summary.cached = yesterdays
        try:
            asyncio.run(scheduler._summary())
            raise AssertionError("yesterday's summary passed as today's")
        except scheduler.StepFailed as exc:
            assert "onsdag 7. oktober" in str(exc)

        async def written(refresh=False):
            return {"verdict": "Solid drift", "text": "…", "written": "2026-10-08"}
        summary.cached = written
        assert asyncio.run(scheduler._summary()) == {"verdict": "Solid drift",
                                                     "written": "2026-10-08"}
    finally:
        summary.cached = real


def test_the_morning_checks_before_it_writes():
    names = [s.name for s in scheduler.MORNING.steps]
    assert names == ["checks", "forecast", "figures", "cards", "watch", "summary"]
    assert scheduler.MORNING.at == time(7, 0)
    assert scheduler.job("morning") is scheduler.MORNING
