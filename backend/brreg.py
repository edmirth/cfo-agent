"""Customers in trouble, from Brønnøysund.

Enhetsregisteret is one of the playbook's three MVP sources — free, open, no
key — and a customer gone bankrupt is the "at-risk customer" the Cash tier is
meant to catch. Every working morning, each customer with money owing is read
against the register:

- **bankrupt** (`konkurs`) and **forced dissolution**
  (`underTvangsavviklingEllerTvangsopplosning`) — the money is not coming, or
  not in time. A card with the amount at risk, and the invoices are taken out
  of the forecast (`cashflow.build`, through `at_risk`).
- **liquidation** (`underAvvikling`) — a voluntary winding-up, which usually
  pays its debts, but only to those who report their claim in time. A card;
  the invoices stay in the forecast.
- **deleted** or **not found** — usually a merger or a wrong number on the
  customer card, not a risk. Not a card: a point on the regnskapsfører's
  clean-up list, with the customers that have no organisation number at all.

The invoices carry the customer's name and nothing else, so the organisation
number is matched from Tripletex's customer list, re-read about once a week.
Private persons have none and are not looked for.

**A failed lookup is not a clean one.** The register not answering, or the
customer list not loading, keeps the status the customer last had and records
why; the morning run says the check was partial. Nothing is ever set to "ok"
without the register having said so.
"""
import asyncio
import logging
import re
from datetime import date, timedelta

import httpx2 as httpx

import config
import db
from mcp_client import mcp

log = logging.getLogger("cfo.brreg")

API = "https://data.brreg.no/enhetsregisteret/api/enheter"
PAGE = "https://virksomhet.brreg.no/oppslag/enheter/{org}"
TIMEOUT_S = 20
BATCH = 100                      # the register's page size for one lookup
MATCH_EVERY_DAYS = 7             # how stale the organisation numbers may get
CUSTOMER_PAGES = 30              # 3 000 customers; past that, say so

# The statuses worth a card, worst first, and how the card says it.
RISK = {"bankrupt": "er slått konkurs",
        "forced": "er under tvangsavvikling",
        "liquidation": "er under avvikling"}
# The money is not counted on: out of the forecast.
EXCLUDED = {"bankrupt", "forced"}
# Not a risk, but not a check either: for the clean-up list.
UNCLEAR = {"deleted": "står som slettet i Enhetsregisteret",
           "not_found": "finnes ikke i Enhetsregisteret"}


class RegisterError(RuntimeError):
    """The register did not answer."""


# ------------------------------------------------------------- reading
def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def _org(text) -> str | None:
    digits = re.sub(r"\D", "", str(text or ""))
    return digits if len(digits) == 9 else None


async def _customers() -> dict[str, list[dict]]:
    """Tripletex's customers, active and archived, by normalised name.

    Archived too: a customer gone bankrupt is often archived while its
    invoices are still open.
    """
    out: dict[str, list[dict]] = {}
    for inactive in (False, True):
        for page in range(CUSTOMER_PAGES):
            r = await mcp.call("search_customers", {"count": 100, "from": page * 100,
                                                    "isInactive": inactive})
            rows = r.get("rows") or r.get("customers") or r.get("values") or []
            for row in rows:
                out.setdefault(_norm(row.get("name") or ""), []).append({
                    "org": _org(row.get("organizationNumber") or row.get("orgNumber")),
                    "private": bool(row.get("isPrivateIndividual"))})
            if len(rows) < 100:
                break
        else:
            log.warning("Kundelisten er lengre enn %d sider; resten ble ikke lest",
                        CUSTOMER_PAGES)
    return out


def _match(name: str, customers: dict[str, list[dict]]) -> dict | None:
    """The customer behind an invoice's name; None when there is none, or more
    than one with different numbers."""
    found = customers.get(_norm(name))
    if not found:
        # "1254-Låven Boligsameie": a customer number in front of the name.
        bare = re.sub(r"^\d+\s*[-–]\s*", "", name or "")
        found = customers.get(_norm(bare)) if bare != name else None
    if not found:
        return None
    orgs = {c["org"] for c in found if c["org"]}
    if len(orgs) > 1:
        return None
    return {"org": next(iter(orgs), None), "private": all(c["private"] for c in found)}


