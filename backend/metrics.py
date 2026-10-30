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
- **The Monday letter** — when each brief was emailed (`reports`), the taps
  that brought someone into the app from it (`email_taps`), and how soon after
  the send the app was first open and for how many minutes that first day.
  No open pixel: it would be a guess (Apple Mail loads every image, Gmail
  through a proxy) and one the cookie rules want consent for anyway.

**Only with a yes.** Minutes and taps are recorded only for a user who has
said yes to being measured (`consents`); before they answer, and after a
no, nothing is. The server holds to it whatever the app sends.
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


LINKS = ("brief", "card", "saker")


# ------------------------------------------------------------- consent
def consent(user: str) -> bool | None:
    """Whether `user` lets us measure their use: yes, no, or not asked yet."""
    with db.read() as conn:
        row = conn.execute("SELECT measure FROM consents WHERE company_id = ? AND user_email = ?",
                           (db.company_id(), user)).fetchone()
    return None if row is None else bool(row["measure"])


def set_consent(user: str, measure: bool) -> None:
    with db.tx() as conn:
        conn.execute("INSERT INTO consents (company_id, user_email, measure, at) "
                     "VALUES (?, ?, ?, ?) ON CONFLICT (company_id, user_email) "
                     "DO UPDATE SET measure = excluded.measure, at = excluded.at",
                     (db.company_id(), user, int(measure), db.now()))


# ------------------------------------------------------------- recording
def ping(user: str, at: datetime | None = None) -> bool:
    """The app is open and in focus for `user` this minute. Kept only with
    their yes; says whether it was."""
    if consent(user) is not True:
        return False
    at = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with db.tx() as conn:
        conn.execute("INSERT OR IGNORE INTO activity (company_id, user_email, minute) "
                     "VALUES (?, ?, ?)", (db.company_id(), user, at.strftime("%Y-%m-%dT%H:%M")))
    return True


def tap(user: str, report_id: int, link: str, card_id: str | None = None,
        at: datetime | None = None) -> bool:
    """`user` came into the app from a link in the Monday email of brief
    `report_id`. Kept only with their yes, and only for a brief that exists;
    says whether it was."""
    if link not in LINKS or consent(user) is not True:
        return False
    at = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with db.tx() as conn:
        cid = db.company_id()
        if not conn.execute("SELECT 1 FROM reports WHERE id = ? AND company_id = ? "
                            "AND kind = 'weekly_brief'", (report_id, cid)).fetchone():
            return False
        conn.execute("INSERT INTO email_taps (company_id, user_email, report_id, link, card_id, at) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (cid, user, report_id, link, card_id if link == "card" else None,
                      at.isoformat(timespec="seconds")))
    return True


# ------------------------------------------------------------- measuring
def minutes(conn, cid: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for (minute,) in conn.execute("SELECT minute FROM activity WHERE company_id = ?", (cid,)):
        wk = _week(datetime.fromisoformat(minute).date())
        out[wk] = out.get(wk, 0) + 1
    return out


def letters(conn, cid: int) -> dict[str, dict]:
    """Each Monday letter that was emailed, by the week it went out: when, the
    taps from it, and how soon and how long the app was open after."""
    minutes_kept = sorted(m for (m,) in conn.execute(
        "SELECT minute FROM activity WHERE company_id = ?", (cid,)))
    out: dict[str, dict] = {}
    for r in conn.execute("SELECT id, period, facts FROM reports WHERE company_id = ? "
                          "AND kind = 'weekly_brief' ORDER BY id", (cid,)):
        sent = (db.loads(r["facts"], {}) or {}).get("sent")
        if not sent or not sent.get("at"):
            continue
        at = _when(sent["at"]).astimezone(timezone.utc)
        taps = {link: 0 for link in LINKS}
        for t in conn.execute("SELECT link, count(*) AS n FROM email_taps WHERE company_id = ? "
                              "AND report_id = ? GROUP BY link", (cid, r["id"])):
            taps[t["link"]] = t["n"]
        start, day_end = at.strftime("%Y-%m-%dT%H:%M"), (at + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        after = [m for m in minutes_kept if start <= m < day_end]
        first = after[0] if after else None
        out[_week(at.date())] = {
            "report_id": r["id"], "period": r["period"], "sent_at": sent["at"],
            "taps": taps, "tapped": sum(taps.values()),
            # From the minute it went out to the first minute the app was open.
            "first_visit_minutes": (int((datetime.fromisoformat(first).replace(tzinfo=timezone.utc)
                                         - at.replace(second=0, microsecond=0)).total_seconds()
                                        // 60) if first else None),
            "minutes_first_day": len(after)}
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
        sent = letters(conn, cid)
        all_dips = dips(conn, cid, floor["value"])
        since = conn.execute("SELECT min(on_date) FROM bank_balances WHERE company_id = ? "
                             "AND source = 'bank_feed'", (cid,)).fetchone()[0]
    weeks = [{"week": wk, "from": _monday(wk).isoformat(),
              "minutes": mins.get(wk, 0), "letter": sent.get(wk), "decisions": dec.get(wk),
              "cost": usd.get(wk)} for wk in _weeks(today)]
    return {"weeks": weeks, "target_minutes": TARGET_MINUTES, "dips": all_dips,
            "floor": {"kr": floor["value"], "said": company.said(floor)},
            "bank_history_since": since}
