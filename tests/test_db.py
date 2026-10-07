"""The database: the one-time import, the company on every row, and writers
that cannot trip over each other."""
import json
import sqlite3
import tempfile
import threading
from datetime import date, timedelta
from pathlib import Path

import cards
import db
import memory
from tests import _tmp

MEMORY = {
    "since": "2026-09-20", "counter": 7,
    "snapshots": [{"date": "2026-09-20", "kpis": {"bank": 2625898.93, "omsetning": 1.5e7},
                   "definitions_hash": "abc123"},
                  {"date": "2026-09-21", "kpis": {"bank": 2700000.0}}],
    "findings": [
        {"id": "F001", "opened": "2026-09-20", "topic": "Lønnsandel", "severity": "high",
         "statement": "Over målet", "metric": "lonnsandel_pct", "value": 83.8,
         "status": "open"},
        {"id": "F004", "opened": "2026-09-21", "topic": "Skanska sen", "severity": "medium",
         "statement": "70 dager", "metric": None, "value": None, "status": "resolved",
         "closed": "2026-09-25", "outcome": "Betalt"}],
    "forecasts": [{"id": "P002", "made": "2026-09-20", "period": "2026-09",
                   "metric": "Omsetning", "expected": 1500000, "low": None, "high": None,
                   "basis": "snitt", "actual": 1650000, "scored": "2026-10-01",
                   "note": "", "error_pct": 10.0}],
    "decisions": [{"id": "D007", "date": "2026-09-22", "decision": "Vent med ansettelse",
                   "context": "Kort K003"}],
}
CARDS = {"counter": 18, "cards": [
    {"id": "K003", "key": "collections:Skanska", "source": "auto", "kind": "collections",
     "urgency": "high", "amount": 99449.0, "title": "Skanska 70 d", "body": "b",
     "evidence": [{"label": "Faktura 6483"}], "status": "done", "created": "2026-09-20",
     "closed": "2026-09-22", "options": [{"id": "ok", "label": "Send", "effect": "approve"}],
     "decided": {"at": "2026-09-22T09:00:00", "option": "ok", "label": "Send",
                 "effect": "approve", "note": ""},
     "draft": {"kind": "e-post", "to": "", "subject": "Påminnelse", "text": "Hei"}},
    {"id": "K018", "key": "cash:floor", "source": "auto", "kind": "cash",
     "urgency": "medium", "amount": None, "title": "Under gulvet", "body": "b",
     "evidence": [], "status": "open", "created": "2026-10-04", "refreshed": "2026-10-04",
     "options": []}]}


def _folder_with_json() -> Path:
    folder = Path(tempfile.mkdtemp())
    (folder / "memory.json").write_text(json.dumps(MEMORY), encoding="utf-8")
    (folder / "cards.json").write_text(json.dumps(CARDS), encoding="utf-8")
    db.reset_for_tests(folder / "cfo.db")
    return folder


# ------------------------------------------------------------------ import
def test_the_json_files_are_imported_once_with_every_id_and_date():
    folder = _folder_with_json()
    mem = memory._load()
    assert [f["id"] for f in mem["findings"]] == ["F001", "F004"]
    assert mem["findings"][1]["closed"] == "2026-09-25"
    assert mem["findings"][1]["outcome"] == "Betalt"
    assert mem["forecasts"][0]["error_pct"] == 10.0
    assert mem["decisions"][0]["context"] == "Kort K003"
    assert [s["date"] for s in mem["snapshots"]] == ["2026-09-20", "2026-09-21"]
    assert mem["snapshots"][0]["kpis"]["bank"] == 2625898.93
    assert mem["since"] == "2026-09-20"

    deck = cards._load()["cards"]
    assert [c["id"] for c in deck] == ["K003", "K018"]
    skanska = deck[0]
    assert skanska["amount"] == 99449.0 and skanska["closed"] == "2026-09-22"
    assert skanska["decided"]["label"] == "Send"
    assert skanska["draft"]["subject"] == "Påminnelse"
    assert skanska["evidence"] == [{"label": "Faktura 6483"}]

    # The files are kept, renamed, and the import never runs again.
    assert not (folder / "memory.json").exists()
    assert (folder / "memory.json.migrated").exists()
    assert (folder / "cards.json.migrated").exists()
    (folder / "cards.json").write_text(json.dumps(CARDS), encoding="utf-8")
    db._ready.clear()
    assert len(cards._load()["cards"]) == 2


def test_numbering_carries_on_after_the_highest_imported_id():
    _folder_with_json()
    # Memory's F, P and D share one series; the file's counter was 7.
    assert memory.add_finding("ny", "low", "s")["id"] == "F008"
    assert memory.add_decision("ja")["id"] == "D009"
    assert cards.add({"key": "x", "title": "Ny", "options": []})["id"] == "K019"


