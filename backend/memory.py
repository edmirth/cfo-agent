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

Stored as one JSON file, written atomically. Snapshots are deterministic; the
other three are written by the agent through the tools in `agent.py`.
"""
import json
import logging
import os
import tempfile
import threading
from datetime import date, timedelta
from pathlib import Path

import definitions
from config import ROOT

log = logging.getLogger("cfo.memory")

STORE = ROOT / "state" / "memory.json"

# A year of daily snapshots is enough to speak to any comparison a CEO asks
# for; beyond that the ledger itself is the better source.
MAX_SNAPSHOTS = 400
MAX_RESOLVED = 100

# What the briefing block shows. Caps exist because this text ships in every
# system prompt — memory that crowds out the analysis is not an improvement.
SHOW_FINDINGS = 20
SHOW_FORECASTS = 10
SHOW_DECISIONS = 8

_lock = threading.Lock()


class NotFound(KeyError):
    """No record with that id. Distinct from a malformed call."""

EMPTY: dict = {"since": None, "counter": 0, "snapshots": [],
               "findings": [], "forecasts": [], "decisions": []}


def _load() -> dict:
    if not STORE.exists():
        return dict(EMPTY, snapshots=[], findings=[], forecasts=[], decisions=[])
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # Memory is an enhancement, never a reason to fail a question. A
        # corrupt store is set aside so the next write starts clean.
        log.error("Memory unreadable (%s); starting a fresh store", exc)
        try:
            STORE.rename(STORE.with_suffix(".corrupt.json"))
        except OSError:
            pass
        return dict(EMPTY, snapshots=[], findings=[], forecasts=[], decisions=[])
    for key in ("snapshots", "findings", "forecasts", "decisions"):
        data.setdefault(key, [])
    data.setdefault("counter", 0)
    data.setdefault("since", None)
    return data


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename: a crash mid-write leaves the old file intact rather
    # than a truncated one.
    fd, tmp = tempfile.mkstemp(dir=STORE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _next_id(data: dict, prefix: str) -> str:
    data["counter"] += 1
    return f"{prefix}{data['counter']:03d}"


def _today() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------- snapshots

def snapshot(kpis: dict, on: str | None = None) -> None:
    """Record where the figures stood. Same-day calls overwrite, so the
    dashboard's ten-minute refresh does not write a hundred rows a day."""
    on = on or _today()
    clean = {k: v for k, v in (kpis or {}).items() if isinstance(v, (int, float))}
    if not clean:
        return
    with _lock:
        data = _load()
        data["snapshots"] = [s for s in data["snapshots"] if s.get("date") != on]
        # Stamped with the definitions in force, so a trend across a change of
        # definition can be spotted instead of quietly compared.
        try:
            mark = definitions.stamp()
        except Exception:  # noqa: BLE001 — a snapshot is better than none
            mark = {}
        data["snapshots"].append({"date": on, "kpis": clean, **mark})
        data["snapshots"].sort(key=lambda s: s["date"])
        del data["snapshots"][:-MAX_SNAPSHOTS]
        if not data["since"]:
            data["since"] = on
        _save(data)


# ----------------------------------------------------------------- writes

def add_finding(topic: str, severity: str, statement: str,
                metric: str | None = None, value: float | None = None) -> dict:
    """Flag something. Returns the stored record, id included."""
    with _lock:
        data = _load()
        rec = {"id": _next_id(data, "F"), "opened": _today(), "topic": topic,
               "severity": severity, "statement": statement,
               "metric": metric, "value": value, "status": "open"}
        data["findings"].append(rec)
        _save(data)
    log.info("Finding %s opened: %s", rec["id"], topic)
    return rec


def resolve_finding(finding_id: str, outcome: str, status: str = "resolved") -> dict:
    with _lock:
        data = _load()
        for rec in data["findings"]:
            if rec["id"].upper() == finding_id.upper():
                rec.update(status=status, closed=_today(), outcome=outcome)
                closed = [f for f in data["findings"] if f["status"] != "open"]
                if len(closed) > MAX_RESOLVED:
                    drop = {id(f) for f in closed[: len(closed) - MAX_RESOLVED]}
                    data["findings"] = [f for f in data["findings"] if id(f) not in drop]
                _save(data)
                return rec
        raise NotFound(f"No finding {finding_id}")


def add_forecast(period: str, metric: str, expected: float,
                 basis: str, low: float | None = None,
                 high: float | None = None) -> dict:
    with _lock:
        data = _load()
        rec = {"id": _next_id(data, "P"), "made": _today(), "period": period,
               "metric": metric, "expected": expected, "low": low, "high": high,
               "basis": basis, "actual": None}
        data["forecasts"].append(rec)
        _save(data)
    log.info("Forecast %s recorded: %s %s", rec["id"], metric, period)
    return rec


def score_forecast(forecast_id: str, actual: float, note: str = "") -> dict:
    with _lock:
        data = _load()
        for rec in data["forecasts"]:
            if rec["id"].upper() == forecast_id.upper():
                rec.update(actual=actual, scored=_today(), note=note)
                exp = rec.get("expected")
                if exp:
                    rec["error_pct"] = round((actual - exp) / abs(exp) * 100, 1)
                _save(data)
                return rec
        raise NotFound(f"No forecast {forecast_id}")


def add_decision(decision: str, context: str = "") -> dict:
    with _lock:
        data = _load()
        rec = {"id": _next_id(data, "D"), "date": _today(),
               "decision": decision, "context": context}
        data["decisions"].append(rec)
        _save(data)
    log.info("Decision recorded: %s", decision[:60])
    return rec


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
        with _lock:
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