def status_of(entity: dict) -> tuple[str, str | None]:
    """(status, since) from one entry in the register."""
    if entity.get("konkurs"):
        return "bankrupt", entity.get("konkursdato")
    if entity.get("underTvangsavviklingEllerTvangsopplosning"):
        since = next((v for k, v in sorted(entity.items())
                      if k.startswith("tvangs") and k.endswith("Dato") and v), None)
        return "forced", since
    if entity.get("underAvvikling"):
        return "liquidation", entity.get("underAvviklingDato")
    if entity.get("slettedato"):
        return "deleted", entity["slettedato"]
    return "ok", None


async def _get(client, url: str, params: dict | None = None):
    return await client.get(url, params=params)


async def lookup(orgs: list[str]) -> dict[str, dict]:
    """The register's answer for each number: {status, since, name}.

    One request per hundred; a number missing from the answer is asked for on
    its own, since a deleted entity (410) and one that never was (404) are
    left out of a search alike. Raises RegisterError if the register cannot be
    read at all.
    """
    if config.DEMO:
        return {}
    out: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            for i in range(0, len(orgs), BATCH):
                chunk = orgs[i:i + BATCH]
                r = await _get(client, API, {"organisasjonsnummer": ",".join(chunk),
                                             "size": BATCH})
                if r.status_code != 200:
                    raise RegisterError(f"Enhetsregisteret svarte {r.status_code}")
                for e in (r.json().get("_embedded") or {}).get("enheter") or []:
                    st, since = status_of(e)
                    out[e["organisasjonsnummer"]] = {"status": st, "since": since,
                                                     "name": e.get("navn")}
                for org in chunk:
                    if org in out:
                        continue
                    one = await _get(client, f"{API}/{org}")
                    if one.status_code == 410:
                        body = _json(one)
                        out[org] = {"status": "deleted", "since": body.get("slettedato"),
                                    "name": body.get("navn")}
                    elif one.status_code == 404:
                        out[org] = {"status": "not_found", "since": None, "name": None}
                    elif one.status_code == 200:
                        e = _json(one)
                        st, since = status_of(e)
                        out[org] = {"status": st, "since": since, "name": e.get("navn")}
                    else:
                        raise RegisterError(f"Enhetsregisteret svarte {one.status_code} "
                                            f"for {org}")
    except httpx.HTTPError as exc:
        raise RegisterError(f"Enhetsregisteret kunne ikke nås ({exc.__class__.__name__})") from exc
    return out


def _json(r) -> dict:
    try:
        return r.json() or {}
    except ValueError:
        return {}


# ------------------------------------------------------------- the check
def _rows(conn, cid: int) -> dict[str, dict]:
    return {r["name"]: dict(r) for r in conn.execute(
        "SELECT * FROM brreg_checks WHERE company_id = ?", (cid,))}


