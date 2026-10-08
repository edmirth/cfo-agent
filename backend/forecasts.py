"""The forecasts the CFO made, and the bank balances to hold them against.

A forecast nobody keeps cannot be scored, and the playbook's proof that this
one can be trusted — "four weeks ahead, within about ±10 %, eight weeks
running" — needs weeks of saved forecasts before it says anything. So from the
first day:

- **`forecast_runs`** — the 13-week forecast, once a day: the opening and
  where it came from, both low points, the assumptions and the definitions in
  force. With it its 13 weeks (`forecast_weeks`) and every line behind them
  (`forecast_flows`), so a miss can later be put down to a kind of flow.
- **`bank_balances`** — what each bank account held that day, booked
  (`ledger`) and in the bank (`bank_feed`). This is the actual a forecast is
  scored against (card 5).

Written from the forecast build itself, which runs whenever the forecast is
fresh — and every working morning from the scheduler (card 6), so a day
nobody opens the app still has its row. A day the server was off has none;
the scoring has to live with gaps rather than invent them.

Nothing here may cost the forecast: `record` is called inside a guard, and a
failure to save is logged, not raised.
"""
import logging
from datetime import date

import db
import definitions
import job_runs

log = logging.getLogger("cfo.forecasts")


def record(data: dict, ledger: dict[str, float], today: date) -> dict:
    """Save today's forecast and bank balances. Returns what was written.

    `ledger` is the booked closing balance per bank account. The forecast is
    kept once per day — the first whole build of the day — and only when it
    is whole: a forecast missing a register would be scored as if it were a
    forecast. The balances are a measurement of the day and are replaced by a
    later, fresher reading of the same day.
    """
    written = {"forecast_run": None, "balances": 0}
    with db.tx() as conn:
        written["balances"] = _balances(conn, data, ledger, today)
    if data.get("partial") or kept(today):
        return written
    # A run of its own, so the saved forecast can say which run made it — and
    # only when one is saved: the build runs every ten minutes in use.
    run = job_runs.start("forecast")
    token = db.job_run.set(run)
    try:
        with db.tx() as conn:
            written["forecast_run"] = _forecast(conn, data, today, run)
        job_runs.finish(run, "ok", details=written)
    except Exception as exc:
        job_runs.finish(run, "failed", error=str(exc), details=written)
        raise
    finally:
        db.job_run.reset(token)
    return written


def kept(today: date) -> bool:
    """Whether today's forecast is saved."""
    with db.read() as conn:
        return conn.execute(
            "SELECT 1 FROM forecast_runs WHERE company_id = ? AND made_on = ? "
            "AND purpose = 'weekly'", (db.company_id(), today.isoformat())
        ).fetchone() is not None


def _balances(conn, data: dict, ledger: dict[str, float], today: date) -> int:
    cid = db.company_id()
    rows = [(cid, today.isoformat(), acct, "ledger", db.to_ore(kr))
            for acct, kr in ledger.items()]
    # The bank's own figure only where every month of it could be read. A
    # partly-known adjustment is not a balance anyone should be scored on.
    # The feed is as of its last line, so that is the day it is filed under.
    bank = data.get("bank") or {}
    if bank.get("known") and bank.get("adjustment") is not None:
        on = bank.get("latest") or today.isoformat()
        adjusted = {a["account"]: a["adjustment"] for a in bank.get("accounts") or []}
        rows += [(cid, on, acct, "bank_feed", db.to_ore(kr + adjusted.get(acct, 0.0)))
                 for acct, kr in ledger.items()]
    conn.executemany(
        "INSERT OR REPLACE INTO bank_balances (company_id, on_date, account, "
        "source, balance_ore) VALUES (?, ?, ?, ?, ?)", rows)
    return len(rows)


