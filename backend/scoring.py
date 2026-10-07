"""How close the forecast came: each Monday's, 1, 2 and 4 weeks later.

The playbook's trust proof for the first deliverable is a record, not a
promise: "the 4-week-ahead forecast within about ±10 % for 8 weeks in a row".
This keeps that record.

**Which forecast.** The first saved forecast of each calendar week — Monday's
whenever the app is used on a Monday. The others that week stay saved and are
not scored.

**Against what.** The expected line — the forecast — at the close of the week
1, 2 and 4 weeks on, against the bank's own balance (`bank_feed`) on the last
day of that week the feed covers, Friday to Sunday. Never the booked balance:
it runs days behind the bank, and scoring against it would blame the forecast
for the bookkeeping backlog. A week with no bank figure stays unscored rather
than being scored against a guess. The committed line is kept beside it, as
the floor it is, and not scored.

**Why it missed.** Each saved forecast carries the open invoices and bills it
expected and when (`forecast_runs.items`). The forecast saved in the week after
the target shows what was still open then. An invoice expected in by the
target and still open was paid later than forecast; one paid before it was
expected, earlier. The same for our own bills, with the sign turned. What that
does not explain is left as the remainder — money that was never in the
forecast, such as a bill not yet in the ledger.

Run from the forecast build, after the day's forecast is saved. It only reads
the database, scores what has come due, and never scores anything twice.
"""
import logging
from datetime import date, timedelta

import db

log = logging.getLogger("cfo.scoring")

HORIZONS = (1, 2, 4)
WITHIN_PCT = 10.0            # the playbook's graduation band
STREAK_HORIZON = 4
RECENT = 8                   # weeks the average error is taken over
ACTUAL_WINDOW_DAYS = 3       # Friday to Sunday: the feed's last day of the week
TOP_NAMES = 5


# ------------------------------------------------------------------ choosing
def _weekly(conn, cid: int) -> list:
    """The first saved forecast of each ISO week, oldest first."""
    rows = conn.execute(
        "SELECT * FROM forecast_runs WHERE company_id = ? AND purpose = 'weekly' "
        "ORDER BY made_on, id", (cid,)).fetchall()
    seen, out = set(), []
    for r in rows:
        week = date.fromisoformat(r["made_on"]).isocalendar()[:2]
        if week not in seen:
            seen.add(week)
            out.append(r)
    return out


def _actual(conn, cid: int, target: date) -> tuple[int, str] | None:
    """The bank's balance at the close of the target week, in øre, and the
    day it is true of: the latest feed day from Friday to Sunday."""
    lo = (target - timedelta(days=ACTUAL_WINDOW_DAYS - 1)).isoformat()
    row = conn.execute(
        "SELECT on_date, sum(balance_ore) AS ore FROM bank_balances "
        "WHERE company_id = ? AND source = 'bank_feed' AND on_date BETWEEN ? AND ? "
        "GROUP BY on_date ORDER BY on_date DESC LIMIT 1",
        (cid, lo, target.isoformat())).fetchone()
    return (row["ore"], row["on_date"]) if row else None


def _later(conn, cid: int, target: date):
    """The forecast saved in the week after the target: the open books then."""
    return conn.execute(
        "SELECT * FROM forecast_runs WHERE company_id = ? AND purpose = 'weekly' "
        "AND made_on > ? AND made_on <= ? AND items IS NOT NULL "
        "ORDER BY made_on, id LIMIT 1",
        (cid, target.isoformat(), (target + timedelta(days=7)).isoformat())
    ).fetchone()


# ------------------------------------------------------------- attributing
def _key(item: dict):
    """An invoice is its number; a bill without one is who and how much."""
    return item["number"] if item.get("number") is not None \
        else (item.get("name"), item.get("amount"))


def _slips(before: list, after: list, target: date) -> dict[str, float]:
    """Per counterparty, how much was settled later than expected by the
    target (positive) or earlier (negative), in kroner."""
    still = {}
    for item in after:
        still[_key(item)] = still.get(_key(item), 0.0) + item["amount"]
    by_name: dict[str, float] = {}
    for item in before:
        expected = sum(a for d, a in item["parts"] if d <= target.isoformat())
        settled = item["amount"] - still.get(_key(item), 0.0)
        slip = expected - settled
        if abs(slip) >= 1:
            by_name[item["name"]] = by_name.get(item["name"], 0.0) + slip
    return by_name