async def check(names: set[str], today: date | None = None) -> dict:
    """Read every customer in `names` against the register, and keep it.

    Returns what was found: the customers at risk (and which are new today),
    the unclear ones, those not checked, and what failed.
    """
    today = today or date.today()
    if config.DEMO:
        # The demo's customers are invented; the register knows none of them.
        return {"customers": len(names), "checked": 0, "at_risk": [], "new_risk": [],
                "unclear": [], "no_org": [], "not_checked": [], "failed": []}
    names = {n for n in names if n}
    cid = db.company_id()
    with db.read() as conn:
        known = _rows(conn, cid)
    failed: list[str] = []

    # 1. Organisation numbers, from the customer list when any is stale.
    stale_before = (today - timedelta(days=MATCH_EVERY_DAYS)).isoformat()
    if any(not (known.get(n) or {}).get("matched_on")
           or known[n]["matched_on"] <= stale_before for n in names):
        try:
            customers = await _customers()
        except Exception as exc:  # noqa: BLE001
            log.warning("Kundelisten kunne ikke hentes: %s", exc)
            failed.append(f"Kundelisten i Tripletex kunne ikke hentes ({exc}), så "
                          f"organisasjonsnumrene er ikke oppdatert.")
            customers = None
        if customers is not None:
            for n in names:
                m = _match(n, customers) or {"org": None, "private": False}
                row = known.setdefault(n, {"name": n, "status": "unchecked"})
                if row.get("org_number") != m["org"]:
                    row.update(status="unchecked", since=None, register_name=None,
                               checked_on=None)
                row.update(org_number=m["org"], private=int(m["private"]),
                           matched_on=today.isoformat())

    # 2. The register, for every customer with a number.
    rows = {n: known.setdefault(n, {"name": n, "status": "unchecked"}) for n in names}
    before = {n: r.get("status") for n, r in rows.items()}
    for r in rows.values():
        if not r.get("org_number") and r.get("matched_on"):
            r.update(status="private" if r.get("private") else "no_org", since=None,
                     register_name=None, checked_on=today.isoformat(), error=None)
    orgs = sorted({r["org_number"] for r in rows.values() if r.get("org_number")})
    answers: dict[str, dict] = {}
    if orgs:
        try:
            answers = await lookup(orgs)
        except RegisterError as exc:
            log.warning("Enhetsregisteret: %s", exc)
            failed.append(f"{exc}. Kundene har den statusen de hadde sist.")
    for r in rows.values():
        org = r.get("org_number")
        if not org:
            if not r.get("matched_on"):
                r["error"] = "Organisasjonsnummeret er ikke funnet ennå."
            continue
        a = answers.get(org)
        if a is None:
            r["error"] = failed[-1] if failed else "Ikke besvart."
            continue
        r.update(status=a["status"], since=a["since"], register_name=a["name"],
                 checked_on=today.isoformat(), error=None)

    with db.tx() as conn:
        for r in rows.values():
            conn.execute(
                "INSERT INTO brreg_checks (company_id, name, org_number, private, "
                "matched_on, status, since, register_name, checked_on, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (company_id, name) DO UPDATE SET org_number = excluded.org_number, "
                "private = excluded.private, matched_on = excluded.matched_on, "
                "status = excluded.status, since = excluded.since, "
                "register_name = excluded.register_name, checked_on = excluded.checked_on, "
                "error = excluded.error",
                (cid, r["name"], r.get("org_number"), int(r.get("private") or 0),
                 r.get("matched_on"), r.get("status") or "unchecked", r.get("since"),
                 r.get("register_name"), r.get("checked_on"), r.get("error")))

    at_risk = sorted(n for n, r in rows.items() if r["status"] in RISK)
    return {"customers": len(rows),
            "checked": sum(1 for r in rows.values()
                           if r.get("checked_on") == today.isoformat() and not r.get("error")),
            "at_risk": at_risk,
            "new_risk": [n for n in at_risk if before.get(n) != rows[n]["status"]],
            "unclear": sorted(n for n, r in rows.items() if r["status"] in UNCLEAR),
            "no_org": sorted(n for n, r in rows.items() if r["status"] == "no_org"),
            "not_checked": sorted(n for n, r in rows.items() if r.get("error")),
            "failed": failed}


# ------------------------------------------------------------- what the others read
def _entry(r) -> dict:
    return {"org": r["org_number"], "status": r["status"], "since": r["since"],
            "register_name": r["register_name"], "checked_on": r["checked_on"],
            "error": r["error"], "excluded": r["status"] in EXCLUDED,
            "said": RISK.get(r["status"]) or UNCLEAR.get(r["status"]) or "",
            "url": PAGE.format(org=r["org_number"]) if r["org_number"] else ""}


def at_risk() -> dict[str, dict]:
    """Customers the register last had in trouble, by name. Never raises: a
    forecast is not to fail because this table could not be read."""
    try:
        with db.read() as conn:
            return {r["name"]: _entry(r) for r in conn.execute(
                "SELECT * FROM brreg_checks WHERE company_id = ? AND status IN "
                f"({','.join('?' * len(RISK))})", (db.company_id(), *RISK))}
    except Exception as exc:  # noqa: BLE001
        log.warning("Brønnøysund-statusene kunne ikke leses: %s", exc)
        return {}


def loose_ends(names: set[str] | None = None) -> dict:
    """For the clean-up list: customers with money owing that could not be
    checked because of something in the books."""
    try:
        with db.read() as conn:
            rows = [r for r in conn.execute(
                "SELECT * FROM brreg_checks WHERE company_id = ? "
                "AND status IN ('no_org', 'deleted', 'not_found') ORDER BY name",
                (db.company_id(),)) if names is None or r["name"] in names]
    except Exception as exc:  # noqa: BLE001
        log.warning("Brønnøysund-statusene kunne ikke leses: %s", exc)
        return {"no_org": [], "unclear": []}
    return {"no_org": [r["name"] for r in rows if r["status"] == "no_org"],
            "unclear": [{"name": r["name"], **_entry(r)} for r in rows
                        if r["status"] in UNCLEAR]}
