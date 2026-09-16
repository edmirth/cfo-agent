#!/usr/bin/env python
"""Verifiser Tripletex-tilgangen isolert, før agenten involveres.

    ./.venv/bin/python scripts/check_tokens.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import httpx2 as httpx  # noqa: E402

import config  # noqa: E402
from tlx_oauth import OAuthError, tokens  # noqa: E402
from tripletex import TripletexClient, TripletexError  # noqa: E402


def _sse(body: str) -> dict:
    """The MCP endpoint answers as SSE; pull the JSON out of the data line."""
    if "data: " in body:
        body = next(l[6:] for l in body.splitlines() if l.startswith("data: "))
    return json.loads(body)


async def check_mcp() -> int:
    print("Modus: MCP over OAuth\n")
    print(f"client_id     : {config.TRIPLETEX_CLIENT_ID}")
    print(f"refresh token : {len(config.TRIPLETEX_REFRESH_TOKEN)} tegn")
    try:
        at = await tokens.access_token()
    except OAuthError as exc:
        print(f"\n✗ {exc}")
        return 1
    print(f"access token  : {len(at)} tegn  ✓ fornyet\n")

    h = {"Authorization": f"Bearer {at}",
         "Accept": "application/json, text/event-stream",
         "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(config.TRIPLETEX_MCP_URL + "/", headers=h, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "cfo-agent", "version": "0.1.0"}}})
        if r.status_code != 200:
            print(f"✗ MCP initialize svarte {r.status_code}: {r.text[:300]}")
            return 1
        info = _sse(r.text).get("result", {})
        print(f"✓ Tilkoblet {info.get('serverInfo', {}).get('name', 'MCP')}")

        sid = r.headers.get("mcp-session-id")
        if sid:
            h["mcp-session-id"] = sid
        await c.post(config.TRIPLETEX_MCP_URL + "/", headers=h,
                     json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        r2 = await c.post(config.TRIPLETEX_MCP_URL + "/", headers=h,
                          json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tl = _sse(r2.text).get("result", {}).get("tools", [])
        print(f"✓ {len(tl)} verktøy tilgjengelig")

        r3 = await c.post(config.TRIPLETEX_MCP_URL + "/", headers=h, json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "logged_in_user_info", "arguments": {}}})
        res = _sse(r3.text).get("result", {})
        text = " ".join(b.get("text", "") for b in res.get("content", []))[:200]
        print(f"✓ Live oppslag: {text.strip() or res}")

    print("\nAlt fungerer. Start appen med ./run.sh")
    return 0


async def check_rest() -> int:
    print("Modus: REST med consumer + employee token\n")
    client = TripletexClient(config.TRIPLETEX_CONSUMER_TOKEN, config.TRIPLETEX_EMPLOYEE_TOKEN)
    try:
        who = await client.whoami()
        print(f"✓ Innlogget som {who.get('firstName','?')} {who.get('lastName','')}".rstrip())
        from datetime import date
        today = date.today()
        pl = await client.profit_and_loss(f"{today.year}-01-01", today.isoformat())
        t = pl["totals"]
        print(f"  Driftsinntekter : {t['driftsinntekter']:>15,.0f}".replace(",", " "))
        print(f"  Driftsresultat  : {t['driftsresultat']:>15,.0f}".replace(",", " "))
        print("\nAlt fungerer. Start appen med ./run.sh")
        return 0
    except TripletexError as exc:
        print(f"✗ {exc}")
        return 1
    finally:
        await client.aclose()


async def main() -> int:
    if config.TRIPLETEX_CLIENT_ID and config.TRIPLETEX_REFRESH_TOKEN:
        return await check_mcp()
    if config.TRIPLETEX_CONSUMER_TOKEN and config.TRIPLETEX_EMPLOYEE_TOKEN:
        return await check_rest()

    print("Ingen fungerende Tripletex-tilgang er satt opp ennå.\n")
    print("Anbefalt vei — logg inn i nettleseren én gang:\n")
    print("    ./.venv/bin/python scripts/oauth_login.py\n")
    print("Den lagrer TRIPLETEX_CLIENT_ID og TRIPLETEX_REFRESH_TOKEN i .env.")
    print("Refresh-tokenet utløper ikke, så dette gjøres kun denne ene gangen.\n")
    have = []
    if config.TRIPLETEX_EMPLOYEE_TOKEN:
        have.append(f"TRIPLETEX_EMPLOYEE_TOKEN ({len(config.TRIPLETEX_EMPLOYEE_TOKEN)} tegn)")
    if config.TRIPLETEX_CONSUMER_TOKEN:
        have.append("TRIPLETEX_CONSUMER_TOKEN")
    print("I .env nå:", ", ".join(have) if have else "ingenting relevant")
    if config.TRIPLETEX_EMPLOYEE_TOKEN.startswith("tlxr_"):
        print("\nMerk: tlxr_-nøkkelen kan ikke brukes alene — den er et refresh token")
        print("bundet til en klient vi ikke kjenner. oauth_login.py lager et vi eier.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