def attribute(miss_kr: float, items: dict | None, later_items: dict | None,
              target: date) -> dict:
    """Put a miss (forecast − actual, kroner) down to who paid when.

    A customer paying later leaves the bank lower than forecast: it adds to
    the miss. Our own bill paid later leaves it higher: it takes away. The
    rest is what the forecast never knew about.
    """
    if not items or not later_items:
        return {"available": False,
                "why": "ingen lagret prognose uka etter å sammenligne med"}
    ar = _slips(items.get("ar") or [], later_items.get("ar") or [], target)
    ap = _slips(items.get("ap") or [], later_items.get("ap") or [], target)
    receipts_late = sum(v for v in ar.values() if v > 0)
    receipts_early = -sum(v for v in ar.values() if v < 0)
    payments_late = sum(v for v in ap.values() if v > 0)
    payments_early = -sum(v for v in ap.values() if v < 0)
    explained = sum(ar.values()) - sum(ap.values())
    names = ([{"name": n, "kind": "kunde", "amount": round(v, 2)} for n, v in ar.items()]
             + [{"name": n, "kind": "leverandør", "amount": round(-v, 2)}
                for n, v in ap.items()])
    names.sort(key=lambda x: -abs(x["amount"]))
    return {"available": True,
            "receipts_late": round(receipts_late, 2),
            "receipts_early": round(receipts_early, 2),
            "payments_late": round(payments_late, 2),
            "payments_early": round(payments_early, 2),
            "explained": round(explained, 2),
            "not_in_forecast": round(miss_kr - explained, 2),
            "names": names[:TOP_NAMES]}


# ------------------------------------------------------------------ scoring
def score(today: date | None = None) -> int:
    """Score every weekly forecast whose horizon has come due. Returns how
    many scores were written."""
    today = today or date.today()
    cid = db.company_id()
    written = 0
    with db.tx() as conn:
        done = {(r["run_id"], r["horizon_weeks"]) for r in conn.execute(
            "SELECT run_id, horizon_weeks FROM forecast_scores WHERE company_id = ?",
            (cid,))}
        for run in _weekly(conn, cid):
            weeks = {w["week_no"]: w for w in conn.execute(
                "SELECT * FROM forecast_weeks WHERE run_id = ?", (run["id"],))}
            for h in HORIZONS:
                if (run["id"], h) in done or (h - 1) not in weeks:
                    continue
                week = weeks[h - 1]
                target = date.fromisoformat(week["week_start"]) + timedelta(days=6)
                if target >= today:
                    continue                       # not over yet
                actual = _actual(conn, cid, target)
                if actual is None:
                    continue                       # no bank figure: unscored
                actual_ore, actual_on = actual
                forecast_ore = week["expected_close_ore"]
                miss_kr = db.to_kr(forecast_ore - actual_ore)
                error = (round((forecast_ore - actual_ore) / abs(actual_ore) * 100, 2)
                         if actual_ore else None)
                later = _later(conn, cid, target)
                why = attribute(miss_kr, db.loads(run["items"]),
                                db.loads(later["items"]) if later else None, target)
                conn.execute(
                    "INSERT INTO forecast_scores (company_id, run_id, horizon_weeks, "
                    "target_date, forecast_ore, committed_ore, actual_ore, actual_on, "
                    "error_pct, attribution, scored_on) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (cid, run["id"], h, target.isoformat(), forecast_ore,
                     week["committed_close_ore"], actual_ore, actual_on, error,
                     db.dumps(why), today.isoformat()))
                written += 1
    if written:
        log.info("Prognoser scoret: %d nye", written)
    return written


