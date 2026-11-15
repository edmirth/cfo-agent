"""The data map and the chart (card 70, step 2): the format, which entries
count, and a map moving a role all the way through a forecast."""
import json
import tempfile
from pathlib import Path

import chart
import datamap
from tests.test_cashflow_build import REVENUE, _cum, _forecast, _invoice


def _map(accounts: dict, **extra) -> dict:
    return {"schema": 1, "version": 1, "made": "2026-11-15", "made_by": "hand",
            "accounts": accounts, **extra}


def _stored(raw: dict):
    """Point the data maps at a fresh folder holding `raw` for company 1."""
    folder = Path(tempfile.mkdtemp()) / "data_maps"
    folder.mkdir()
    (folder / "1.json").write_text(json.dumps(raw), encoding="utf-8")
    real = datamap.DIR
    datamap.DIR = folder
    return real


def test_accounts_are_read_as_numbers_and_ranges():
    m = datamap.parse(_map({"receivables": {"accounts": [[1500, 1509], 1530],
                                            "check": "verified", "why": "factoring"}}))
    assert m.accounts["receivables"].value == ((1500, 1509), (1530, 1530))
    assert m.accounts["receivables"].why == "factoring" and not m.problems


def test_a_bad_entry_is_left_out_with_its_reason():
    m = datamap.parse(_map({
        "receivables": {"accounts": [[1509, 1500]], "check": "verified"},
        "revenue": {"accounts": [3000], "check": "probably"},
        "kitchen_sink": {"accounts": [1000], "check": "verified"}}))
    assert m.accounts == {}
    assert len(m.problems) == 3
    assert any("no such role" in p for p in m.problems)


def test_another_schema_is_not_read():
    assert datamap.parse({"schema": 2, "accounts": {}}) is None
    assert datamap.parse(["not", "a", "map"]) is None


def test_no_map_is_the_standard_chart():
    real = datamap.DIR
    datamap.DIR = Path(tempfile.mkdtemp()) / "nowhere"
    try:
        assert chart.for_company(1) is chart.DEFAULT
    finally:
        datamap.DIR = real


def test_only_what_the_books_confirm_is_used():
    real = _stored(_map({
        "receivables": {"accounts": [[1500, 1509], 1530], "check": "verified"},
        "revenue": {"accounts": [[3000, 3199]], "check": "contradicted"},
        "wages": {"accounts": [5000], "check": "unchecked"}}))
    try:
        c = chart.for_company(1)
    finally:
        datamap.DIR = real
    assert c.receivables == ((1500, 1509), (1530, 1530))
    assert c.source("receivables") == "verified"
    assert c.revenue == chart.DEFAULT.revenue and c.source("revenue") == "default"
    assert c.wages == chart.DEFAULT.wages


def test_a_role_the_commitments_read_does_not_move_yet():
    """Until the commitments take the company's chart (step 2b), moving a
    role they read would have the forecast and the commitments on different
    accounts."""
    real = _stored(_map({"payables": {"accounts": [[2400, 2419]], "check": "verified"}}))
    try:
        c = chart.for_company(1)
    finally:
        datamap.DIR = real
    assert c.payables == chart.DEFAULT.payables


def test_a_verified_map_moves_the_receivables_reconciliation():
    """Factoring receivables on 1530: outside the standard 1500-1509, the
    ledger looks short of the invoices; with the map, 1530 is receivables."""
    ar = [_invoice(100_000.0, "2026-09-20", "2026-10-20")]
    ledger = [REVENUE, _cum("1500 Kundefordringer", [0.0] * 9 + [100_000.0]),
              _cum("1530 Factoringfordringer", [0.0] * 9 + [40_000.0])]

    def residual():
        data = _forecast(ledger, ar=ar)
        return data["assumptions"]["ukjente_fordringer"]["belop"]

    import db
    real = _stored(_map({"receivables": {"accounts": [[1500, 1509], 1530],
                                         "check": "verified"}}))
    try:
        cid = db.company_id()
        folder = datamap.DIR
        (folder / "1.json").rename(folder / f"{cid}.json")
        with_map = residual()
    finally:
        datamap.DIR = real
    assert residual() == 0.0, "without the map 1530 is not receivables"
    assert with_map == 40_000.0
