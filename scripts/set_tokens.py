#!/usr/bin/env python
"""Skriv nøkler til .env uten at de vises på skjermen eller havner i historikken.

    ./.venv/bin/python scripts/set_tokens.py

Trykk Enter for å beholde det som allerede står der.
"""
import re
from getpass import getpass
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"
EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"

FIELDS = [
    ("ANTHROPIC_API_KEY", "Anthropic API-nøkkel (sk-ant-...)", True),
    ("TRIPLETEX_CONSUMER_TOKEN", "Tripletex consumer token (blank hvis du bare fikk én nøkkel)", False),
    ("TRIPLETEX_EMPLOYEE_TOKEN", "Tripletex employee token / API-nøkkel", True),
]


def read_env() -> str:
    if ENV.exists():
        return ENV.read_text()
    return EXAMPLE.read_text() if EXAMPLE.exists() else ""


def set_key(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(line, text)
    return text.rstrip("\n") + f"\n{line}\n"


def main() -> int:
    text = read_env()
    print(f"Skriver til {ENV}")
    print("Verdiene vises ikke mens du skriver. Enter = behold nåværende.\n")

    for key, label, required in FIELDS:
        current = ""
        m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.MULTILINE)
        if m:
            current = m.group(1).strip()
        state = f"satt, {len(current)} tegn" if current else "ikke satt"
        value = getpass(f"{label}\n  [{state}] > ").strip()
        if value:
            text = set_key(text, key, value)
            print(f"  ✓ {key} lagret ({len(value)} tegn)\n")
        elif current:
            print(f"  · {key} uendret\n")
        elif required:
            print(f"  ! {key} står tom — appen vil ikke fungere før den er satt\n")
        else:
            print(f"  · {key} står tom\n")

    ENV.write_text(text)
    ENV.chmod(0o600)
    print(f"Lagret. Rettigheter satt til 600 (kun du kan lese filen).")
    print("\nNeste: ./.venv/bin/python scripts/check_tokens.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
