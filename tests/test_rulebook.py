"""The company's rules: the floor, reminder days, alert minimum and payroll
target are read from company.md, and a missing one falls back to a default
that everything using it calls assumed."""
import tempfile
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import cards
import cashflow
import company
import industry
import summary


@contextmanager
def _company(block: str = ""):
    """company.md with this settings block, in a throwaway directory."""
    saved = company.COMPANY_FILE, company.TEMPLATE
    path = Path(tempfile.mkdtemp()) / "company.md"
    path.write_text(f"---\n{block}\n---\n\nTekst.\n", encoding="utf-8")
    company.COMPANY_FILE, company.TEMPLATE = path, path.with_name("ingen-mal.md")
    company._cache.clear()
    try:
        yield
    finally:
        company.COMPANY_FILE, company.TEMPLATE = saved
        company._cache.clear()


SET = ("likviditetsgulv_kr: 2 000 000\npurring_etter_dager: 30\n"
       "varsel_minimum_kr: 20k\nlonnsandel_mal_pct: 75 %\n"
       "kostnadsavvik_pct: 40")


# ------------------------------------------------------------------ reading

def test_amounts_are_read_whole_not_by_their_first_digits():
    # The plain number reader would take «2 000 000» as 2, and a floor of two
    # kroner silences every cash alert.
    assert company._kroner("2 000 000") == 2_000_000
    assert company._kroner("2 MNOK") == 2_000_000
    assert company._kroner("1,5 mill") == 1_500_000
    assert company._kroner("20k") == 20_000
    assert company._kroner("750 000 kr") == 750_000
    for unclear in ("1.5", "tjue", "-5", "2 00 000"):
        assert company._kroner(unclear) is None, unclear


def test_a_rule_that_cannot_be_read_is_refused_and_said():
    settings, _, notes = company._parse(
        "---\nlikviditetsgulv_kr: to millioner\npurring_etter_dager: -3\n"
        "lonnsandel_mal_pct: 120\n---\n")
    assert settings == {}
    assert len(notes) == 3 and all("standardverdien" in n for n in notes)


def test_the_rules_are_listed_as_known_settings():
    for key in company.RULES:
        assert key in company.KNOWN


# ------------------------------------------------------------ set vs missing

def test_a_set_rule_is_the_companys():
    with _company(SET):
        r = company.rules(monthly_wages=1_000_000)
    assert r["likviditetsgulv_kr"]["value"] == 2_000_000
    assert r["purring_etter_dager"]["value"] == 30
    assert r["varsel_minimum_kr"]["value"] == 20_000
    assert r["lonnsandel_mal_pct"]["value"] == 75
    assert r["kostnadsavvik_pct"]["value"] == 40
    assert not any(rule["assumed"] for rule in r.values())
    assert company.said(r["likviditetsgulv_kr"]) == "satt i Selskapet"


def test_a_missing_rule_uses_the_default_and_says_it_is_assumed():
    with _company():
        r = company.rules(monthly_wages=1_234_567.4)
    floor = r["likviditetsgulv_kr"]
    assert floor["value"] == 1_234_567 and floor["assumed"]
    assert floor["basis"] == "én månedslønn"
    assert r["purring_etter_dager"]["value"] == 14
    assert r["varsel_minimum_kr"]["value"] == 10_000
    assert all(r[k]["assumed"] for k in ("purring_etter_dager", "varsel_minimum_kr"))
    assert "antatt" in company.said(floor)
    # No payroll target is invented: nothing is assumed, it is simply not set.
    assert r["lonnsandel_mal_pct"]["value"] is None
    assert not r["lonnsandel_mal_pct"]["assumed"]


def test_without_wages_the_floor_falls_back_to_the_old_constant():
    with _company():
        floor = company.rules()["likviditetsgulv_kr"]
    assert floor["value"] == company.FLOOR_FALLBACK and floor["assumed"]


def test_the_agent_is_told_which_rules_are_assumed():
    with _company("purring_etter_dager: 30"):
        text = company.briefing()
    assert "Selskapets regler" in text
    assert "30 dager" in text and "satt i Selskapet" in text
    assert "10 000 kr (antatt" in text
    assert "ikke noe mål satt" in text


# -------------------------------------------------------------------- cards

def _late(days: int, amount: float, name: str = "Skanska") -> dict:
    due = (date(2026, 10, 5) - timedelta(days=days)).isoformat()
    return {"name": name, "due": due, "amount": amount, "number": 1}


def test_collections_use_the_default_reminder_days_and_minimum():
    with _company():
        out = cards._collections([_late(15, 12_000)], date(2026, 10, 5))
    assert len(out) == 1
    rule = next(e for e in out[0]["evidence"] if e["label"] == "Regel")
    assert "14 dager" in rule["value"] and "antatt" in rule["value"]


