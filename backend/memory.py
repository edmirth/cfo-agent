"""The controller's memory: what was true, what was flagged, what was promised.

A CFO's value is longitudinal. Without this the agent meets the company fresh
every conversation and can never say "receivables are up 340k since I raised
this on the 12th, and nothing has been collected" — the sentence that separates
a controller from a report generator.

Four things are kept, because they are the four a controller is held to:

- **snapshots** — where the figures stood on a given day, written from the
  dashboard build, so trend memory costs nothing and involves no model.
- **findings** — what was flagged, when, and whether it was ever closed. An
  open finding that keeps re-appearing is itself the finding.
- **forecasts** — what was predicted, so it can be scored against the outcome
  later. A CFO who is never wrong on the record has never committed to a number.
- **decisions** — what the CEO said to do, so the next conversation does not
  re-litigate it.

Stored in the database (`db.py`): `findings`, `predictions`, `decisions` and
`kpi_snapshots`, every row with its company. Nothing is deleted to make room —
the caps below limit what the briefing shows, not what is kept. Snapshots are
deterministic; the other three are written by the agent through the tools in
`agent/tools.py`.
"""
import logging
from datetime import date, timedelta

import db
import definitions

log = logging.getLogger("cfo.memory")

# What the briefing block shows. Caps exist because this text ships in every
# system prompt — memory that crowds out the analysis is not an improvement.
SHOW_FINDINGS = 20
SHOW_FORECASTS = 10
SHOW_DECISIONS = 8


class NotFound(KeyError):
    """No record with that id. Distinct from a malformed call."""


def _today() -> str:
    return date.today().isoformat()


# ------------------------------------------------------------------ rows
def _finding(r) -> dict:
    rec = {"id": r["ref"], "opened": r["opened_on"], "topic": r["topic"],
           "severity": r["severity"], "statement": r["statement"],
           "metric": r["metric"], "value": r["value"], "status": r["status"]}
    if r["closed_on"] is not None or r["status"] != "open":
        rec.update(closed=r["closed_on"], outcome=r["outcome"])
    return rec


def _prediction(r) -> dict:
    rec = {"id": r["ref"], "made": r["made_on"], "period": r["period"],
           "metric": r["metric"], "expected": r["expected"], "low": r["low"],
           "high": r["high"], "basis": r["basis"], "actual": r["actual"]}
    if r["scored_on"] is not None:
        rec.update(scored=r["scored_on"], note=r["note"])
        if r["error_pct"] is not None:
            rec["error_pct"] = r["error_pct"]
    return rec


def _decision(r) -> dict:
    return {"id": r["ref"], "date": r["decided_on"], "decision": r["decision"],
            "context": r["context"]}


def _load() -> dict:
    """Everything remembered, in the shape the briefing reads, oldest first."""
    cid = db.company_id()
    with db.read() as conn:
        snaps: dict[str, dict] = {}
        for r in conn.execute(
                "SELECT on_date, kpi, value, definitions_hash FROM kpi_snapshots "
                "WHERE company_id = ? ORDER BY on_date", (cid,)):
            s = snaps.setdefault(r["on_date"], {"date": r["on_date"], "kpis": {}})
            s["kpis"][r["kpi"]] = r["value"]
            if r["definitions_hash"]:
                s["definitions_hash"] = r["definitions_hash"]
        q = lambda table: conn.execute(  # noqa: E731
            f"SELECT * FROM {table} WHERE company_id = ? ORDER BY id", (cid,))
        findings = [_finding(r) for r in q("findings")]
        forecasts = [_prediction(r) for r in q("predictions")]
        decisions = [_decision(r) for r in q("decisions")]
    snapshots = list(snaps.values())
    return {"since": snapshots[0]["date"] if snapshots else None,
            "snapshots": snapshots, "findings": findings,
            "forecasts": forecasts, "decisions": decisions}


# ---------------------------------------------------------------- snapshots

def snapshot(kpis: dict, on: str | None = None) -> None:
    """Record where the figures stood. Same-day calls overwrite, so the
    dashboard's ten-minute refresh does not write a hundred rows a day."""
    on = on or _today()
    clean = {k: v for k, v in (kpis or {}).items() if isinstance(v, (int, float))}
    if not clean:
        return
    # Stamped with the definitions in force, so a trend across a change of
    # definition can be spotted instead of quietly compared.
    try:
        mark = definitions.stamp().get("definitions_hash")
    except Exception:  # noqa: BLE001 — a snapshot is better than none
        mark = None
    cid = db.company_id()
    with db.tx() as conn:
        conn.execute("DELETE FROM kpi_snapshots WHERE company_id = ? AND on_date = ?",
                     (cid, on))
        conn.executemany(
            "INSERT INTO kpi_snapshots (company_id, on_date, kpi, value, "
            "definitions_hash) VALUES (?, ?, ?, ?, ?)",
            [(cid, on, k, float(v), mark) for k, v in clean.items()])


# ----------------------------------------------------------------- writes