def _forecast(conn, data: dict, today: date, run: int | None) -> int | None:
    cid = db.company_id()
    bank = data.get("bank") or {}
    low_c, low_e = data.get("low_committed") or {}, data.get("low_expected") or {}
    try:
        stamp = definitions.stamp().get("definitions_hash")
    except Exception:  # noqa: BLE001 — a forecast is better kept unstamped than lost
        stamp = None
    row = conn.execute(
        "INSERT INTO forecast_runs (company_id, made_on, purpose, opening_ore, "
        "opening_source, low_committed_ore, low_committed_week, low_expected_ore, "
        "low_expected_week, assumptions, definitions_hash, job_run_id, items) "
        "VALUES (?, ?, 'weekly', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT DO NOTHING RETURNING id",
        (cid, today.isoformat(), db.to_ore(data["opening"]),
         "bank_feed" if bank.get("adjustment") is not None else "ledger",
         db.to_ore(low_c.get("amount")), low_c.get("start"),
         db.to_ore(low_e.get("amount")), low_e.get("start"),
         db.dumps(data.get("assumptions") or {}), stamp, run,
         db.dumps(data.get("items")))).fetchone()
    if row is None:
        return None                     # today's is already kept
    run_id = row[0]
    weeks = data.get("weeks") or []
    conn.executemany(
        "INSERT INTO forecast_weeks (company_id, run_id, week_no, week_start, "
        "committed_close_ore, expected_close_ore) VALUES (?, ?, ?, ?, ?, ?)",
        [(cid, run_id, w["index"], w["start"], db.to_ore(w["committed_close"]),
          db.to_ore(w["expected_close"])) for w in weeks])
    conn.executemany(
        "INSERT INTO forecast_flows (company_id, run_id, week_no, scenario, kind, "
        "label, amount_ore) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(cid, run_id, w["index"], i["scenario"], i["kind"], i.get("label"),
          db.to_ore(i["amount"])) for w in weeks for i in w.get("items") or []])
    log.info("Prognosen for %s lagret: %d uker, %d linjer", today.isoformat(),
             len(weeks), sum(len(w.get("items") or []) for w in weeks))
    return run_id


# ------------------------------------------------------------------- reads
def runs(limit: int = 30) -> list[dict]:
    """The latest saved forecasts, newest first, in kroner."""
    with db.read() as conn:
        rows = conn.execute(
            "SELECT * FROM forecast_runs WHERE company_id = ? "
            "ORDER BY made_on DESC, id DESC LIMIT ?",
            (db.company_id(), limit)).fetchall()
        out = []
        for r in rows:
            weeks = conn.execute(
                "SELECT week_no, week_start, committed_close_ore, expected_close_ore "
                "FROM forecast_weeks WHERE run_id = ? ORDER BY week_no",
                (r["id"],)).fetchall()
            out.append({
                "id": r["id"], "made_on": r["made_on"], "purpose": r["purpose"],
                "opening": db.to_kr(r["opening_ore"]),
                "opening_source": r["opening_source"],
                "low_committed": {"amount": db.to_kr(r["low_committed_ore"]),
                                  "start": r["low_committed_week"]},
                "low_expected": {"amount": db.to_kr(r["low_expected_ore"]),
                                 "start": r["low_expected_week"]},
                "assumptions": db.loads(r["assumptions"], {}),
                "definitions_hash": r["definitions_hash"],
                "weeks": [{"week_no": w["week_no"], "start": w["week_start"],
                           "committed_close": db.to_kr(w["committed_close_ore"]),
                           "expected_close": db.to_kr(w["expected_close_ore"])}
                          for w in weeks]})
    return out


def balances(source: str = "bank_feed", account: str | None = None,
             since: str | None = None) -> list[dict]:
    """The balances kept, oldest first: what a forecast is scored against."""
    sql = ("SELECT on_date, account, source, balance_ore FROM bank_balances "
           "WHERE company_id = ? AND source = ?")
    args: list = [db.company_id(), source]
    if account:
        sql += " AND account = ?"
        args.append(account)
    if since:
        sql += " AND on_date >= ?"
        args.append(since)
    with db.read() as conn:
        rows = conn.execute(sql + " ORDER BY on_date, account", args).fetchall()
    return [{"on_date": r["on_date"], "account": r["account"], "source": r["source"],
             "balance": db.to_kr(r["balance_ore"])} for r in rows]
