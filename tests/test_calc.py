import calc


def test_expressions():
    assert calc.evaluate("15600 + 18444 + 31200 + 10400") == 75644
    assert calc.num(calc.evaluate("sum([12575, 271, 10959])")) == "23 805"
    assert round(calc.evaluate("11355165 / 13358058 * 100"), 1) == 85.0


def test_refuses_code():
    for bad in ["__import__('os')", "open('/etc/passwd')", "x + 1", "'a'*3",
                "1/0", "2**999"]:
        try:
            calc.evaluate(bad)
        except calc.CalcError:
            continue
        raise AssertionError(f"allowed: {bad}")


def test_dso_grosses_up_vat():
    r = calc.metric("dso", {"receivables": 1997489, "revenue": 13358058, "days": 263})
    assert r["value"] == 31.5, r
    assert "1,25" in r["shown"]


def test_variance_reports_pct():
    r = calc.metric("variance", {"actual": 504985, "budget": 1625897})
    assert r["value"] == -1120912 and r["pct"] == -68.9
