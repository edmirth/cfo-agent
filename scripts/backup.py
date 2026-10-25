#!/usr/bin/env python
"""Sikkerhetskopien for hånd: lag en nøkkel, ta en kopi nå, eller åpne en kopi.

    ./.venv/bin/python scripts/backup.py key
        En ny CFO_BACKUP_KEY. Legg den i Renders innstillinger og i en
        passordbehandler: uten den kan kopiene utenfor serveren ikke åpnes.

    ./.venv/bin/python scripts/backup.py now
        Tar en kopi nå, som nattjobben gjør, og sender den ut hvis det er satt opp.

    ./.venv/bin/python scripts/backup.py open <kopi.tar.gz[.enc]> <ny mappe>
        Pakker ut en kopi, kryptert eller ikke, i en tom mappe. Selve
        tilbakeføringen er beskrevet i docs/hosting.md.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def main(argv: list[str]) -> int:
    if argv[:1] == ["key"]:
        from cryptography.fernet import Fernet
        print(Fernet.generate_key().decode())
        return 0

    import backup  # noqa: E402 — after the path, and only when it is needed

    if argv[:1] == ["now"]:
        copy = backup.make()
        print(f"✓ På disken: {copy}")
        if backup.offsite_configured():
            out = asyncio.run(backup.upload(copy))
            print(f"✓ Utenfor serveren: {out['object']}")
        else:
            print("· Ikke sendt ut: CFO_BACKUP_KEY og SUPABASE_SERVICE_KEY er ikke satt.")
        return 0

    if argv[:1] == ["open"] and len(argv) == 3:
        try:
            names = backup.open_copy(Path(argv[1]), Path(argv[2]))
        except backup.BackupError as exc:
            print(f"! {exc}")
            return 1
        print(f"✓ Pakket ut i {argv[2]}: {', '.join(names)}")
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
