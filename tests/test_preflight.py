import preflight


def test_payables_tie_on_their_own_side():
    """Tripletex returns Leverandørreskontro negative, the same side as 2400.

    Negating one of them reported 65 937 kr missing from books that tied to the
    øre, which set the whole preflight to "broken" and told the CFO that no
    payables figure could be quoted.
    """
    assert preflight._tie(-32968.67, -32968.67) == 0.0


def test_receivables_tie_on_their_own_side():
    assert preflight._tie(2007750.0, 2007750.0) == 0.0


def test_tie_still_catches_an_account_on_the_wrong_side():
    # 2400 standing in debit against a credit subledger is a real break, and
    # must not cancel to nothing the way comparing magnitudes would.
    assert abs(preflight._tie(32968.67, -32968.67) - 65937.34) < 1e-6


def test_tie_reports_a_genuine_shortfall():
    assert abs(preflight._tie(-30000.0, -32968.67) - 2968.67) < 1e-6
