"""What runs without anyone asking, and when.

Nothing in the early-warning lane is early while somebody has to think to ask
for it. So every Norwegian working day at 07:00 the morning's work runs on its
own: the books are checked, today's forecast is built and kept, the figures
fetched, the deck rebuilt and the day's summary written. The brief is waiting
when the CEO opens the page, and a day nobody opens it still has a forecast to
score (card 5) and a snapshot for the trend.

**Inside the server, not beside it.** Only one process may talk to Tripletex
(`lock.py`): a second one renewing the same refresh token locks the account
out. A cron job that started its own copy of the app would be that second
process. So the scheduler is a task in the server's own event loop, and runs
exactly when the server does — on the Mac for now, on a host later, with no
change here.

**A clock, not a sleep.** A Mac sleeps with its lid shut. A task told to sleep
until 07:00 wakes late by however long the machine slept; this loop looks at
the wall clock every minute instead, so the first minute after the Mac wakes
is the minute it notices.

**Once per slot, caught up the same day.** A run belongs to its slot —
Thursday 07:00 — and `job_runs` says whether the slot has had one. A Mac
opened at 09:30 runs the morning it missed then. One first opened the next day
does not run yesterday's: today's slot is the one owed, and three missed
mornings are one run, not three.

**Never silent.** Every run is a row in `job_runs` with what each step did. A
step that fails costs that step, not the run: the summary failing for want of
credit still leaves the forecast kept, and the run says `partial`. A run that
did not finish is tried again half an hour later, three times at most. A run
that failed, and a morning missed because the server was off, are both said
on the front page (`status`) — the server log is not something a CEO reads.

The Monday brief (card 7) is a job of its own, on the first working day of
each week, run straight after the morning. Card 9 (sending it) and card 12
(the morning watch) add their steps here.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic
from zoneinfo import ZoneInfo

import brief
import cards
import cashflow
import commitments
import config
import db
import forecasts
import job_runs
import overview
import preflight
import summary
import workdays
from mcp_client import McpError
from tlx_oauth import OAuthError

log = logging.getLogger("cfo.scheduler")

TZ = ZoneInfo(config.TIMEZONE)
TICK_SECONDS = 60
MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=30)
# Far enough to step over Easter, the longest run of days off in the year.
LOOK_DAYS = 14

DAYS = ("mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag")
MONTHS = ("januar", "februar", "mars", "april", "mai", "juni", "juli",
          "august", "september", "oktober", "november", "desember")


class StepFailed(RuntimeError):
    """A step that ended without doing its work. The message is already the
    sentence for the front page."""


class Busy(RuntimeError):
    """The job is already running."""


@dataclass(frozen=True)
class Step:
    """One piece of a run. `run` returns what it found; `partial: True` in it
    marks a step that ran without everything it needed, with `cause` saying
    what. Raising fails the step."""
    name: str
    label: str
    run: Callable[[], Awaitable[dict | None]]


@dataclass(frozen=True)
class Scheduled:
    name: str                       # job_runs.job
    label: str                      # what the front page calls it
    at: time                        # local time, in TZ
    runs_on: Callable[[date], bool]
    days: str                       # runs_on, in words
    steps: tuple[Step, ...]


def now() -> datetime:
    """The scheduler's clock: aware, in the company's time zone."""
    return datetime.now(TZ)


# ------------------------------------------------------------------- the work
async def _checks() -> dict:
    pf = await preflight.cached()
    out = {"condition": pf.get("condition"),
           "flagged": sum(c.get("status") in ("warn", "note")
                          for c in pf.get("checks") or [])}
    if pf.get("failed"):
        return {**out, "partial": True,
                "cause": f"Tripletex svarte ikke på {len(pf['failed'])} av "
                         f"kontrollene."}
    return out


async def _forecast() -> dict:
    cf = await cashflow.cached()
    low = cf.get("low_committed") or {}
    out = {"low_point": low.get("amount"), "low_week": low.get("start")}
    # The build keeps the forecast itself, and swallows a failure to save so
    # the page still gets one. Asked again here, or a forecast that was never
    # kept would pass as one that was.
    if cf.get("partial"):
        return {**out, "partial": True,
                "cause": "Tripletex svarte ikke på alle oppslagene, så "
                         "prognosen er ufullstendig og ble ikke lagret."}
    if not forecasts.kept(date.today()):
        return {**out, "partial": True,
                "cause": "Prognosen ble regnet ut, men ikke lagret."}
    return out


async def _figures() -> dict:
    ov, com = await asyncio.gather(overview.cached(), commitments.cached())
    out = {"bank": (ov.get("kpis") or {}).get("bank"),
           "free_now": com.get("free_now")}
    if ov.get("partial"):
        return {**out, "partial": True,
                "cause": "Tripletex svarte ikke på alle rapportene, så dagens "
                         "nøkkeltall ble ikke lagret."}
    return out


async def _cards() -> dict:
    deck = await cards.refresh()
    return {"open": len(deck.get("open") or [])}


async def _summary() -> dict:
    s = await summary.cached()
    if s.get("error"):
        raise StepFailed(s["error"])
    if s.get("stale"):
        raise StepFailed(f"Dagens tekst ble ikke skrevet, så forsiden viser "
                         f"den fra {_date(date.fromisoformat(s['written']))}. "
                         f"Grunnen står i serverloggen.")
    return {"verdict": s.get("verdict"), "written": s.get("written")}


async def _brief() -> dict:
    try:
        b = await brief.write()
    except brief.BriefError as exc:
        raise StepFailed(str(exc)) from exc
    out = {"light": b["light"], "period": b["period"],
           "decisions": b["decisions"]["count"], "written_by": b["written_by"]}
    if b["written_by"] != "model":
        return {**out, "partial": True,
                "cause": "Brevet ble skrevet ut fra tallene alene, uten CFO-ens "
                         "egne ord. Grunnen står i serverloggen."}
    if b.get("forecast_partial"):
        return {**out, "partial": True,
                "cause": "Prognosen manglet noe fra Tripletex da brevet ble skrevet."}
    return out


def first_working_day_of_week(d: date) -> bool:
    """Monday, or the day after when Monday is a holiday (Easter, Whit)."""
    monday = d - timedelta(days=d.weekday())
    return d == workdays.forward(monday) and d.isocalendar()[1] == monday.isocalendar()[1]


def _at(text: str) -> time:
    try:
        return time.fromisoformat(text)
    except ValueError:
        raise SystemExit(f"CFO_MORNING_AT må være TT:MM, fikk «{text}»") from None


# Checks and forecast first: the cards and the summary are built from them,
# and read them from the cache rather than asking Tripletex twice.
MORNING = Scheduled(
    name="morning", label="Morgenkjøringen", at=_at(config.MORNING_AT),
    runs_on=workdays.is_working_day, days="virkedager",
    steps=(Step("checks", "Kontrollene", _checks),
           Step("forecast", "Prognosen", _forecast),
           Step("figures", "Nøkkeltallene", _figures),
           Step("cards", "Sakene", _cards),
           Step("summary", "Oppsummeringen", _summary)))

# After the morning, in the same minute: `tick` runs jobs in this order, so the
# brief reads the forecast, checks and deck the morning has just made fresh.
WEEKLY = Scheduled(
    name="weekly_brief", label="Mandagsbrevet", at=MORNING.at,
    runs_on=first_working_day_of_week, days="første virkedag i uka",
    steps=(Step("brief", "Mandagsbrevet", _brief),))

JOBS: tuple[Scheduled, ...] = (MORNING, WEEKLY)


def job(name: str) -> Scheduled:
    for j in JOBS:
        if j.name == name:
            return j
    raise KeyError(f"Ingen planlagt jobb som heter «{name}».")


# ------------------------------------------------------------------- the clock
def _slots(j: Scheduled, before: datetime) -> Iterator[datetime]:
    """The job's slots at or before `before`, latest first."""
    local = before.astimezone(TZ)
    for back in range(LOOK_DAYS + 1):
        d = local.date() - timedelta(days=back)
        if j.runs_on(d):
            slot = datetime.combine(d, j.at, TZ)
            if slot <= local:
                yield slot


