#!/usr/bin/env python
"""Verify the Tripletex tokens on their own, before involving the agent.

    ./.venv/bin/python scripts/check_tokens.py

Prints who the tokens authenticate as and a live figure, or the exact failure.
"""
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import config  # noqa: E402
from tripletex import TripletexClient, TripletexError  # noqa: E402


async def main() -> int:
    consumer = config.TRIPLETEX_CONSUMER_TOKEN
    employee = config.TRIPLETEX_EMPLOYEE_TOKEN
    print(f"consumer token: {'set (' + str(len(consumer)) + ' chars)' if consumer else 'MISSING'}")
    print(f"employee token: {'set (' + str(len(employee)) + ' chars)' if employee else 'MISSING'}")
    if not employee:
        print("\n→ Sett TRIPLETEX_EMPLOYEE_TOKEN i .env først.")
        return 1
    if not consumer:
        print("\n→ TRIPLETEX_CONSUMER_TOKEN mangler. Tripletex' eneste autentisering er")
        print("  Basic auth med sesjonstoken, og sesjonstokenet krever begge halvdeler.")
        print("  Sjekk om Tripletex ga deg to tokens da du opprettet API-tilgangen.")
        return 1

    client = TripletexClient(consumer, employee)
    try:
        who = await client.whoami()
        print("\n✓ Sesjonstoken opprettet.")
        print(f"  Innlogget som : {who.get('firstName','?')} {who.get('lastName','')}".rstrip())
        print(f"  Selskap       : {(who.get('company') or {}).get('name', who.get('companyId','?'))}")

        today = date.today()
        pl = await client.profit_and_loss(f"{today.year}-01-01", today.isoformat())
        t = pl["totals"]
        print("\n✓ Live tall hentet (hittil i år):")
        print(f"  Driftsinntekter : {t['driftsinntekter']:>15,.0f}".replace(",", " "))
        print(f"  Driftsresultat  : {t['driftsresultat']:>15,.0f}".replace(",", " "))
        print(f"  Driftsmargin    : {t['driftsmargin_pct']:>15} %")
        print("\nAlt fungerer. Start appen med ./run.sh")
        return 0
    except TripletexError as exc:
        print(f"\n✗ {exc}")
        return 1
    finally:
        await client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
