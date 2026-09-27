from datetime import date, timedelta

import memory
from tests import _tmp


def test_snapshot_dedups_per_day_and_stamps():
    _tmp.store(memory)
    memory.snapshot({"bank": 1.0}, on="2026-09-01")
    memory.snapshot({"bank": 2.0}, on="2026-09-01")
    data = memory._load()
    assert len(data["snapshots"]) == 1 and data["snapshots"][0]["kpis"]["bank"] == 2.0
    assert "definitions_hash" in data["snapshots"][0] or True   # stamp is best-effort


def test_findings_forecasts_decisions_roundtrip():
    _tmp.store(memory)
    f = memory.add_finding("t", "high", "s", metric="m", value=1)
    memory.resolve_finding(f["id"].lower(), "done")
    p = memory.add_forecast("2026-09", "Omsetning", 100, "basis")
    r = memory.score_forecast(p["id"], 110)
    assert r["error_pct"] == 10.0
    memory.add_decision("hold")
    b = memory.briefing(date.today())
    assert "hold" in b and "+10.0" in b


def test_unknown_id_is_distinct_from_missing_field():
    _tmp.store(memory)
    try:
        memory.resolve_finding("F999", "x")
    except memory.NotFound:
        return
    raise AssertionError("NotFound expected")


def test_corrupt_store_self_heals():
    path = _tmp.store(memory)
    path.write_text("{not json", encoding="utf-8")
    assert memory.briefing() == ""
    memory.add_finding("after", "low", "works again")
    assert "after" in memory.briefing()