def last_slot(j: Scheduled, at: datetime) -> datetime | None:
    return next(_slots(j, at), None)


def next_slot(j: Scheduled, after: datetime) -> datetime | None:
    local = after.astimezone(TZ)
    for ahead in range(LOOK_DAYS + 1):
        d = local.date() + timedelta(days=ahead)
        if j.runs_on(d):
            slot = datetime.combine(d, j.at, TZ)
            if slot > local:
                return slot
    return None


def _utc(dt: datetime) -> str:
    """As `db.now()` writes it, so stored times compare as text."""
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


def _owed(j: Scheduled, at: datetime) -> tuple[datetime | None, list[dict]]:
    """Today's slot if it has passed, and the runs since it, oldest first.
    Only today's: a morning missed yesterday is not run today."""
    slot = last_slot(j, at)
    if slot is None or slot.date() != at.astimezone(TZ).date():
        return None, []
    return slot, job_runs.since(j.name, _utc(slot))


def _retry_at(tries: list[dict]) -> datetime | None:
    """When the next attempt at the slot is allowed, or None when it is done
    or given up on."""
    if not tries:
        return None
    if any(r["status"] in ("ok", "running") for r in tries):
        return None
    if len(tries) >= MAX_ATTEMPTS:
        return None
    # From when the attempt started, not when it ended: a run the server died
    # in "ended" when the next server closed it, and is owed again at once.
    return _parse(tries[-1]["started_at"]) + RETRY_AFTER