def test_collections_follow_the_companys_reminder_days_and_minimum():
    today = date(2026, 10, 5)
    with _company(SET):
        assert cards._collections([_late(15, 50_000)], today) == []   # not 30 days yet
        assert cards._collections([_late(40, 15_000)], today) == []   # under 20 000
        out = cards._collections([_late(40, 25_000)], today)
    assert len(out) == 1 and "30 dager" in out[0]["body"]


def _forecast(low: float, wages: float = 1_000_000.0) -> dict:
    week = {"label": "Uke 44", "start": "2026-10-26", "committed_close": low}
    return {"low_committed": {"amount": low, "label": "Uke 44", "start": "2026-10-26"},
            "weeks": [week], "assumptions": {"monthly_wages": wages}}


def test_the_cash_card_is_raised_under_the_assumed_floor_and_says_so():
    with _company():
        out = cards._from_cashflow(_forecast(900_000))   # under one month's wages
    assert len(out) == 1
    assert "antatt" in out[0]["body"] and "1 000 000" in out[0]["body"]
    assert any(e["label"] == "Gulv" for e in out[0]["evidence"])


def test_the_cash_card_follows_the_companys_floor():
    with _company("likviditetsgulv_kr: 500 000"):
        assert cards._from_cashflow(_forecast(900_000)) == []
    with _company("likviditetsgulv_kr: 2 MNOK"):
        out = cards._from_cashflow(_forecast(1_600_000))
    assert len(out) == 1 and "antatt" not in out[0]["body"]


def test_the_old_constants_are_gone():
    for name in ("CASH_FLOOR", "LATE_DAYS", "LATE_AMOUNT"):
        assert not hasattr(cards, name), name


# --------------------------------------------------- the forecast briefing

RATES = {"revenue": 0.0, "wages": 400_000.0, "wages_cash": 400_000.0,
         "opex": 0.0, "aga": 0.0}


def _assembled(opening: float) -> dict:
    today = date(2026, 10, 5)
    return cashflow._assemble(today, cashflow._monday(today), opening,
                              [], [], RATES, 30, [], [], [])


def test_the_briefing_measures_against_an_assumed_floor_and_says_so():
    with _company():
        text = cashflow.briefing(_assembled(300_000.0))
    assert "**Gulvet** er **400 000 kr**" in text
    assert "antatt: én månedslønn" in text
    assert "under gulvet første gang" in text


def test_the_briefing_uses_the_companys_floor():
    with _company("likviditetsgulv_kr: 250 000"):
        text = cashflow.briefing(_assembled(300_000.0))
    assert "**Gulvet** er **250 000 kr** — satt av selskapet" in text
    assert "holder seg over gulvet" in text and "antatt" not in text.split("**Gulvet**")[1].split("\n")[0]


# ---------------------------------------------------------------- the brief

def test_the_summary_is_given_the_floor_and_the_payroll_target():
    ov = {"kpis": {"omsetning": 1.0, "lonnsandel_pct": 80.0}}
    with _company(SET):
        facts = summary._shape(ov, {}, [], _forecast(1_600_000))
    assert facts["lonnsandel_mal_pct"] == 75
    assert facts["likviditetsgulv"]["kr"] == 2_000_000
    assert facts["forste_uke_under_gulvet"]["label"] == "Uke 44"
    with _company():
        facts = summary._shape(ov, {}, [], _forecast(1_600_000))
    assert facts["lonnsandel_mal_pct"] is None
    assert "antatt" in facts["likviditetsgulv"]["hvor_fra"]


def _tiles():
    return {"kpis": [{"id": "lonnsandel", "value": 78.0, "target": 70,
                      "alert": 76, "better": "low", "status": "bad"},
                     {"id": "driftsmargin", "value": 5.0, "target": 8,
                      "alert": 3, "better": "high", "status": "watch"}]}


def test_the_payroll_tile_takes_the_companys_target():
    with _company("lonnsandel_mal_pct: 80"):
        out = industry._with_rules(_tiles())
    wage = out["kpis"][0]
    assert wage["target"] == 80 and wage["target_from"] == "company.md"
    # The industry's alert sat under the company's own target; it would have
    # called the target a failure, so it gives way.
    assert wage["alert"] is None and wage["status"] == "good"
    assert out["kpis"][1]["target"] == 8


def test_without_a_payroll_target_the_industry_one_stands():
    with _company():
        out = industry._with_rules(_tiles())
    assert out["kpis"][0]["target"] == 70 and "target_from" not in out["kpis"][0]
