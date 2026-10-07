"""The one door to the database.

What only this product knows — what the CFO flagged, forecast and prepared,
and what the CEO decided — lives here instead of in JSON files under `state/`.
Tripletex stays the truth about the money and is never copied in. The design,
the tables and the rules every table follows are in `docs/database.md`.

This is the only module that opens a connection. Swapping SQLite for Postgres,
adding the tenant filter or the audit log each changes this file, not the
forty places that remember something.

SQLite in `state/cfo.db`, in WAL mode so a reader never waits for the writer.
Every write runs in `tx()`, which takes the write lock up front (BEGIN
IMMEDIATE): two requests that read-modify-write the same rows queue instead of
both reading the old state and one overwriting the other. That is what the
thread locks around the JSON files did inside one process; this holds across
processes too.
"""
import json
import logging
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import config

log = logging.getLogger("cfo.db")

# CFO_DB points the whole app at another file; the test runner sets it so no
# test can reach the real database.
PATH = Path(os.getenv("CFO_DB") or config.ROOT / "state" / "cfo.db")
MIGRATIONS = Path(__file__).parent / "migrations"
BUSY_TIMEOUT_S = 10.0

_ready: dict[str, int] = {}          # path -> company id, once migrated
_ready_lock = threading.Lock()


def now() -> str:
    """A moment, in UTC, as the schema stores it."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- money
def to_ore(kr) -> int | None:
    """Kroner to whole øre. Floats drift; integers do not."""
    if kr is None:
        return None
    return int(round(float(kr) * 100))


def to_kr(ore) -> float | None:
    if ore is None:
        return None
    return ore / 100


# ----------------------------------------------------------------- JSON
def dumps(value) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def loads(text, default=None):
    if text is None:
        return default
    return json.loads(text)


# ---------------------------------------------------------- connections
def _open(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: no implicit transactions. `tx()` says when one
    # starts and what kind, so nothing is ever half-committed by accident.
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_S, isolation_level=None,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_S * 1000)}")
    return conn


def _ensure(path: Path) -> int:
    """Migrate this file once per process, and return the company's id."""
    key = str(path)
    if key in _ready:
        return _ready[key]
    with _ready_lock:
        if key in _ready:
            return _ready[key]
        conn = _open(path)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            _migrate(conn)
            cid = _company(conn)
            _import_json(conn, cid, path.parent)
        finally:
            conn.close()
        _ready[key] = cid
        return cid


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """A write transaction: all of it lands, or none of it does.

    The write lock is taken at the start, so a read inside it sees the state
    no other writer can change before this one commits.
    """
    _ensure(PATH)
    conn = _open(PATH)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.close()


@contextmanager
def read() -> Iterator[sqlite3.Connection]:
    """A consistent read: one snapshot for every query inside it."""
    _ensure(PATH)
    conn = _open(PATH)
    try:
        conn.execute("BEGIN")
        try:
            yield conn
        finally:
            conn.execute("ROLLBACK")
    finally:
        conn.close()


def company_id() -> int:
    """The company every row belongs to.

    One company until login exists (card 8); then the request names it, and a
    query without one fails instead of guessing.
    """
    return _ensure(PATH)


def next_ref(conn: sqlite3.Connection, series: str, prefix: str) -> str:
    """The next short id in a series — F004, K014 — inside the caller's
    transaction, so two writers cannot be handed the same one."""
    cid = company_id()
    conn.execute("INSERT OR IGNORE INTO counters (company_id, series, value) "
                 "VALUES (?, ?, 0)", (cid, series))
    value = conn.execute(
        "UPDATE counters SET value = value + 1 WHERE company_id = ? AND series = ? "
        "RETURNING value", (cid, series)).fetchone()[0]
    return f"{prefix}{value:03d}"