def due(j: Scheduled, at: datetime) -> datetime | None:
    """The slot to run now, or None."""
    slot, tries = _owed(j, at)
    if slot is None:
        return None
    if not tries:
        return slot
    retry = _retry_at(tries)
    if retry is not None and at >= retry and retry.astimezone(TZ).date() == slot.date():
        return slot
    return None


# ------------------------------------------------------------------- running
_running: set[str] = set()
# The slot each job last started, and when. Should the database refuse to
# record a run, `due` would hand the same slot back every minute, and the
# summary is a paid model call; this holds it to once per RETRY_AFTER anyway.
_tried: dict[str, tuple[datetime, datetime]] = {}


LOGIN = ("Tripletex-innloggingen virker ikke, så ingen tall kunne hentes. "
         "Kjør ./.venv/bin/python scripts/oauth_login.py.")


def _login(exc: BaseException) -> bool:
    """A Tripletex login only a person can mend. The module that hit it
    often wraps it in its own error, so its fix is looked for in the words."""
    return isinstance(exc, OAuthError) or "oauth_login.py" in str(exc)


def _cause(exc: BaseException) -> str:
    """Why a step failed, in words the CEO can act on. The provider's own
    words, with their request ids, stay in the log and in `job_runs.error`."""
    if _login(exc):
        return LOGIN
    if isinstance(exc, StepFailed):
        return str(exc)              # already written for a person
    if isinstance(exc, McpError):
        return "Tripletex svarte ikke på oppslaget."
    if "credit balance is too low" in str(exc):
        return "Det er ikke kreditt på Anthropic-kontoen."
    return "Noe feilet. Detaljene ligger i serverloggen."