def add_finding(topic: str, severity: str, statement: str,
                metric: str | None = None, value: float | None = None) -> dict:
    """Flag something. Returns the stored record, id included."""
    with db.tx() as conn:
        ref = db.next_ref(conn, "memory", "F")
        conn.execute(
            "INSERT INTO findings (company_id, ref, opened_on, topic, severity, "
            "statement, metric, value, job_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (db.company_id(), ref, _today(), topic, severity, statement,
             metric, value, db.job_run.get()))
    log.info("Finding %s opened: %s", ref, topic)
    return {"id": ref, "opened": _today(), "topic": topic, "severity": severity,
            "statement": statement, "metric": metric, "value": value,
            "status": "open"}


def resolve_finding(finding_id: str, outcome: str, status: str = "resolved") -> dict:
    with db.tx() as conn:
        row = conn.execute(
            "UPDATE findings SET status = ?, closed_on = ?, outcome = ? "
            "WHERE company_id = ? AND ref = ? RETURNING *",
            (status, _today(), outcome, db.company_id(),
             finding_id.strip().upper())).fetchone()
    if row is None:
        raise NotFound(f"No finding {finding_id}")
    return _finding(row)


def open_findings() -> list[dict]:
    """Everything flagged and not yet closed, oldest first."""
    with db.read() as conn:
        return [_finding(r) for r in conn.execute(
            "SELECT * FROM findings WHERE company_id = ? AND status = 'open' "
            "ORDER BY id", (db.company_id(),))]


def add_forecast(period: str, metric: str, expected: float,
                 basis: str, low: float | None = None,
                 high: float | None = None) -> dict:
    with db.tx() as conn:
        ref = db.next_ref(conn, "memory", "P")
        conn.execute(
            "INSERT INTO predictions (company_id, ref, made_on, period, metric, "
            "expected, low, high, basis, job_run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (db.company_id(), ref, _today(), period, metric, expected, low,
             high, basis, db.job_run.get()))
    log.info("Forecast %s recorded: %s %s", ref, metric, period)
    return {"id": ref, "made": _today(), "period": period, "metric": metric,
            "expected": expected, "low": low, "high": high, "basis": basis,
            "actual": None}


def score_forecast(forecast_id: str, actual: float, note: str = "") -> dict:
    cid, ref = db.company_id(), forecast_id.strip().upper()
    with db.tx() as conn:
        row = conn.execute("SELECT expected FROM predictions "
                           "WHERE company_id = ? AND ref = ?", (cid, ref)).fetchone()
        if row is None:
            raise NotFound(f"No forecast {forecast_id}")
        exp = row["expected"]
        error = round((actual - exp) / abs(exp) * 100, 1) if exp else None
        row = conn.execute(
            "UPDATE predictions SET actual = ?, scored_on = ?, note = ?, "
            "error_pct = ? WHERE company_id = ? AND ref = ? RETURNING *",
            (actual, _today(), note, error, cid, ref)).fetchone()
    return _prediction(row)


def add_decision(decision: str, context: str = "",
                 card: str | None = None) -> dict:
    """Record what the CEO chose. `card` is the card's ref when it came from
    one, so the decision can be traced back to what it answered."""
    cid = db.company_id()
    with db.tx() as conn:
        ref = db.next_ref(conn, "memory", "D")
        card_id = None
        if card:
            hit = conn.execute("SELECT id FROM cards WHERE company_id = ? AND ref = ?",
                               (cid, card.upper())).fetchone()
            card_id = hit["id"] if hit else None
        conn.execute(
            "INSERT INTO decisions (company_id, ref, decided_on, decision, "
            "context, card_id) VALUES (?, ?, ?, ?, ?, ?)",
            (cid, ref, _today(), decision, context, card_id))
    log.info("Decision recorded: %s", decision[:60])
    return {"id": ref, "date": _today(), "decision": decision, "context": context}


# ---------------------------------------------------------------- briefing

# Cumulative-since-1-January figures. A change across a window is that
# window's contribution, not a movement in a level — the agent has to be told
# which is which or it will read a rising YTD revenue as growth.
CUMULATIVE = {"omsetning", "driftsresultat"}

TRENDED = [
    ("omsetning", "Omsetning hittil i år", "kr"),
    ("driftsresultat", "Driftsresultat hittil i år", "kr"),
    ("driftsmargin_pct", "Driftsmargin", "%"),
    ("lonnsandel_pct", "Lønnsandel", "%"),
    ("bank", "Bank", "kr"),
    ("kundefordringer", "Kundefordringer", "kr"),
    ("likviditetsgrad", "Likviditetsgrad", "x"),
    ("egenkapitalandel_pct", "Egenkapitalandel", "%"),
]


