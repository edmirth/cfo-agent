"""Every bank line with a category (card 63). Made-up names throughout."""
import asyncio
from datetime import date

import bankcat
import company

EMPLOYEES = [bankcat._words("Kari Nordmann"), bankcat._words("Ola Jakob Hansen")]
CUSTOMERS = {bankcat._norm("Fjordbygg AS")}
SUPPLIERS = {bankcat._norm("Vaskemiddel Grossist")}


def _cat(name, amount, day="2026-10-20", posting=""):
    original = company.setting
    company.setting = lambda k, d=None: {"lonn_utbetalingsdag": 10}.get(k, d)
    try:
        return bankcat.category({"name": name, "amount": amount, "date": day, "posting": posting},
                                CUSTOMERS, EMPLOYEES, SUPPLIERS)
    finally:
        company.setting = original


def test_the_authorities_and_the_lenders_by_name():
    assert _cat("MERVERDIAVGIFT-OCR INNBET.", -700_000) == "mva"
    assert _cat("Skatteetaten-Skatteinnkreving", -250_000) == "skatt"
    assert _cat("NORDEA FINANCE EQUIPMENT AS", -16_000) == "lan"
    assert _cat("BERTEL O STEEN BILUTLEIE AS", -11_000) == "lan"
    assert _cat("IF SKADEFORSIKRING NUF", -14_000) == "forsikring"
    assert _cat("NORDEA LIV AS", -22_000) == "pensjon"
    assert _cat("Omkostninger", -300) == "gebyr"
    assert _cat("Varekjøp", -900) == "kort"
    assert _cat("Kari Nordmann leie", -23_000, day="2026-10-01") == "husleie"


def test_the_posting_a_line_is_matched_to_names_it_too():
    assert _cat("Ukjent tekst", -221, posting="Bankgebyr: Omkostninger") == "gebyr"


def test_money_in_from_a_customer():
    assert _cat("FJORDBYGG AS", 50_000) == "kunder"
    assert _cat("Noen andre", 12_000, posting="Betaling: Faktura nummer 1001 til Noen AS (30001)") == "kunder"
    assert _cat("NAV", 44_000) == "nav"
    assert _cat("Noen andre", 12_000) == "ukjent"


def test_an_employee_however_the_bank_spells_him():
    """Surname first, a middle initial, a digit the bank added."""
    assert _cat("Nordmann Kari", -30_000, day="2026-10-25") == "lonn"
    assert _cat("Ola J. Hansen", -30_000, day="2026-10-25") == "lonn"
    assert _cat("Kari Nordmann2", -30_000, day="2026-10-25") == "lonn"


def test_a_private_person_paid_on_the_pay_day_is_wages():
    """The register does not know nicknames; the pay day does."""
    assert _cat("Giorgo", -21_000, day="2026-10-09") == "lonn"
    assert _cat("Giorgo", -21_000, day="2026-10-25") == "ukjent"


def test_a_company_paid_is_a_supplier():
    assert _cat("Renholdsutstyr Nord AS", -114_000) == "leverandorer"
    assert _cat("Vaskemiddel Grossist", -5_000) == "leverandorer"
    assert _cat("Betaling med kid", -8_000) == "leverandorer"


def test_the_summary_by_month_and_what_is_unknown():
    original = company.setting
    company.setting = lambda k, d=None: {"lonn_utbetalingsdag": 10}.get(k, d)
    try:
        out = bankcat.summary([
            {"date": "2026-09-10", "name": "Kari Nordmann", "amount": -30_000.0, "posting": ""},
            {"date": "2026-09-15", "name": "FJORDBYGG AS", "amount": 50_000.0, "posting": ""},
            {"date": "2026-09-20", "name": "Per Privat", "amount": -10_000.0, "posting": ""},
            {"date": "2026-10-12", "name": "MERVERDIAVGIFT", "amount": -60_000.0, "posting": ""}],
            CUSTOMERS, EMPLOYEES, SUPPLIERS)
    finally:
        company.setting = original
    assert out["months"]["2026-09"]["lonn"] == {"inn": 0.0, "ut": -30_000.0}
    assert out["months"]["2026-09"]["kunder"] == {"inn": 50_000.0, "ut": 0.0}
    assert out["unknown"] == [{"name": "Per Privat", "amount": -10_000.0, "lines": 1}]
    assert out["unknown_share_out"] == 0.1


class _Bank:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    async def call(self, tool, args):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Tripletex svarte ikke")
        if tool == "get_bank_reconciliation_periods":
            return {"periods": [{"accountNumber": "1920", "status": "open",
                                 "period": {"start": "2026-10-01"}}]}
        if tool == "get_unmatched_bank_transactions":
            line = {"id": 1 if args["matchStatus"] == "matched" else 2, "postedDate": "2026-10-15",
                    "description": "FJORDBYGG AS" if args["matchStatus"] == "matched" else "Per Privat",
                    "amountCurrency": 50_000.0 if args["matchStatus"] == "matched" else -10_000.0}
            return {args["matchStatus"]: [line]}
        if tool == "search_employees":
            return {"employees": [{"firstName": "Kari", "lastName": "Nordmann"}]}
        if tool == "list_suppliers":
            return {"suppliers": []}
        return {}


def test_read_once_a_day_and_a_failure_is_not_kept():
    bankcat.CACHE.clear()
    bank = _Bank()
    first = asyncio.run(bankcat.measured(bank, date(2026, 11, 8), {"Fjordbygg AS"}))
    calls = bank.calls
    assert first["months"]["2026-10"]["kunder"]["inn"] == 50_000.0
    assert asyncio.run(bankcat.measured(bank, date(2026, 11, 8), {"Fjordbygg AS"})) is first
    assert bank.calls == calls
    bankcat.CACHE.clear()
    assert asyncio.run(bankcat.measured(_Bank(fail=True), date(2026, 11, 8), set())) is None
    assert bankcat.CACHE == {}
