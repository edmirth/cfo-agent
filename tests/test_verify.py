import verify


def test_norwegian_number_shapes():
    cases = {
        "75 644 kr, 3,8 % av 2 007 750 kr": {3.8, 75644.0, 2007750.0},
        "2625898.93 3.8 1.504 75644": {1.504, 3.8, 75644.0, 2625898.93},
        '{"a":2625898.93,"b":1920,"c":1.5}': {1.5, 1920.0, 2625898.93},
        "1.234.567,89": {1234567.89},
        "2,6 mill.": {2.6, 2600000.0},
        "-247 365": {-247365.0},
    }
    for text, want in cases.items():
        assert verify.numbers(text) == want, (text, verify.numbers(text))


def test_identifiers_and_dates_are_not_figures():
    got = verify.numbers("konto 1500, faktura 6689, uke 50, den 16.–24. juli 2026-09-01")
    assert got == set(), got


def test_tolerance_is_magnitude_aware():
    c = verify.Corpus()
    c.add("2625898.93 3.8 1.504", "x")
    assert c.supports(2625899) and not c.supports(2625000)
    assert c.supports(3.79) and not c.supports(4.2)
    assert c.supports(1.5)


def test_check_traces_and_flags():
    c = verify.Corpus()
    c.add('{"closing":2625898.93}', "get_balance_sheet")
    c.add("Sum: 34 044", "calculate")
    r = verify.check("2 625 899 kr på konto, 34 044 kr forfalt, margin 4,7 %, rundt 960 000 kr", c)
    assert {t["value"] for t in r["traced"]} == {2625899.0, 34044.0}
    assert r["unverified"] == [960000.0] and r["minor"] == [4.7]
    assert any("get_balance_sheet" in t["from"] for t in r["traced"])


def test_sources_keep_names_across_rounds():
    class B:
        def __init__(self, **kw): self.__dict__.update(kw)
    names = {}
    verify.sources([B(type="mcp_tool_use", id="t1", name="get_balance_sheet", input={})], names)
    out = verify.sources([B(type="mcp_tool_result", tool_use_id="t1",
                            content=[{"type": "text", "text": "42"}])], names)
    assert out[0][0] == "get_balance_sheet", out


def test_a_minus_written_out_is_read_as_one():
    assert verify.numbers("Kassa står i minus 845 481 kr") == {-845481.0}
    assert verify.numbers("Saldo −845 481 kr") == {-845481.0}
    assert verify.numbers("Resultat: –12 300 kr") == {-12300.0}
    # Ranges stay ranges.
    assert verify.numbers("uke 3–5") == {5.0}
    assert verify.numbers("100–200 kr") == {100.0, 200.0}


def test_a_negative_figure_is_traced_however_it_is_written():
    c = verify.Corpus()
    c.add('{"saldo": -845481.0}', "get_balance_sheet")
    c.add("Likviditet uke 4: −1 363 822 kr", "fakta")
    for answer in ("Kassa står i minus 845 481 kr.", "Saldoen er -845 481 kr.",
                   "Et underskudd på 845 481 kr.", "Laveste punkt −1 363 822 kr.",
                   "Laveste punkt -1 363 822 kr."):
        r = verify.check(answer, c)
        assert r["unverified"] == [], (answer, r)
    signed = verify.check("Saldoen er -845 481 kr.", c)["traced"][0]
    assert "note" not in signed
    unsigned = verify.check("Et underskudd på 845 481 kr.", c)["traced"][0]
    assert unsigned["note"] == "fortegn ulikt"


def test_a_figure_with_no_source_is_still_flagged():
    c = verify.Corpus()
    c.add('{"saldo": -845481.0}', "get_balance_sheet")
    assert verify.check("Kassa står i minus 845 000 kr.", c)["unverified"] == [-845000.0]
