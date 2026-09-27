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