async def _step(step: Step) -> dict:
    began = monotonic()
    try:
        found = dict(await step.run() or {})
    except Exception as exc:  # noqa: BLE001 — one step must not stop the rest
        log.exception("%s feilet", step.label)
        return {"step": step.name, "label": step.label, "status": "failed",
                "error": str(exc)[:500], "cause": _cause(exc),
                "login": _login(exc), "seconds": round(monotonic() - began, 1)}
    status = "partial" if found.pop("partial", False) else "ok"
    return {"step": step.name, "label": step.label, "status": status, **found,
            "seconds": round(monotonic() - began, 1)}


def _overall(steps: list[dict]) -> str:
    said = {s["status"] for s in steps}
    if said <= {"ok"}:
        return "ok"
    return "failed" if said == {"failed"} else "partial"


async def run(j: Scheduled, slot: datetime | None = None,
              triggered_by: str = "schedule") -> dict:
    """Run every step of `j` once, in order, and record how it went.

    `slot` is the time the run is for; a run asked for by hand has none.
    Everything the steps record — the forecast kept, the cards written — is
    filed under this run and this trigger.
    """
    if j.name in _running:
        raise Busy(f"{j.label} kjører allerede.")
    _running.add(j.name)
    run_id = job_runs.start(j.name, triggered_by)
    trigger = job_runs.trigger.set(triggered_by)
    current = db.job_run.set(run_id)
    steps: list[dict] = []
    details = {"slot": slot.isoformat() if slot else None, "steps": steps}
    log.info("%s startet%s", j.label,
             f" for {slot:%Y-%m-%d %H:%M}" if slot else " for hånd")
    try:
        for step in j.steps:
            steps.append(await _step(step))
    except asyncio.CancelledError:
        job_runs.finish(run_id, "failed", details=details,
                        error="Avbrutt: serveren stoppet midt i kjøringen.")
        raise
    finally:
        db.job_run.reset(current)
        job_runs.trigger.reset(trigger)
        _running.discard(j.name)

    status = _overall(steps)
    failed = [s for s in steps if s["status"] == "failed"]
    job_runs.finish(run_id, status, details=details,
                    error="; ".join(f"{s['step']}: {s['error']}" for s in failed) or None)
    if status == "ok":
        log.info("%s ferdig", j.label)
    else:
        log.error("%s %s. %s", j.label,
                  "feilet" if status == "failed" else "ble ikke helt ferdig",
                  _why([s for s in steps if s["status"] != "ok"]))
    return {"id": run_id, "job": j.name, "status": status, **details}


async def tick(at: datetime | None = None,
               jobs: tuple[Scheduled, ...] | None = None) -> list[dict]:
    """Run whatever is due. One pass of the loop; the tests drive it directly."""
    at = at or now()
    done = []
    for j in jobs or JOBS:
        slot = due(j, at)
        if slot is None or j.name in _running:
            continue
        tried = _tried.get(j.name)
        if tried and tried[0] == slot and at < tried[1] + RETRY_AFTER:
            continue
        _tried[j.name] = (slot, at)
        done.append(await run(j, slot))
    return done


async def _loop() -> None:
    while True:
        try:
            await tick()
        except Exception:  # noqa: BLE001 — the loop must outlive any one tick
            log.exception("Planleggeren feilet i en runde")
        await asyncio.sleep(TICK_SECONDS)


_task: asyncio.Task | None = None


def start() -> None:
    """Start the loop in the server's event loop. Called once, at startup."""
    global _task
    if not config.SCHEDULER:
        log.info("Planlagte kjøringer er slått av (CFO_SCHEDULER=off)")
        return
    for j in JOBS:
        nxt = next_slot(j, now())
        log.info("Planlagt: %s %s kl %s (%s), neste %s", j.label.lower(),
                 j.days, f"{j.at:%H:%M}", config.TIMEZONE,
                 _when(nxt, now()) if nxt else "ingen")
    _task = asyncio.create_task(_loop(), name="scheduler")


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None


def running() -> bool:
    return _task is not None and not _task.done()


# ------------------------------------------------------------------- telling
def _date(d: date) -> str:
    return f"{DAYS[d.weekday()]} {d.day}. {MONTHS[d.month - 1]}"


