import overview


def _row(path: str, closing):
    """A saldobalanse row: the last cell is the closing balance."""
    return {"path": path, "cells": [0, 0, closing]}


# Ullensaker's real trial balance, trimmed to the accounts that matter.
REAL = [
    _row("1100 Bygninger", 51240), _row("1101 Avskrivninger kontor hjemme", -11009.97),
    _row("1102 Utebod/Redskapsbod", 3900), _row("1233 Citroen Berlingo", 8889),
    _row("1234 MG / MGS6", 482387), _row("1235 Citroën Berlingo", 172266.42),
    _row("1236 Audi E-tron", 0), _row("1237 Peugeot Mester Partner", 62833.03),
    _row("1500 Kundefordringer", 2539600), _row("1571 Lønnsforskudd", 111619.91),
    _row("1720 Forskuddsbetalte kostnader", 14696.69),
    _row("1920 Bedriftskonto", 2625898.93), _row("1950 Skattetrekk", 0),
    _row("2000 Aksjekapital", -100000), _row("2050 Annen egenkapital", -1552732.37),
    _row("2120 Utsatt skatt", -2135), _row("2229 Santander", -16981.36),
    _row("2231 Lån DS32516", -208232.9), _row("2232 Lån EP95468", -453929.53),
    _row("2250 Gjeld til ansatte", -7137.34), _row("2400 Leverandørgjeld", -32968.67),
    _row("2610 Utleggstrekk", 8490.5), _row("2700 Utgående mva", -1156938.25),
    _row("2710 Inngående mva", 145027.23), _row("2770 Skyldig aga", -199990.36),
    _row("2785 Påløpt aga ferielønn", -140201), _row("2910 Gjeld ansatte", 37867.5),
    _row("2940 Skyldig feriepenger", -994332.53),
    _row("2945 Periodisering av lønn", -986108),
    _row("2990 Annen kortsiktig gjeld", -6112), _row("2991 Gjeld kjøp av bil", -10000),
    _row("3000 Salgsinntekt", -13994237.25),       # must be ignored
    _row("5000 Lønn til ansatte", 8776461.48),     # must be ignored
]


def test_equity_is_assets_less_debt_not_a_report_row():
    """Tripletex's own Egenkapitalandel row returns 0 for this company; the
    trial balance gives the real figure.

    A snapshot of Ullensaker's ledger, not today's — the live figure moves daily
    as invoices and VAT are booked. What is pinned is the arithmetic:

        assets  (1000-1999)   6 062 321.01
        debt    (2100-2999)  -4 023 681.71
        equity   residual     2 038 639.30  ->  33.63 %
    """
    assert overview.equity_ratio(REAL) == 33.6


def test_equity_accounts_are_excluded_from_both_sides():
    # 2000 and 2050 are equity, not debt. Counting them as debt would halve it.
    assert overview._side_total(REAL, 2100, 2999) < 0
    assert all(overview.account_number(r) not in (2000, 2050)
               for r in REAL if 2100 <= (overview.account_number(r) or 0) <= 2999)


def test_profit_and_loss_accounts_are_ignored():
    assert overview._side_total(REAL, 1000, 1999) == sum(
        r["cells"][-1] for r in REAL if 1000 <= (overview.account_number(r) or 0) <= 1999)


def test_a_debt_free_company_is_a_hundred_per_cent_not_unknown():
    """Owing nothing is a fact about the company, not missing data. This used
    to return None because the guard required a debt range to exist."""
    assert overview.equity_ratio([_row("1920 Bedriftskonto", 500000)]) == 100.0


def test_no_assets_is_unknown_not_zero():
    assert overview.equity_ratio([_row("2400 Leverandørgjeld", -5000)]) is None
    assert overview.equity_ratio([]) is None


def test_debt_exceeding_assets_goes_negative_rather_than_clamping():
    rows = [_row("1920 Bedriftskonto", 100000), _row("2400 Leverandørgjeld", -150000)]
    assert overview.equity_ratio(rows) == -50.0


def test_a_thin_margin_keeps_two_decimals():
    """0.043 % must not read as 0.0 — nothing left and almost nothing left are
    different findings."""
    assert overview._pct(5765.68, 13477929.68) == 0.04
    assert overview._pct(83.8 * 100, 10000) == 83.8      # ordinary case keeps one
    assert overview._pct(-4000, 10000) == -40.0
