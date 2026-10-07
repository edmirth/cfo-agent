"""Every run of anything that does work: what it was, what it cost, how it went.

One row in `job_runs` per chat turn, summary, industry decision — and later
the forecast save, the watch and the brief. The row is inserted as `running`
when the job starts and closed when it ends, so a job that dies half-way is
still visible as one that never finished (card 6 asks for exactly that).

While a job runs, its id is in `db.job_run`, and the rows it writes —
findings, predictions, cards, messages — carry it. "Where did this card come
from?" then has an answer.

Recording must never cost the job itself: a failure to write here is logged
and the work goes on.
"""
import logging

import db

log = logging.getLogger("cfo.job_runs")

STATUSES = ("ok", "partial", "failed")


def start(job: str, triggered_by: str = "user", model: str | None = None) -> int | None:
    """Open a run. Returns its id, or None when it could not be recorded."""
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
