"""The whole forecast, frozen: every week, flow, assumption and warning, and
the briefing the agent reads, for each demo company on fixed days.

The guard for refactoring `cashflow.py` (cards 68-72): a change that moves
any krone, sentence or key fails here, with the paths that moved. A change
meant to move them is accepted by writing the snapshots again, in a commit
of its own that says why:

    CFO_SNAPSHOT_UPDATE=1 ./.venv/bin/python -m tests.run

Each company runs in a process of its own, as in test_demo.py, because
config reads CFO_DEMO at import. The calendar is frozen before the backend
is imported, so the books and every `date.today()` agree on the day, and
the network is refused, so nothing reaches Tripletex or Brønnøysund.

The days are picked for what they exercise:
- 2026-01-14: early in the year, last year's months in the run rates;
- 2026-11-12: an ordinary mid-month day;
- 2026-11-26: after the AGA term was paid on the 15th and the payroll was
  posted, the window where `aga_booked` reads the net movement (card 68).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from demo.companies import SPECS

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = Path(__file__).resolve().parent / "snapshots" / "cashflow"
DAYS = ("2026-01-14", "2026-11-12", "2026-11-26")
UPDATE = os.environ.get("CFO_SNAPSHOT_UPDATE") == "1"

PROBE = r"""
import datetime as _dt, json, os, socket, sys

FIXED = _dt.date.fromisoformat(os.environ["SNAP_TODAY"])

class _Date(_dt.date):
    @classmethod
    def today(cls):
        return FIXED

class _DateTime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.combine(FIXED, _dt.time(12, 0), tzinfo=tz)

    @classmethod
    def today(cls):
        return cls.now()

_dt.date, _dt.datetime = _Date, _DateTime

def refuse(*a, **k):
    raise OSError("network refused in snapshot test")
socket.create_connection = refuse
socket.socket.connect = lambda self, *a: refuse()

sys.path.insert(0, "backend")
import asyncio, cashflow

async def main():
    data = await cashflow.build(FIXED)
    return {"build": data, "briefing": cashflow.briefing(data)}

print("RESULT " + json.dumps(asyncio.run(main()), ensure_ascii=False,
                             sort_keys=True, default=str))
"""


def _run(slug: str, day: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / slug
        state.mkdir()
        (state / "company.md").write_text(SPECS[slug].company_md, encoding="utf-8")
        env = {**os.environ, "CFO_DEMO": slug, "CFO_STATE": str(state),
               "CFO_DB": str(Path(tmp) / "demo.db"), "CFO_AUTH": "off",
               "CFO_SCHEDULER": "off", "SNAP_TODAY": day}
        r = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=300)
        line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT ")), None)
        assert line, f"{slug} {day}: {r.stderr[-2000:]}"
        # Through JSON and back, so the comparison is on what was saved:
        # tuples become lists either way.
        return json.loads(line[7:])


def _diff(old, new, path: str = "", out: list | None = None) -> list[str]:
    """The paths where two snapshots part, at most 15 of them."""
    out = [] if out is None else out
    if len(out) >= 15:
        return out
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            if k not in old or k not in new:
                out.append(f"{path}.{k}: {'added' if k in new else 'removed'}")
            else:
                _diff(old[k], new[k], f"{path}.{k}", out)
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            out.append(f"{path}: {len(old)} items -> {len(new)}")
        for i, (a, b) in enumerate(zip(old, new)):
            _diff(a, b, f"{path}[{i}]", out)
    elif isinstance(old, str) and isinstance(new, str) and old != new:
        # Long text such as the briefing: show where it parts, not its start.
        at = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b),
                  min(len(old), len(new)))
        lo = max(0, at - 40)
        out.append(f"{path} @{at}: {old[lo:at + 60]!r} -> {new[lo:at + 60]!r}")
    elif old != new:
        out.append(f"{path}: {str(old)[:120]!r} -> {str(new)[:120]!r}")
    return out


def test_the_forecast_matches_its_snapshots():
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    failures = []
    for slug in sorted(SPECS):
        for day in DAYS:
            got = _run(slug, day)
            file = SNAPSHOTS / f"{slug}-{day}.json"
            if UPDATE or not file.exists():
                file.write_text(json.dumps(got, ensure_ascii=False, indent=1,
                                           sort_keys=True) + "\n", encoding="utf-8")
                continue
            moved = _diff(json.loads(file.read_text(encoding="utf-8")), got)
            if moved:
                failures.append(f"{file.name}:\n    " + "\n    ".join(moved))
    assert not failures, ("The forecast moved. If that is meant, rerun with "
                          "CFO_SNAPSHOT_UPDATE=1 and commit the snapshots on "
                          "their own.\n  " + "\n  ".join(failures))


def test_the_snapshots_do_not_depend_on_the_hash_seed():
    # Set iteration order varies with PYTHONHASHSEED. A snapshot that only
    # holds under one seed would fail at random and be updated until nobody
    # trusts it, so two seeds must give the same forecast.
    def once(seed: str) -> dict:
        os.environ["PYTHONHASHSEED"] = seed
        try:
            return _run("lindeskar", DAYS[1])
        finally:
            os.environ.pop("PYTHONHASHSEED", None)
    a, b = once("1"), once("2")
    assert not _diff(a, b), _diff(a, b)
