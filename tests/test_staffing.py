import industry


def _script(payload: str):
    """What tripletex_run_script hands back: printed lines in `output`."""
    return {"output": [payload], "executionTimeMs": 1}


def test_fte_is_the_sum_of_the_employment_percentages():
    # Ullensaker: 34 heads, 20.0 årsverk — 11 people on 20 %, 8 on 100 %.
    heads, fte = industry._staffing(
        _script('{"headcount": 34, "with_percentage": 34, "fte": 20.0}'))
    assert (heads, fte) == (34, 20.0)


def test_headcount_without_percentages_does_not_become_fte():
    """One person without a percentage would be counted as nobody, shrinking
    the denominator and flattering every per-employee figure — the opposite of
    the error this replaces. Fall back to heads and say so."""
    heads, fte = industry._staffing(
        _script('{"headcount": 34, "with_percentage": 33, "fte": 19.0}'))
    assert heads == 34 and fte is None


def test_a_failed_script_yields_nothing_rather_than_a_guess():
    for bad in ({}, {"output": []}, {"output": ["not json"]}, None):
        assert industry._staffing(bad or {}) == (None, None)


def test_an_empty_payroll_is_not_zero_fte():
    heads, fte = industry._staffing(
        _script('{"headcount": 0, "with_percentage": 0, "fte": 0}'))
    assert heads is None and fte is None


def test_per_head_divides_by_fte_and_says_so():
    import calc
    r = calc.metric("per_head", {"value": 18600900, "fte": 20.0})
    assert r["value"] == 930045.0
    assert "årsverk" in r["shown"] and "årsverk" in r["note"]


def test_per_head_refuses_rather_than_dividing_by_nothing():
    import calc
    try:
        calc.metric("per_head", {"value": 100, "fte": 0})
    except calc.CalcError:
        return
    raise AssertionError("dividing by zero årsverk should raise")
