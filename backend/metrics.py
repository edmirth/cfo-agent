"""Whether the product works, measured the way the playbook says.

"What to measure (not daily active users): CEO time per week (target under
10 minutes), share of prepared actions approved without edits, problems
caught early, e.g. cash dips flagged weeks ahead" — and the agent's cost per
company, for the margins. For the product owner, never shown to the
customer.

Everything here is read from what the product already keeps; nothing is
estimated:

- **Time in the app** — `activity`, one row per minute the app was open and in
  focus. What was looked at is not recorded.
- **Decisions** — `card_events`: how many, how many approved, how many of
  those with the draft as it was written, and how long from the card
  appearing to the decision.
- **Cash dips** — a week the bank's own balance (`bank_balances`,
  `bank_feed`) closed under the floor. Its warning is the first saved
  forecast (`forecast_weeks`) whose committed line had that week under the
  floor too: how many weeks before it, or none.
- **Agent cost** — `job_runs.cost_usd`, by week and job.

The floor is today's, from the rulebook: no history of it is kept, so a
changed floor re-measures the past.
"""
import logging
import statistics
from datetime import date, datetime, timedelta, timezone

import company
import db
import forecasts

log = logging.getLogger("cfo.metrics")

WEEKS = 8
TARGET_MINUTES = 10          # the playbook's CEO time per week


def _week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _monday(week: str) -> date:
    y, w = week.split("-W")
    return date.fromisocalendar(int(y), int(w), 1)


def _when(stamp: str) -> datetime:
    """A stored time, date-only ones as midnight UTC."""
    t = datetime.fromisoformat(stamp)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _weeks(today: date, n: int = WEEKS) -> list[str]:
    return [_week(today - timedelta(weeks=i)) for i in range(n)]


# ------------------------------------------------------------- recording
def ping(user: str, at: datetime | None = None) -> None:
    """The app is open and in focus for `user` this minute."""
    at = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with db.tx() as conn:
        conn.execute("INSERT OR IGNORE INTO activity (company_id, user_email, minute) "
                     "VALUES (?, ?, ?)", (db.company_id(), user, at.strftime("%Y-%m-%dT%H:%M")))


# ------------------------------------------------------------- measuring
def minutes(conn, cid: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for (minute,) in conn.execute("SELECT minute FROM activity WHERE company_id = ?", (cid,)):
        wk = _week(datetime.fromisoformat(minute).date())
        out[wk] = out.get(wk, 0) + 1
    return out


def decisions(conn, cid: int) -> dict[str, dict]:
    created = {r["card_id"]: r["at"] for r in conn.execute(
        "SELECT card_id, min(at) AS at FROM card_events WHERE company_id = ? "
        "AND event = 'created' GROUP BY card_id", (cid,))}
    out: dict[str, dict] = {}
    for r in conn.execute(
            "SELECT card_id, at, effect, draft_edited FROM card_events "
            "WHERE company_id = ? AND event = 'decided' ORDER BY at", (cid,)):
        at = _when(r["at"])
        w = out.setdefault(_week(at.date()), {"decided": 0, "approved": 0,
                                              "approved_unedited": 0, "approved_edited": 0,
                                              "hours": []})
        w["decided"] += 1
        if r["effect"] == "approve":
            w["approved"] += 1
            w["approved_edited" if r["draft_edited"] == 1 else "approved_unedited"] += 1
        if r["card_id"] in created:
            w["hours"].append((at - _when(created[r["card_id"]])).total_seconds() / 3600)
    for w in out.values():
        hours = w.pop("hours")
        w["median_hours_to_decide"] = round(statistics.median(hours), 1) if hours else None
        w["unedited_pct"] = (round(w["approved_unedited"] / w["approved"] * 100, 1)
                             if w["approved"] else None)
    return out


def cost(conn, cid: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in conn.execute("SELECT job, started_at, cost_usd FROM job_runs WHERE company_id = ?",
                          (cid,)):
        w = out.setdefault(_week(_when(r["started_at"]).date()),
                           {"usd": 0.0, "runs": 0, "unpriced": 0, "by_job": {}})
        w["runs"] += 1
        if r["cost_usd"] is None:
            w["unpriced"] += 1
            continue
        w["usd"] = round(w["usd"] + r["cost_usd"], 4)
        w["by_job"][r["job"]] = round(w["by_job"].get(r["job"], 0.0) + r["cost_usd"], 4)
    return out


def _floor() -> dict:
    runs = forecasts.runs(1)
    wages = (runs[0]["assumptions"] or {}).get("monthly_wages") if runs else None
    return company.rules(wages)["likviditetsgulv_kr"]


def dips(conn, cid: int, floor_kr: float) -> list[dict]:
    """Weeks the bank's own balance closed under the floor, newest first,
    with the weeks of warning the forecasts gave."""
    closes: dict[str, tuple[str, int]] = {}
    for r in conn.execute(
            "SELECT on_date, sum(balance_ore) AS ore FROM bank_balances WHERE company_id = ? "
            "AND source = 'bank_feed' GROUP BY on_date ORDER BY on_date", (cid,)):
        closes[_week(date.fromisoformat(r["on_date"]))] = (r["on_date"], r["ore"])
    floor_ore = db.to_ore(floor_kr)
    out = []
    for wk, (on, ore) in sorted(closes.items(), reverse=True):
        if ore >= floor_ore:
            continue
        monday = _monday(wk)
        first = conn.execute(
            "SELECT min(r.made_on) FROM forecast_weeks w JOIN forecast_runs r ON r.id = w.run_id "
            "WHERE w.company_id = ? AND w.week_start = ? AND w.committed_close_ore < ? "
            "AND r.made_on <= ?", (cid, monday.isoformat(), floor_ore, on)).fetchone()[0]
        out.append({"week": wk, "on": on, "balance": db.to_kr(ore), "floor": floor_kr,
                    "first_flagged": first,
                    # Seen only in its own week is no warning: 0, not less.
                    "weeks_ahead": (max(0, (monday - date.fromisoformat(first)).days // 7)
                                    if first else None)})
    return out


def report(today: date | None = None) -> dict:
    """The last weeks, newest first, and every dip there has been."""
    today = today or date.today()
    cid = db.company_id()
    floor = _floor()
    with db.read() as conn:
        mins, dec, usd = minutes(conn, cid), decisions(conn, cid), cost(conn, cid)
        all_dips = dips(conn, cid, floor["value"])
        since = conn.execute("SELECT min(on_date) FROM bank_balances WHERE company_id = ? "
                             "AND source = 'bank_feed'", (cid,)).fetchone()[0]
    weeks = [{"week": wk, "from": _monday(wk).isoformat(),
              "minutes": mins.get(wk, 0), "decisions": dec.get(wk),
              "cost": usd.get(wk)} for wk in _weeks(today)]
    return {"weeks": weeks, "target_minutes": TARGET_MINUTES, "dips": all_dips,
            "floor": {"kr": floor["value"], "said": company.said(floor)},
            "bank_history_since": since}
