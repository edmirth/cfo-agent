#!/usr/bin/env python
"""Verifiser Tripletex-tilgangen isolert, før agenten involveres.

    ./.venv/bin/python scripts/check_tokens.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import config  # noqa: E402
from mcp_client import McpError, mcp  # noqa: E402
from tlx_oauth import OAuthError, tokens  # noqa: E402


async def main() -> int:
    if not (config.TRIPLETEX_CLIENT_ID and config.TRIPLETEX_REFRESH_TOKEN):
        print("Tripletex er ikke satt opp ennå.\n")
        print("Logg inn i nettleseren én gang:\n")
        print("    ./.venv/bin/python scripts/oauth_login.py\n")
        print("Den lagrer TRIPLETEX_CLIENT_ID og TRIPLETEX_REFRESH_TOKEN i .env.")
        print("Refresh-tokenet utløper ikke, så dette gjøres kun denne ene gangen.")
        return 1

    print(f"client_id     : {config.TRIPLETEX_CLIENT_ID}")
    print(f"refresh token : {len(config.TRIPLETEX_REFRESH_TOKEN)} tegn")
    try:
        at = await tokens.access_token()
    except OAuthError as exc:
        print(f"\n✗ {exc}")
        return 1
    print(f"access token  : {len(at)} tegn  ✓ fornyet\n")

    try:
        who = await mcp.call("logged_in_user_info")
        name = f"{who.get('firstName', '')} {who.get('lastName', '')}".strip()
        print(f"✓ Tilkoblet Tripletex som {name or 'ukjent bruker'}")
        print(f"  Selskap: {who.get('companyName', '?')}")

        from datetime import date
        today = date.today()
        rep = await mcp.call("fetch_report", {
            "report_name": "Resultatrapport",
            "period_start": f"{today.year}-01-01", "period_end": today.isoformat()})
        rows = rep.get("table", {}).get("rows", [])
        for path, tag in (("Driftsresultat > Driftsinntekter", "Driftsinntekter"),
                          ("Driftsresultat", "Driftsresultat")):
            row = next((r for r in rows if r.get("path") == path), None)
            if row and row.get("cells"):
                print(f"  {tag:<16}: {row['cells'][0]:>14,.0f}".replace(",", " "))
    except McpError as exc:
        print(f"\n✗ {exc}")
        return 1
    finally:
        await mcp.aclose()

    print("\nAlt fungerer. Start appen med ./run.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