def test_an_imported_decision_from_a_card_can_be_traced_back_to_it():
    _folder_with_json()
    c = cards.add({"key": "agent:a", "title": "A", "source": "agent",
                   "options": [{"id": "ok", "label": "Ja", "effect": "approve"}]})
    cards.decide(c["id"], "ok")
    with db.read() as conn:
        row = conn.execute("SELECT c.ref FROM decisions d JOIN cards c "
                           "ON c.id = d.card_id ORDER BY d.id DESC LIMIT 1").fetchone()
    assert row["ref"] == c["id"]


# ----------------------------------------------------------------- company
def test_every_row_carries_the_company():
    _folder_with_json()
    memory.snapshot({"bank": 1.0}, on="2026-10-01")
    with db.read() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")]
        checked = 0
        for t in tables:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
            if "company_id" not in cols:
                assert t in ("companies", "schema_version", "kpi_definitions"), t
                continue
            n = conn.execute(f"SELECT count(*) FROM {t} WHERE company_id IS NULL "
                             f"OR company_id != ?", (db.company_id(),)).fetchone()[0]
            assert n == 0, t
            checked += 1
    assert checked >= 15


# ------------------------------------------------------------- concurrency
def test_concurrent_writers_lose_nothing_and_share_no_id():
    """Twenty threads, each with its own connection, all writing at once."""
    _tmp.db()
    errors = []

    def work(i):
        try:
            memory.add_finding(f"t{i}", "low", "s")
            cards.add({"key": f"k{i}", "title": f"Kort {i}", "options": []})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    findings = memory._load()["findings"]
    deck = cards._load()["cards"]
    assert len(findings) == 20 and len({f["id"] for f in findings}) == 20
    assert len(deck) == 20 and len({c["id"] for c in deck}) == 20


def test_two_racing_adds_of_the_same_key_store_one_card():
    _tmp.db()
    results = []
    barrier = threading.Barrier(8)

    def work():
        barrier.wait()
        results.append(cards.add({"key": "collections:Seby", "title": "Seby",
                                  "options": []}))

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r is not None for r in results) == 1
    assert len(cards._load()["cards"]) == 1


def test_the_database_itself_refuses_a_second_live_card_on_a_key():
    _tmp.db()
    cards.add({"key": "k", "title": "A", "options": []})
    try:
        with db.tx() as conn:
            cards.insert_row(conn, db.company_id(),
                             {"id": "K999", "key": "k", "title": "B", "status": "open"})
    except sqlite3.IntegrityError:
        return
    raise AssertionError("a second live card on the same key was stored")


# ------------------------------------------------------------- history
def _events(ref):
    with db.read() as conn:
        return [(r["event"], r["actor"], r["effect"]) for r in conn.execute(
            "SELECT e.* FROM card_events e JOIN cards c ON c.id = e.card_id "
            "WHERE c.ref = ? ORDER BY e.id", (ref,))]


def test_a_card_keeps_its_history_as_events():
    _tmp.db()
    c = cards.add({"key": "collections:Skanska", "title": "Skanska", "source": "auto",
                   "options": [{"id": "wait", "label": "Vent", "effect": "snooze", "days": 7},
                               {"id": "ok", "label": "Send", "effect": "approve"}]})
    cards.decide(c["id"], "wait")
    with db.tx() as conn:                       # a week passes
        conn.execute("UPDATE cards SET snooze_until = ? WHERE ref = ?",
                     ((date.today() - timedelta(days=1)).isoformat(), c["id"]))
    cards.deck()
    cards.decide(c["id"], "ok")
    cards.reconcile([], sources_ok=True)       # the customer paid
    assert _events(c["id"]) == [
        ("created", "system", None), ("decided", "ceo", "snooze"),
        ("woke", "system", None), ("decided", "ceo", "approve"),
        ("released", "system", None)]


def test_closed_cards_are_never_deleted():
    _tmp.db()
    for i in range(210):
        c = cards.add({"key": f"k{i}", "title": f"{i}",
                       "options": [{"id": "no", "label": "Nei", "effect": "dismiss"}]})
        cards.decide(c["id"], "no")
    assert len(cards._load()["cards"]) == 210
    assert len(cards.deck()["recent"]) == 8


def test_money_is_stored_in_whole_ore():
    _tmp.db()
    c = cards.add({"key": "k", "title": "A", "amount": 99449.456, "options": []})
    with db.read() as conn:
        ore = conn.execute("SELECT amount_ore FROM cards WHERE ref = ?",
                           (c["id"],)).fetchone()[0]
    assert ore == 9944946 and cards._load()["cards"][0]["amount"] == 99449.46