# ------------------------------------------------------------- migrations
def _migrate(conn: sqlite3.Connection) -> None:
    """Run every migration file not yet recorded, in name order, each once."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version ("
                 "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if f.stem in done:
            continue
        sql = f.read_text(encoding="utf-8").replace(
            "CREATE TABLE schema_version", "CREATE TABLE IF NOT EXISTS schema_version")
        # executescript commits as it goes, so the script runs inside its own
        # BEGIN/COMMIT: a migration that fails half-way leaves no half-schema.
        conn.executescript(f"BEGIN;\n{sql}\nINSERT INTO schema_version "
                           f"VALUES ('{f.stem}', '{now()}');\nCOMMIT;")
        log.info("Database: migrering %s kjørt", f.stem)


def _company(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM companies ORDER BY id LIMIT 1").fetchone()
    if row:
        return row[0]
    cur = conn.execute("INSERT INTO companies (name, created_at) VALUES (?, ?)",
                       (config.COMPANY_NAME, now()))
    log.info("Database: selskapet %s opprettet", config.COMPANY_NAME)
    return cur.lastrowid


# ------------------------------------------------- the one-time JSON import
IMPORT_VERSION = "import_json"


def _import_json(conn: sqlite3.Connection, cid: int, state: Path) -> None:
    """Bring `memory.json` and `cards.json` in, once, keeping every id and date.

    Runs in one transaction and records itself in `schema_version`, so it
    happens exactly once whatever restarts in between. The files are renamed to
    `*.json.migrated`, never deleted. A file that cannot be read is set aside
    as `*.json.corrupt` and the import goes on without it, as the JSON stores
    did themselves.
    """
    if conn.execute("SELECT 1 FROM schema_version WHERE version = ?",
                    (IMPORT_VERSION,)).fetchone():
        return
    sources = {name: state / f"{name}.json" for name in ("memory", "cards")}
    data = {}
    for name, f in sources.items():
        if not f.exists():
            continue
        try:
            data[name] = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.error("Database: %s er ulesbar (%s); settes til side", f.name, exc)
            f.rename(f.with_suffix(".json.corrupt"))

    conn.execute("BEGIN IMMEDIATE")
    try:
        counts = {}
        if "memory" in data:
            counts.update(_import_memory(conn, cid, data["memory"]))
        if "cards" in data:
            counts.update(_import_cards(conn, cid, data["cards"]))
        conn.execute("INSERT INTO schema_version VALUES (?, ?)",
                     (IMPORT_VERSION, now()))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    for name in data:
        sources[name].rename(sources[name].with_suffix(".json.migrated"))
    if data:
        log.info("Database: importerte %s", ", ".join(
            f"{v} {k}" for k, v in counts.items()))


def _set_counter(conn, cid: int, series: str, value: int) -> None:
    conn.execute("INSERT INTO counters (company_id, series, value) VALUES (?, ?, ?) "
                 "ON CONFLICT (company_id, series) DO UPDATE SET "
                 "value = max(value, excluded.value)", (cid, series, value))


def _highest(refs) -> int:
    nums = [int(r[1:]) for r in refs if r and r[1:].isdigit()]
    return max(nums, default=0)


def _import_memory(conn, cid: int, mem: dict) -> dict:
    for s in mem.get("snapshots") or []:
        for kpi, value in (s.get("kpis") or {}).items():
            if isinstance(value, (int, float)):
                conn.execute(
                    "INSERT OR REPLACE INTO kpi_snapshots VALUES (?, ?, ?, ?, ?)",
                    (cid, s["date"], kpi, float(value), s.get("definitions_hash")))
    for f in mem.get("findings") or []:
        conn.execute(
            "INSERT INTO findings (company_id, ref, opened_on, topic, severity, "
            "statement, metric, value, status, closed_on, outcome) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, f["id"], f.get("opened") or "", f.get("topic") or "",
             f.get("severity") or "medium", f.get("statement") or "",
             f.get("metric"), f.get("value"), f.get("status") or "open",
             f.get("closed"), f.get("outcome")))
    for p in mem.get("forecasts") or []:
        conn.execute(
            "INSERT INTO predictions (company_id, ref, made_on, period, metric, "
            "expected, low, high, basis, actual, scored_on, error_pct, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, p["id"], p.get("made") or "", p.get("period") or "",
             p.get("metric") or "", p.get("expected"), p.get("low"), p.get("high"),
             p.get("basis"), p.get("actual"), p.get("scored"), p.get("error_pct"),
             p.get("note")))
    for d in mem.get("decisions") or []:
        conn.execute(
            "INSERT INTO decisions (company_id, ref, decided_on, decision, context) "
            "VALUES (?, ?, ?, ?, ?)",
            (cid, d["id"], d.get("date") or "", d.get("decision") or "",
             d.get("context")))
    refs = [r.get("id") for k in ("findings", "forecasts", "decisions")
            for r in mem.get(k) or []]
    _set_counter(conn, cid, "memory",
                 max(int(mem.get("counter") or 0), _highest(refs)))
    return {"snapshots": len(mem.get("snapshots") or []),
            "findings": len(mem.get("findings") or []),
            "predictions": len(mem.get("forecasts") or []),
            "decisions": len(mem.get("decisions") or [])}


def _import_cards(conn, cid: int, deck: dict) -> dict:
    import cards as cards_mod          # the row mapping lives with the deck
    for c in deck.get("cards") or []:
        cards_mod.insert_row(conn, cid, c, event="created", actor="import")
    _set_counter(conn, cid, "cards",
                 max(int(deck.get("counter") or 0),
                     _highest(c.get("id") for c in deck.get("cards") or [])))
    return {"cards": len(deck.get("cards") or [])}


def reset_for_tests(path: Path) -> None:
    """Point the module at a fresh file. Only the tests call this."""
    global PATH
    PATH = Path(path)
    _ready.pop(str(PATH), None)
