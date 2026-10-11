"""Customers in trouble, pinned against a made-up register.

Tripletex's customer list and Enhetsregisteret are both stand-ins; what is
checked is the matching, what is kept, that a failure is never a clean bill,
the card, and that a bankrupt customer's money leaves the forecast.
"""
import asyncio
from datetime import date

import brreg
import cards
import company
import db
from tests import _tmp
from tests.test_cashflow_build import _forecast, _invoice, _kinds

TODAY = date(2026, 10, 12)

CUSTOMERS = [
    {"name": "Skanska Norge AS", "organizationNumber": "943 049 467"},
    {"name": "Seby AS", "organizationNumber": "911111111"},
    {"name": "Låven Boligsameie", "organizationNumber": "922222222"},
    {"name": "Avvikling AS", "organizationNumber": "933333333"},
    {"name": "Borte AS", "organizationNumber": "944444444"},
    {"name": "Ola Nordmann", "isPrivateIndividual": True},
    {"name": "Uten Nummer AS"},
    {"name": "Dobbel AS", "organizationNumber": "955555555"},
    {"name": "Dobbel AS", "organizationNumber": "966666666"},
]
REGISTER = {
    "943049467": {"navn": "SKANSKA NORGE AS", "konkurs": False},
    "911111111": {"navn": "SEBY AS", "konkurs": True, "konkursdato": "2026-10-09"},
    "922222222": {"navn": "LÅVEN BOLIGSAMEIE", "konkurs": False,
                  "underTvangsavviklingEllerTvangsopplosning": True,
                  "tvangsopplostPgaManglendeRegnskapDato": "2026-06-04"},
    "933333333": {"navn": "AVVIKLING AS", "underAvvikling": True,
                  "underAvviklingDato": "2026-09-01"},
}
GONE = {"944444444": 410}          # deleted: left out of a search, 410 on its own
NAMES = {"Skanska Norge AS", "Seby AS", "1254-Låven Boligsameie", "Avvikling AS",
         "Borte AS", "Ola Nordmann", "Uten Nummer AS", "Dobbel AS"}


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


class _World:
    """Tripletex and the register, either of which can be down."""

    def __init__(self, register=REGISTER, tripletex_down=False, register_down=False):
        self.register, self.tripletex_down, self.register_down = register, tripletex_down, register_down
        self.searches = 0

    async def call(self, tool, args=None):
        assert tool == "search_customers"
        if self.tripletex_down:
            raise RuntimeError("Tripletex svarte ikke")
        self.searches += not args.get("isInactive")      # one read: active, then archived
        return {"rows": [] if args.get("isInactive") else CUSTOMERS}

    async def get(self, client, url, params=None):
        if self.register_down:
            return _Resp(503)
        if params:
            asked = params["organisasjonsnummer"].split(",")
            return _Resp(200, {"_embedded": {"enheter": [
                {"organisasjonsnummer": o, **self.register[o]} for o in asked
                if o in self.register]}})
        org = url.rsplit("/", 1)[1]
        if org in GONE:
            return _Resp(GONE[org], {"organisasjonsnummer": org, "slettedato": "2025-03-01"})
        return _Resp(404)


def _run(world, names=NAMES, today=TODAY):
    real = (brreg.mcp, brreg._get)
    brreg.mcp, brreg._get = world, world.get
    try:
        return asyncio.run(brreg.check(set(names), today))
    finally:
        brreg.mcp, brreg._get = real


def _kept():
    with db.read() as conn:
        return brreg._rows(conn, db.company_id())


def _fresh():
    _tmp.db()
    _tmp.store(company, "COMPANY_FILE")


# ------------------------------------------------------------- the check
def test_each_customer_gets_what_the_register_says():
    _fresh()
    out = _run(_World())
    kept = _kept()
    assert {n: r["status"] for n, r in kept.items()} == {
        "Skanska Norge AS": "ok", "Seby AS": "bankrupt", "1254-Låven Boligsameie": "forced",
        "Avvikling AS": "liquidation", "Borte AS": "deleted", "Ola Nordmann": "private",
        "Uten Nummer AS": "no_org", "Dobbel AS": "no_org"}
    assert kept["Skanska Norge AS"]["org_number"] == "943049467"
    assert kept["Seby AS"]["since"] == "2026-10-09"
    assert kept["1254-Låven Boligsameie"]["since"] == "2026-06-04"
    assert kept["Borte AS"]["since"] == "2025-03-01"
    assert out["at_risk"] == ["1254-Låven Boligsameie", "Avvikling AS", "Seby AS"]
    assert out["new_risk"] == out["at_risk"] and out["failed"] == []
    assert out["unclear"] == ["Borte AS"] and out["checked"] == 8