def _when(dt: datetime, at: datetime) -> str:
    """«i dag kl 07:00», «i morgen kl 07:00», «mandag 12. oktober kl 07:00»."""
    local, today = dt.astimezone(TZ), at.astimezone(TZ).date()
    day = ("i dag" if local.date() == today
           else "i morgen" if local.date() == today + timedelta(days=1)
           else "i går" if local.date() == today - timedelta(days=1)
           else _date(local.date()))
    return f"{day} kl {local:%H:%M}"


def _why(steps: list[dict]) -> str:
    """«Prognosen og nøkkeltallene: Tripletex svarte ikke på oppslaget.»
    Each reason once. A dead Tripletex login explains every other failure
    that came with it, so it is said alone."""
    if any(s.get("login") for s in steps):
        return LOGIN
    by: dict[str, list[str]] = {}
    for s in steps:
        by.setdefault(s.get("cause") or "", []).append(s["label"])
    out = []
    for cause, labels in by.items():
        names = (labels[0] if len(labels) == 1
                 else ", ".join(labels[:-1]) + " og " + labels[-1])
        names = names[0] + names[1:].lower()
        out.append(f"{names}: {cause}" if cause else names)
    return " ".join(out)


def _attention(j: Scheduled, at: datetime, last: dict | None) -> str | None:
    """The sentence the front page shows when the last run did not do its
    job, or None when it did."""
    nxt = next_slot(j, at)
    then = f"Neste kjøring {_when(nxt, at)}." if nxt else ""
    # A missed morning first: it is newer than any run there is.
    slot = last_slot(j, at)
    if slot is not None and (last is None or _parse(last["started_at"]) < slot):
        if slot.date() == at.astimezone(TZ).date():
            return None              # owed today, and about to run
        return (f"{j.label} {_when(slot, at)} ble ikke kjørt, fordi serveren "
                f"ikke var i gang. {then}").strip()
    if last is None or last["status"] in ("ok", "running"):
        return None
    ran = (_parse(last["details"]["slot"]) if (last.get("details") or {}).get("slot")
           else _parse(last["started_at"]))
    verb = "feilet" if last["status"] == "failed" else "ble ikke helt ferdig"
    steps = (last.get("details") or {}).get("steps") or []
    why = (_why([s for s in steps if s.get("status") != "ok"]) if steps
           else last.get("error") or "")
    _, tries = _owed(j, at)
    retry = _retry_at(tries)
    if retry is not None and retry.astimezone(TZ).date() == at.astimezone(TZ).date():
        then = ("Prøver igjen straks." if retry <= at
                else f"Prøver igjen kl {retry.astimezone(TZ):%H:%M}.")
    return " ".join(p for p in (f"{j.label} {_when(ran, at)} {verb}.", why, then) if p)


def status(at: datetime | None = None,
           jobs: tuple[Scheduled, ...] | None = None) -> dict:
    """What is planned, how the last run went, and anything to say about it."""
    at = at or now()
    out = []
    for j in jobs or JOBS:
        recent = job_runs.recent(j.name, 1)
        last = recent[0] if recent else None
        nxt = next_slot(j, at)
        out.append({
            "name": j.name, "label": j.label, "at": f"{j.at:%H:%M}", "days": j.days,
            "next_run": nxt.isoformat() if nxt else None,
            "last_run": last and {
                "id": last["id"], "status": last["status"],
                "triggered_by": last["triggered_by"],
                "started_at": last["started_at"], "finished_at": last["finished_at"],
                "steps": [{k: s.get(k) for k in ("step", "label", "status", "cause")}
                          for s in (last.get("details") or {}).get("steps") or []]},
            "attention": _attention(j, at, last) if config.SCHEDULER else None,
        })
    return {"enabled": config.SCHEDULER, "running": running(),
            "timezone": config.TIMEZONE, "jobs": out}
