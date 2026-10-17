"""Demo mode: whole books for made-up companies, and no way to the real ones.

The books are checked as a bookkeeper would: every voucher balances, and the
receivables and payables accounts equal the open invoices and bills behind
them. Each company is then run through the real engine in a process of its
own (config is read at import), with every network connection refused, so a
passing story is also proof that demo mode never reaches Tripletex.
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from demo import books as bk
from demo.companies import SPECS
from demo.tripletex import FakeTripletex

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 18)


def test_every_voucher_balances_and_the_subledgers_tie():
    for spec in SPECS.values():
        b = bk.generate(spec, TODAY)
        by_voucher: dict[int, float] = {}
        for p in b.postings:
            by_voucher[p.voucher] = by_voucher.get(p.voucher, 0.0) + p.amount
        assert all(abs(v) < 0.01 for v in by_voucher.values()), spec.slug
        open_ar = sum(i.gross for i in b.invoices if i.paid is None)
        open_ap = sum(x.gross for x in b.bills if x.paid is None)
        assert abs(b.balance(1500, TODAY) - open_ar) < 1, spec.slug
        assert abs(b.balance(2400, TODAY) + open_ap) < 1, spec.slug
        assert max(p.date for p in b.postings) < TODAY, spec.slug


def test_the_same_company_tells_the_same_story():
    a, b = bk.generate(SPECS["lindeskar"], TODAY), bk.generate(SPECS["lindeskar"], TODAY)
    assert [(p.date, p.account, p.amount) for p in a.postings] == \
           [(p.date, p.account, p.amount) for p in b.postings]


def test_no_organisation_number_is_a_valid_one():
    def mod11(n):
        s = sum(int(d) * w for d, w in zip(n[:8], [3, 2, 7, 6, 5, 4, 3, 2]))
        r = 11 - s % 11
        return (0 if r == 11 else r) == int(n[8])
    numbers = [s.orgnr for s in SPECS.values()] + \
              [c.org for s in SPECS.values() for c in s.customers if c.org]
    assert numbers and not [n for n in numbers if mod11(n)]


def test_a_tool_the_demo_does_not_have_is_refused():
    import asyncio
    fake = FakeTripletex(SPECS["aslefjord"])
    try:
        asyncio.run(fake.call("create_employee", {}))
    except Exception as e:
        assert "not found" in str(e)
    else:
        raise AssertionError("an unknown tool answered")


# ------------------------------------------- the engine, in a process of its own
PROBE = r"""
import asyncio, json, socket, sys
sys.path.insert(0, "backend")
def refuse(*a, **k):
    raise OSError("network refused in demo test")
socket.create_connection = refuse
socket.socket.connect = lambda self, *a: refuse()
import os, config, mcp_client, brreg, cashflow, overview, preflight, cards, brief
from tlx_oauth import tokens
out = {"state": str(config.STATE), "client": type(mcp_client.mcp).__name__,
       "mail": bool(config.RESEND_API_KEY), "company": config.COMPANY_NAME}
async def main():
    try:
        await tokens.access_token(); out["token"] = "issued"
    except Exception as e:
        out["token"] = "refused"
    out["brreg"] = await brreg.lookup(["999999999"])
    cf = await cashflow.build()
    out["negative"] = (cf.get("goes_negative_committed") or {}).get("label")
    out["low"] = cf["low_committed"]["amount"]
    out["light"] = brief.light(cf, float(os.environ["DEMO_FLOOR"])).colour
    out["kpis"] = (await overview.build())["kpis"]
    out["preflight"] = (await preflight.build())["condition"]
    deck = await cards.refresh()
    out["cards"] = [c["title"] for c in deck["open"]]
asyncio.run(main())
print("RESULT " + json.dumps(out, ensure_ascii=False, default=str))
"""


# The floor each company's company.md sets.
FLOORS = {"lindeskar": 2_000_000, "kvarnheim": 1_500_000, "aslefjord": 2_000_000}


def _run(slug: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / slug
        state.mkdir()
        (state / "company.md").write_text(SPECS[slug].company_md, encoding="utf-8")
        env = {**os.environ, "CFO_DEMO": slug, "CFO_STATE": str(state),
               "CFO_DB": str(Path(tmp) / "demo.db"), "CFO_AUTH": "off", "CFO_SCHEDULER": "off",
               "DEMO_FLOOR": str(FLOORS[slug])}
        r = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=300)
        line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT ")), None)
        assert line, r.stderr[-2000:]
        out = json.loads(line[7:])
        assert out["state"] == str(state)
        return out


def test_demo_mode_cannot_reach_the_real_ledger():
    out = _run("aslefjord")
    assert out["client"] == "FakeTripletex"
    assert out["token"] == "refused" and out["brreg"] == {} and not out["mail"]
    assert out["company"] == "Aslefjord Byggvare AS"


def test_lindeskar_is_a_yellow_week_with_one_late_customer():
    out = _run("lindeskar")
    assert any("Sjøgløtt Eiendom AS" in t and "etterskudd" in t for t in out["cards"])
    assert out["light"] == "yellow"
    assert out["negative"] is None and out["low"] < 2_000_000
    assert out["kpis"]["lonnsandel_pct"] > 75


def test_kvarnheim_runs_dry_unless_the_developer_pays():
    out = _run("kvarnheim")
    assert out["light"] == "red" and out["negative"]
    assert any("Ospelia Utvikling AS" in t for t in out["cards"])


def test_aslefjord_is_a_quiet_week():
    out = _run("aslefjord")
    assert out["light"] == "green"
    assert out["cards"] == [] and out["preflight"] == "clean"
    assert out["low"] > 2_000_000
