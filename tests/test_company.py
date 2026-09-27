import company


def test_settings_block_and_warnings():
    settings, story, notes = company._parse(
        "---\nlonn_etterskuddsvis_mnd: 1  # kommentar\nlonn_utbetalingsdag: tjue\nrart: x\n---\n\n# Historie\n")
    assert settings == {"lonn_etterskuddsvis_mnd": 1, "rart": "x"}
    assert story.startswith("# Historie")
    assert any("tjue" in n for n in notes) and any("rart" in n for n in notes)


def test_unclosed_block_reads_nothing():
    settings, _, notes = company._parse("---\nlonn_utbetalingsdag: 20\n\ntekst uten avslutning")
    assert settings == {} and notes