def test_the_customer_list_is_read_once_a_week_the_register_every_day():
    _fresh()
    world = _World()
    _run(world)
    _run(world, today=date(2026, 10, 13))
    assert world.searches == 1
    out = _run(world, today=date(2026, 10, 19))
    assert world.searches == 2 and out["new_risk"] == []


def test_the_register_down_keeps_the_last_status_and_says_so():
    _fresh()
    _run(_World())
    out = _run(_World(register_down=True), today=date(2026, 10, 13))
    kept = _kept()
    assert kept["Seby AS"]["status"] == "bankrupt"
    assert kept["Seby AS"]["checked_on"] == "2026-10-12" and kept["Seby AS"]["error"]
    assert out["failed"] and "503" in out["failed"][0]
    assert "Skanska Norge AS" in out["not_checked"]


def test_nothing_is_clean_until_the_register_has_said_so():
    _fresh()
    out = _run(_World(tripletex_down=True))
    kept = _kept()
    assert {r["status"] for r in kept.values()} == {"unchecked"}
    assert out["failed"] and len(out["not_checked"]) == len(NAMES)
    assert out["at_risk"] == []


def test_a_new_number_on_the_customer_card_forgets_the_old_status():
    _fresh()
    _run(_World())
    moved = dict(REGISTER, **{"911111111": {"navn": "SEBY AS"}})
    out = _run(_World(register=moved), today=date(2026, 10, 19))
    assert _kept()["Seby AS"]["status"] == "ok" and "Seby AS" not in out["at_risk"]


# ------------------------------------------------------------- what the others read
def test_a_card_per_customer_in_trouble_with_what_is_owed():
    _fresh()
    _run(_World())
    risky = brreg.at_risk()
    assert set(risky) == {"Seby AS", "1254-Låven Boligsameie", "Avvikling AS"}
    assert risky["Seby AS"]["excluded"] and not risky["Avvikling AS"]["excluded"]
    invoices = [{"name": "Seby AS", "amount": 57_056.0, "due": "2026-09-30", "number": 1101,
                 "register": risky["Seby AS"]},
                {"name": "Seby AS", "amount": 10_000.0, "due": "2026-11-15", "number": 1150,
                 "register": risky["Seby AS"]}]
    [card] = cards._from_register(invoices)
    assert card["key"] == "brreg:911111111" and card["amount"] == 67_056.0
    assert card["urgency"] == "high"
    assert card["title"] == "Seby AS er slått konkurs: 67 056 kr utestående"
    assert "fra 2026-10-09" in card["body"] and "1 av dem forfalt" in card["body"]
    assert "tatt ut av prognosen" in card["body"]
    links = [e["value"] for e in card["evidence"] if e["label"] == "Enhetsregisteret"]
    assert links == ["https://virksomhet.brreg.no/oppslag/enheter/911111111"]


def test_the_clean_up_list_names_what_could_not_be_checked():
    _fresh()
    _run(_World())
    ends = brreg.loose_ends(NAMES)
    assert ends["no_org"] == ["Dobbel AS", "Uten Nummer AS"]
    assert [u["name"] for u in ends["unclear"]] == ["Borte AS"]
    import health
    items = health.cleanup_items(None, {"register": ends})
    assert [i["id"] for i in items] == ["register_no_org", "register_1"]
    assert "Dobbel AS, Uten Nummer AS" in items[0]["funnet"]
    assert "slettet" in items[1]["funnet"] and "944444444" in items[1]["funnet"]


def test_a_bankrupt_customers_money_leaves_the_forecast():
    _fresh()
    _run(_World())
    ar = [{**_invoice(57_056.0, "2026-09-01", "2026-10-15", 1), "customerName": "Seby AS"},
          {**_invoice(40_000.0, "2026-09-01", "2026-10-15", 2), "customerName": "Avvikling AS"},
          {**_invoice(30_000.0, "2026-09-01", "2026-10-15", 3), "customerName": "Skanska Norge AS"}]
    data = _forecast([], ar=ar)
    paying = {i["name"] for i in data["ar_open"]}
    assert paying == {"Avvikling AS", "Skanska Norge AS"}
    assert round(sum(i["amount"] for i in _kinds(data, "ar"))) == 70_000
    assert {i["name"] for i in data["ar_at_risk"]} == {"Seby AS", "Avvikling AS"}
