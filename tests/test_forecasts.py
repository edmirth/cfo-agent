"""Every forecast kept, with the bank balances it will be scored against."""
import cashflow
import db
import forecasts
import job_runs
from tests import _tmp
from tests.test_bankgap import OCTOBER_RECEIPT, _build
from tests.test_cashflow_build import TODAY, _cum

ROWS = [_cum("1920 Bedriftskonto", [1_000_000] + [0] * 9),
        _cum("1500 Kundefordringer", [0] * 8 + [48813, 0]),
        _cum("3000 Salgsinntekt", [-100000] * 10)]
AR = [{"id": 1, "customerName": "As Bækkelagshallen", "invoiceNumber": 6623,
       "dueDate": "2026-09-30", "invoiceDate": "2026-09-01",
       "amountOutstanding": 48813.0}]


def _count(table):
    with db.read() as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_a_whole_forecast_is_kept_once_a_day_with_every_week_and_line():
    _tmp.db()
    data = _build(ROWS, AR, 1_000_000.0, OCTOBER_RECEIPT)
    kept = forecasts.runs()
    assert len(kept) == 1
    run = kept[0]
    assert run["made_on"] == TODAY.isoformat()
    assert run["opening"] == data["opening"] == 1_048_813.0
    assert run["opening_source"] == "bank_feed"
    assert run["low_committed"] == {"amount": data["low_committed"]["amount"],
                                    "start": data["low_committed"]["start"]}
    assert run["assumptions"]["credit_days"] == data["assumptions"]["credit_days"]
    assert [w["committed_close"] for w in run["weeks"]] == \
        [w["committed_close"] for w in data["weeks"]]
    assert len(run["weeks"]) == 13
    assert _count("forecast_flows") == sum(len(w["items"]) for w in data["weeks"])

    # The run that saved it is recorded, and the forecast points back at it.
    saved = job_runs.recent("forecast")
    assert [r["status"] for r in saved] == ["ok"]
    with db.read() as conn:
        assert conn.execute("SELECT job_run_id FROM forecast_runs").fetchone()[0] \
            == saved[0]["id"]

    # A second build the same day keeps the first forecast and opens no run.
    _build(ROWS, AR, 1_000_000.0, OCTOBER_RECEIPT)
    assert len(forecasts.runs()) == 1 and len(job_runs.recent("forecast")) == 1


def test_the_bank_balance_is_kept_booked_and_as_the_bank_has_it():
    _tmp.db()
    _build(ROWS, AR, 1_000_000.0, OCTOBER_RECEIPT)
    assert forecasts.balances("ledger") == [
        {"on_date": TODAY.isoformat(), "account": "1920", "source": "ledger",
         "balance": 1_000_000.0}]
    # Filed under the feed's last line, not today: that is the day it is true of.
    assert forecasts.balances("bank_feed") == [
        {"on_date": "2026-10-01", "account": "1920", "source": "bank_feed",
         "balance": 1_048_813.0}]
    # A later reading the same day replaces the earlier one.
    _build(ROWS, AR, 1_000_000.0, OCTOBER_RECEIPT)
    assert len(forecasts.balances("ledger")) == 1


def test_a_bank_that_could_not_be_read_gives_no_bank_figure_to_score_against():
    _tmp.db()
    _build(ROWS, AR, 1_000_000.0, None)
    assert forecasts.balances("bank_feed") == []
    assert len(forecasts.balances("ledger")) == 1
    assert forecasts.runs()[0]["opening_source"] == "ledger"


def test_a_partial_forecast_is_not_kept():
    _tmp.db()
    data = {"partial": True, "opening": 1.0, "weeks": [], "bank": {}}
    written = forecasts.record(data, {"1920": 500.0}, TODAY)
    assert written == {"forecast_run": None, "balances": 1}
    assert forecasts.runs() == [] and job_runs.recent("forecast") == []


def test_a_failure_to_save_never_costs_the_forecast():
    _tmp.db()
    original = forecasts.record

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    forecasts.record = broken
    try:
        data = _build(ROWS, AR, 1_000_000.0, OCTOBER_RECEIPT)
    finally:
        forecasts.record = original
    assert data["opening"] == 1_048_813.0 and len(data["weeks"]) == 13
