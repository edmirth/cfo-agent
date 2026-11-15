#!/usr/bin/env python
"""The cash forecast on a real company's books, frozen for refactoring.

The demo snapshots (tests/test_cashflow_snapshots.py) guard the forecast on
made-up books. This guards it on the connected company's own: its books are
fetched once, read-only, and every later run replays them with the calendar
frozen on the day they were fetched, so a refactor that moves a krone shows.

    ./.venv/bin/python scripts/real_snapshot.py record   # fetch and freeze
    ./.venv/bin/python scripts/real_snapshot.py check    # replay and compare
    ./.venv/bin/python scripts/real_snapshot.py check --update   # accept

Everything is written under state/snapshots/cashflow/, which git ignores:
a real company's figures never reach the repository. The run reads a copy
of state/cfo.db, taken at record time and kept with the books, so the bank
categories and register flags are the company's own, and whatever the
forecast writes (the saved forecast, the scoring) is thrown away. Replay
refuses the network and fails on any question the recording cannot answer.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "state" / "snapshots" / "cashflow"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

PROBE = r"""
import datetime as _dt, json, os, socket, sys
MODE, DAY, BOOKS = os.environ["SNAP_MODE"], os.environ["SNAP_TODAY"], os.environ["SNAP_BOOKS"]
FIXED = _dt.date.fromisoformat(DAY)

if MODE == "replay":
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
        raise OSError("network refused in replay")
    socket.create_connection = refuse
    socket.socket.connect = lambda self, *a: refuse()
    socket.getaddrinfo = refuse

sys.path.insert(0, "backend")
import asyncio, mcp_client, cashflow

def key(tool, args):
    return tool + " " + json.dumps(args or {}, sort_keys=True, ensure_ascii=False)

books, real_call = {}, mcp_client.mcp.call
if MODE == "replay":
    books = json.load(open(BOOKS, encoding="utf-8"))

async def call(tool, arguments=None):
    k = key(tool, arguments)
    if MODE == "replay":
        if k not in books:
            raise RuntimeError(f"not in the recording: {k}")
        hit = books[k]
        if "error" in hit:
            raise RuntimeError(hit["error"])
        return hit["result"]
    try:
        result = await real_call(tool, arguments)
    except Exception as exc:
        books[k] = {"error": str(exc)}
        raise
    books[k] = {"result": result}
    return result

mcp_client.mcp.call = call

async def main():
    data = await cashflow.build(FIXED)
    return {"build": data, "briefing": cashflow.briefing(data)}

out = asyncio.run(main())
if MODE == "record":
    json.dump(books, open(BOOKS, "w", encoding="utf-8"), ensure_ascii=False, default=str)
print("RESULT " + json.dumps(out, ensure_ascii=False, sort_keys=True, default=str))
"""


def _run(mode: str, day: str, folder: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "cfo.db"
        shutil.copy(folder / "cfo.db", db)
        env = {**os.environ, "SNAP_MODE": mode, "SNAP_TODAY": day,
               "SNAP_BOOKS": str(folder / "books.json"), "CFO_DB": str(db),
               "CFO_SCHEDULER": "off"}
        env.pop("CFO_DEMO", None)
        r = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=900)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT ")), None)
    if not line:
        sys.exit(f"The forecast did not finish ({mode}):\n{r.stderr[-3000:]}")
    return json.loads(line[7:])


def _latest() -> Path:
    days = sorted(p for p in OUT.glob("*") if (p / "forecast.json").exists())
    if not days:
        sys.exit("No recording yet. Run: scripts/real_snapshot.py record")
    return days[-1]


def _save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")


def record() -> None:
    day = date.today().isoformat()
    folder = OUT / day
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "state" / "cfo.db", folder / "cfo.db")
    got = _run("record", day, folder)
    _save(folder / "forecast.json", got)
    # The recording has to reproduce what was fetched, or it guards nothing.
    again = _run("replay", day, folder)
    moved = _diff(got, again)
    if moved:
        sys.exit("Replay does not reproduce the recorded forecast:\n  " + "\n  ".join(moved))
    b = got["build"]
    print(f"Recorded {day}: {len(json.loads((folder / 'books.json').read_text()))} "
          f"Tripletex answers, {sum(len(w['items']) for w in b['weeks'])} forecast lines, "
          f"partial={b['partial']}, {len(b['warnings'])} warnings. Replay matches.")


def check(update: bool) -> None:
    folder = _latest()
    got = _run("replay", folder.name, folder)
    if update:
        _save(folder / "forecast.json", got)
        print(f"Accepted the forecast for {folder.name} as it now is.")
        return
    moved = _diff(json.loads((folder / "forecast.json").read_text(encoding="utf-8")), got)
    if moved:
        sys.exit(f"The forecast for {folder.name} moved:\n  " + "\n  ".join(moved))
    print(f"The forecast on the books of {folder.name} is unchanged.")


def _diff(old, new):
    from tests.test_cashflow_snapshots import _diff as diff
    return diff(old, new)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["record"]:
        record()
    elif args[:1] == ["check"]:
        check("--update" in args)
    else:
        sys.exit(__doc__)