# ------------------------------------------------------------------ reading
def track_record(today: date | None = None) -> dict:
    """The record: every score, the latest per horizon, the average error over
    the last weeks, and how many weeks running the 4-week forecast has held."""
    today = today or date.today()
    cid = db.company_id()
    with db.read() as conn:
        rows = conn.execute(
            "SELECT s.*, r.made_on FROM forecast_scores s "
            "JOIN forecast_runs r ON r.id = s.run_id WHERE s.company_id = ? "
            "ORDER BY s.target_date DESC, s.horizon_weeks", (cid,)).fetchall()
        kept = len(_weekly(conn, cid))
    scores = [{"made_on": r["made_on"], "horizon_weeks": r["horizon_weeks"],
               "target_date": r["target_date"], "actual_on": r["actual_on"],
               "forecast": db.to_kr(r["forecast_ore"]),
               "committed": db.to_kr(r["committed_ore"]),
               "actual": db.to_kr(r["actual_ore"]), "error_pct": r["error_pct"],
               "attribution": db.loads(r["attribution"], {})} for r in rows]
    by_h = {h: [s for s in scores if s["horizon_weeks"] == h] for h in HORIZONS}
    mean = {h: (round(sum(abs(s["error_pct"]) for s in v[:RECENT]) / len(v[:RECENT]), 2)
                if v else None) for h, v in by_h.items()}
    return {"weekly_forecasts_kept": kept,
            "scores": scores,
            "latest": {h: (v[0] if v else None) for h, v in by_h.items()},
            "mean_abs_error_pct": mean,
            "streak": _streak(by_h[STREAK_HORIZON]),
            "within_pct": WITHIN_PCT,
            "next": _next_due(kept, scores, today)}


def _streak(four_week: list) -> int:
    """Weeks running, newest back, the 4-week forecast held within the band.
    A miss ends it, and so does a week with no score: "in a row" means in a row."""
    n, prev = 0, None
    for s in four_week:                                   # newest first
        target = date.fromisoformat(s["target_date"])
        if prev is not None and (prev - target).days != 7:
            break
        if s["error_pct"] is None or abs(s["error_pct"]) > WITHIN_PCT:
            break
        n, prev = n + 1, target
    return n


def _next_due(kept: int, scores: list, today: date) -> str | None:
    """When the first score can be expected, while there is none."""
    if scores:
        return None
    # The first weekly forecast is this week's if one is kept, else next
    # week's; its week 0 closes on the Sunday, and it is scored the day after.
    monday = today - timedelta(days=today.weekday())
    first = monday if kept else monday + timedelta(days=7)
    return (first + timedelta(days=7)).isoformat()


def _kr(v) -> str:
    return f"{round(v):,}".replace(",", " ")


def briefing(today: date | None = None) -> str:
    """The record, for the system prompt. Said even when empty, so the agent
    never claims an accuracy nobody has measured."""
    try:
        rec = track_record(today)
    except Exception:  # noqa: BLE001 — a missing record must not break a turn
        log.exception("Treffsikkerheten kunne ikke leses")
        return ""
    out = ["## Hvor godt prognosen har truffet\n"]
    if not rec["scores"]:
        out.append(
            f"No forecast has been scored yet ({rec['weekly_forecasts_kept']} weekly "
            f"forecast(s) kept so far; the first score is due around "
            f"{rec['next']}). If asked how accurate the forecast is, say exactly "
            f"that — there is no record yet — and never state an accuracy.")
        return "\n".join(out)
    out.append("Each Monday's forecast (expected line) against the bank's own "
               "balance at the close of the week, 1, 2 and 4 weeks later. "
               "Measured here, no model involved.\n")
    for h in HORIZONS:
        s = rec["latest"][h]
        if not s:
            continue
        line = (f"- **{h} uke{'r' if h > 1 else ''} fram**: prognosen fra "
                f"{s['made_on']} sa {_kr(s['forecast'])} kr for uka som sluttet "
                f"{s['target_date']}; banken viste {_kr(s['actual'])} kr — "
                f"{s['error_pct']:+.1f} %.")
        a = s["attribution"]
        if a.get("available") and a.get("names"):
            who = ", ".join(f"{n['name']} ({_kr(n['amount'])} kr)" for n in a["names"][:3])
            line += (f" Forklart: {who}; {_kr(a['not_in_forecast'])} kr var ikke "
                     f"med i prognosen.")
        if rec["mean_abs_error_pct"][h] is not None:
            line += f" Snitt siste uker: ±{rec['mean_abs_error_pct'][h]:.1f} %."
        out.append(line)
    out.append(f"\nFire uker fram har prognosen holdt seg innenfor ±{WITHIN_PCT:.0f} % "
               f"{rec['streak']} uke(r) på rad; målet er 8. Quote these figures as "
               f"they stand when asked how far the forecast can be trusted.")
    return "\n".join(out)