def _fmt(value, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "kr":
        return f"{round(value):,}".replace(",", " ")
    if unit == "%":
        return f"{value:.1f} %"
    return f"{value:.2f}"


def _age(iso: str, today: date) -> int:
    try:
        return (today - date.fromisoformat(iso)).days
    except (ValueError, TypeError):
        return 0


def _at_or_before(snapshots: list[dict], cutoff: date) -> dict | None:
    """The most recent snapshot no later than `cutoff`."""
    older = [s for s in snapshots if s.get("date", "") <= cutoff.isoformat()]
    return older[-1] if older else None


def briefing(today: date | None = None) -> str:
    """The memory block injected into the system prompt.

    Returns "" when there is nothing worth carrying, so a first-run deployment
    is not handed an empty scaffold to write around.
    """
    today = today or date.today()
    try:
        data = _load()
    except Exception as exc:  # noqa: BLE001 — memory must never break a turn
        log.exception("Briefing failed: %s", exc)
        return ""

    parts: list[str] = []
    snaps = data["snapshots"]
    now = snaps[-1] if snaps else None

    if now:
        week = _at_or_before(snaps, today - timedelta(days=7))
        month = _at_or_before(snaps, today - timedelta(days=30))
        cols = [c for c in (week, month) if c and c["date"] != now["date"]]
        lines = [
            f"Your own record of where the figures stood, latest {now['date']}.",
            "",
            "| Metric | " + " | ".join(
                ["Latest"] + [f"{_age(c['date'], today)} d ago" for c in cols]) + " |",
            "|---" * (1 + 1 + len(cols)) + "|",
        ]
        for key, label_, unit in TRENDED:
            value = now["kpis"].get(key)
            if value is None:
                continue
            cells = [_fmt(value, unit)] + [_fmt(c["kpis"].get(key), unit) for c in cols]
            lines.append(f"| {label_} | " + " | ".join(cells) + " |")
        if len(lines) > 4:
            parts.append("\n".join(lines))
            if CUMULATIVE:
                parts.append(
                    "Omsetning and driftsresultat are cumulative since 1 January: "
                    "the difference between two columns is what that window "
                    "contributed, not a change in a level. The rest are levels.")

    openf = [f for f in data["findings"] if f.get("status") == "open"]
    if openf:
        rows = ["**Open findings** — raised by you, not yet closed. "
                "Check each one against today's figures: if it has resolved "
                "itself, close it; if it has worsened, lead with that.", ""]
        for f in openf[-SHOW_FINDINGS:]:
            days = _age(f.get("opened", ""), today)
            # Format the number alone: the metric name may itself hold a comma.
            figure = (f" ({f['metric']} {_fmt(f['value'], 'kr')})"
                      if f.get("metric") and isinstance(f.get("value"), (int, float))
                      else "")
            rows.append(f"- `{f['id']}` {f.get('opened')} — {days} d open, "
                        f"{f.get('severity', 'medium')} — {f.get('topic')}: "
                        f"{f.get('statement')}{figure}")
        parts.append("\n".join(rows))

    closed = [f for f in data["findings"] if f.get("status") != "open"][-5:]
    if closed:
        parts.append("**Recently closed** — do not raise these again as new.\n\n"
                     + "\n".join(f"- `{f['id']}` {f.get('topic')} — "
                                 f"{f.get('status')} {f.get('closed')}: "
                                 f"{f.get('outcome', '')}" for f in closed))

    unscored = [p for p in data["forecasts"] if p.get("actual") is None]
    if unscored:
        parts.append(
            "**Forecasts you owe an answer on** — when the period has closed, "
            "fetch the actual, score it with `score_forecast`, and say plainly "
            "how close you were before forecasting again.\n\n"
            + "\n".join(
                f"- `{p['id']}` made {p.get('made')} for {p.get('period')}: "
                f"{p.get('metric')} expected {_fmt(p.get('expected'), 'kr')}"
                + (f" (low {_fmt(p.get('low'), 'kr')}, high {_fmt(p.get('high'), 'kr')})"
                   if p.get("low") or p.get("high") else "")
                + f" — basis: {p.get('basis', '')}"
                for p in unscored[-SHOW_FORECASTS:]))

    scored = [p for p in data["forecasts"] if p.get("actual") is not None][-5:]
    if scored:
        parts.append("**Your forecasting record** — cite it when you forecast "
                     "again; it is how the CEO knows what your numbers are worth."
                     "\n\n" + "\n".join(
                         f"- `{p['id']}` {p.get('period')} {p.get('metric')}: "
                         f"expected {_fmt(p.get('expected'), 'kr')}, actual "
                         f"{_fmt(p.get('actual'), 'kr')}"
                         + (f" ({p['error_pct']:+.1f} %)" if p.get("error_pct") is not None else "")
                         for p in scored))

    if data["decisions"]:
        parts.append("**Decisions the CEO has made** — settled. Do not reopen "
                     "them unless the figures have moved against the decision, "
                     "and say so explicitly if they have.\n\n"
                     + "\n".join(f"- {d.get('date')}: {d.get('decision')}"
                                 + (f" ({d['context']})" if d.get("context") else "")
                                 for d in data["decisions"][-SHOW_DECISIONS:]))

    if not parts:
        return ""

    since = data.get("since")
    head = ("## What you already know\n\n"
            "This is your own record, carried between conversations"
            + (f"; you have been CFO here since {since}" if since else "")
            + ". Treat it as history, never as current: it tells you what you "
            "said and what the figures were, and any figure you intend to "
            "state today must be re-fetched from Tripletex first.\n")
    return head + "\n" + "\n\n".join(parts)
