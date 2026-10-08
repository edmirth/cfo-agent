"""Every run of anything that does work: what it was, what it cost, how it went.

One row in `job_runs` per chat turn, summary, industry decision, forecast
save and scheduled run — and later the watch and the brief. The row is
inserted as `running` when the job starts and closed when it ends. A job the
server dies in the middle of is closed as failed when the next server starts
(`close_orphans`), so it shows as one that never finished (card 6).

While a job runs, its id is in `db.job_run`, and the rows it writes —
findings, predictions, cards, messages — carry it. "Where did this card come
from?" then has an answer.

Recording must never cost the job itself: a failure to write here is logged
and the work goes on.
"""
import logging
from contextvars import ContextVar

import db

log = logging.getLogger("cfo.job_runs")

STATUSES = ("ok", "partial", "failed")
ORPHANED = "Serveren stoppet før jobben ble ferdig."

# Who set the work in progress going: the scheduler sets "schedule" for the
# length of its run, so the forecast and the summary it causes are filed as
# the schedule's without every function in between passing it down. A
# ContextVar, like `db.job_run`, so a chat at the same time stays "user".
trigger: ContextVar[str] = ContextVar("trigger", default="user")


def start(job: str, triggered_by: str | None = None,
          model: str | None = None) -> int | None:
    """Open a run. Returns its id, or None when it could not be recorded."""
    triggered_by = triggered_by or trigger.get()
    try:
        with db.tx() as conn:
            return conn.execute(
                "INSERT INTO job_runs (company_id, job, triggered_by, status, "
                "started_at, model) VALUES (?, ?, ?, 'running', ?, ?) RETURNING id",
                (db.company_id(), job, triggered_by, db.now(), model)).fetchone()[0]
    except Exception:  # noqa: BLE001 — the job matters more than its record
        log.exception("Kunne ikke registrere jobben %s", job)
        return None


def finish(run_id: int | None, status: str, usage: dict | None = None,
           cost_usd: float | None = None, unverified: int | None = None,
           error: str | None = None, details: dict | None = None) -> None:
    """Close a run with what it cost and how it ended."""
    if run_id is None:
        return
    if status not in STATUSES:
        raise ValueError(f"Ukjent status {status}")
    u = usage or {}
    try:
        with db.tx() as conn:
            conn.execute(
                "UPDATE job_runs SET status = ?, finished_at = ?, error = ?, "
                "input_tokens = ?, output_tokens = ?, cache_read_tokens = ?, "
                "cost_usd = ?, unverified = ?, details = ? "
                "WHERE id = ? AND company_id = ?",
                (status, db.now(), error, u.get("input"), u.get("output"),
                 u.get("cache_read"), cost_usd, unverified, db.dumps(details),
                 run_id, db.company_id()))
    except Exception:  # noqa: BLE001
        log.exception("Kunne ikke avslutte jobbregistreringen %s", run_id)


def close_orphans() -> int:
    """Close the runs a previous server left open, as failed.

    Called once at startup. `lock.py` guarantees no other server is running,
    so every run still marked running belongs to one that stopped — killed,
    restarted by `--reload`, or the Mac shut down mid-run.
    """
    try:
        with db.tx() as conn:
            n = conn.execute(
                "UPDATE job_runs SET status = 'failed', finished_at = ?, error = ? "
                "WHERE company_id = ? AND status = 'running'",
                (db.now(), ORPHANED, db.company_id())).rowcount
    except Exception:  # noqa: BLE001
        log.exception("Kunne ikke lukke jobber som ble stående")
        return 0
    if n:
        log.warning("%d jobb(er) ble stående da serveren sist stoppet — "
                    "lukket som feilet", n)
    return n


def since(job: str, after: str) -> list[dict]:
    """The runs of `job` started at or after `after` (UTC, as `db.now()`
    writes it), oldest first: the attempts at one scheduled slot."""
    with db.read() as conn:
        rows = conn.execute(
            "SELECT * FROM job_runs WHERE company_id = ? AND job = ? "
            "AND started_at >= ? ORDER BY id", (db.company_id(), job, after)).fetchall()
    return [dict(r, details=db.loads(r["details"], {})) for r in rows]


def recent(job: str | None = None, limit: int = 50) -> list[dict]:
    """The latest runs, newest first."""
    sql = "SELECT * FROM job_runs WHERE company_id = ?"
    args: list = [db.company_id()]
    if job:
        sql += " AND job = ?"
        args.append(job)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with db.read() as conn:
        rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        rec = dict(r)
        rec["details"] = db.loads(rec.get("details"), {})
        out.append(rec)
    return out
