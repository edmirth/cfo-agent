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


def test_a_setting_only_the_cfo_reads_is_not_listed_as_moving_numbers():
    import main  # noqa: F401 — the payload the Selskapet page reads
    payload = main._company_payload({"exists": True, "settings": {
        "lonn_etterskuddsvis_mnd": 1, "kredittid_dager": 30}, "notes": []})
    assert payload["used_in_calculations"] == ["kredittid_dager"]


def test_the_starter_is_neutral_and_carries_the_customers_name():
    # Every new customer starts from the root company.md. One company's facts
    # left switched on in it would be told to the next company's CFO as theirs.
    import tempfile
    from pathlib import Path

    import config
    saved = company.COMPANY_FILE, config.COMPANY_NAME
    company.COMPANY_FILE = Path(tempfile.mkdtemp()) / "company.md"
    config.COMPANY_NAME = "Testfirma AS"
    company._cache.clear()
    try:
        data = company.load(force=True)
        text = company.COMPANY_FILE.read_text(encoding="utf-8")
    finally:
        company.COMPANY_FILE, config.COMPANY_NAME = saved
        company._cache.clear()
    assert data["settings"] == {} and data["notes"] == []
    assert "# Slik fungerer Testfirma AS" in text and "{selskap}" not in text
    assert "Ullensaker" not in text
