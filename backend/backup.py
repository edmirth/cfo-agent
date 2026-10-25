"""The nightly backup (card 51).

What only this product knows — the forecasts kept, the cards, what the CEO
decided — is in `cfo.db` and a few files beside it, on one disk. Every night a
copy of them is packed into one file in `state/backups/`, and the last
`KEEP` nights are kept there. That covers a bad deploy or a row deleted by
mistake. It does not cover losing the disk or the host, so the same file is
also encrypted and sent to Supabase Storage, outside the host, where the last
`KEEP` are kept too.

**What is in it.** `cfo.db`, copied through SQLite's own backup so it is whole
while the server writes, and checked before it is kept. The rulebook
(`company.md`), the KPI definitions, the industry profile and the front-page
summary. Not the Tripletex token: it rotates, so a copy of it is stale by the
next renewal and only a risk.

**Encrypted before it leaves.** With `CFO_BACKUP_KEY`, which lives in the
host's settings and nowhere near the copy. Supabase holds a file it cannot
read; whoever restores needs the key. Lose the key and the copies outside the
host are lost with it, so keep it in a password manager too.

Restoring is by hand, on purpose: `docs/hosting.md`, «Restoring a backup».
"""
import logging
import os
import re
import sqlite3
import tarfile
import tempfile
from datetime import date
from pathlib import Path

import httpx2 as httpx

import config
import db

log = logging.getLogger("cfo.backup")

KEEP = 14
# Where the copies go and what they are taken from. The tests point both at
# throwaway folders.
DIR = config.STATE / "backups"
SOURCE = config.STATE
FILES = ("company.md", "definitions.json", "profile.json", "summary.json")
NAME = re.compile(r"^(?P<company>[a-z0-9-]+)-(?P<day>\d{4}-\d{2}-\d{2})\.tar\.gz$")


class BackupError(RuntimeError):
    """The backup did not happen. The message is the sentence for the front page."""


def company_slug() -> str:
    """The company in a file name: «Lindeskar Renhold AS» → lindeskar-renhold-as."""
    name = (config.DEMO or config.COMPANY_NAME or "selskapet").lower()
    for a, b in (("æ", "ae"), ("ø", "o"), ("å", "a")):
        name = name.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-") or "selskapet"


# ------------------------------------------------------------- on the disk
def make(today: date | None = None) -> Path:
    """Pack tonight's copy into DIR and drop the oldest beyond KEEP."""
    today = today or date.today()
    DIR.mkdir(parents=True, exist_ok=True)
    target = DIR / f"{company_slug()}-{today.isoformat()}.tar.gz"
    with tempfile.TemporaryDirectory(dir=DIR) as tmp:
        copy = Path(tmp) / "cfo.db"
        db.copy_to(copy)
        conn = sqlite3.connect(copy)
        try:
            verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        if verdict != "ok":
            raise BackupError(f"Kopien av databasen var skadet ({verdict}), "
                              f"så den ble ikke lagret.")
        packed = Path(tmp) / target.name
        with tarfile.open(packed, "w:gz") as tar:
            tar.add(copy, "cfo.db")
            for name in FILES:
                if (SOURCE / name).exists():
                    tar.add(SOURCE / name, name)
        os.chmod(packed, 0o600)
        os.replace(packed, target)
    prune()
    log.info("Sikkerhetskopi lagret: %s (%d kB)", target.name, target.stat().st_size // 1024)
    return target


def kept() -> list[Path]:
    """The copies on the disk, oldest first."""
    if not DIR.exists():
        return []
    return sorted((p for p in DIR.iterdir() if NAME.match(p.name)),
                  key=lambda p: NAME.match(p.name)["day"])


def prune() -> list[Path]:
    old = kept()[:-KEEP]
    for p in old:
        p.unlink(missing_ok=True)
    return old


# ------------------------------------------------------- outside the host
def offsite_configured() -> bool:
    return bool(config.BACKUP_KEY and config.BACKUP_SUPABASE_URL
                and config.BACKUP_SUPABASE_KEY)


def _fernet():
    from cryptography.fernet import Fernet
    try:
        return Fernet(config.BACKUP_KEY.encode())
    except ValueError as exc:
        raise BackupError("CFO_BACKUP_KEY er ikke en gyldig nøkkel. Lag en ny med "
                          "scripts/backup.py key.") from exc


def encrypt(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt(data: bytes) -> bytes:
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(data)
    except InvalidToken as exc:
        raise BackupError("Feil nøkkel, eller fila er skadet.") from exc


def _storage(path: str) -> str:
    return f"{config.BACKUP_SUPABASE_URL}/storage/v1/{path}"


def _headers() -> dict:
    key = config.BACKUP_SUPABASE_KEY
    return {"Authorization": f"Bearer {key}", "apikey": key}


async def upload(copy: Path) -> dict:
    """Send one copy, encrypted, and drop the oldest there beyond KEEP."""
    bucket, prefix = config.BACKUP_BUCKET, company_slug()
    name = f"{copy.name}.enc"
    body = encrypt(copy.read_bytes())
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(_storage(f"object/{bucket}/{prefix}/{name}"), content=body,
                         headers={**_headers(), "x-upsert": "true",
                                  "Content-Type": "application/octet-stream"})
        if r.status_code not in (200, 201):
            raise BackupError(f"Supabase tok ikke imot kopien ({r.status_code}: "
                              f"{r.text[:200]}).")
        listed = await c.post(_storage(f"object/list/{bucket}"), headers=_headers(),
                              json={"prefix": prefix, "limit": 1000,
                                    "sortBy": {"column": "name", "order": "asc"}})
        dropped = []
        if listed.status_code == 200:
            names = sorted(o["name"] for o in listed.json()
                           if NAME.match(o.get("name", "").removesuffix(".enc")))
            dropped = names[:-KEEP]
            if dropped:
                await c.request("DELETE", _storage(f"object/{bucket}"), headers=_headers(),
                                json={"prefixes": [f"{prefix}/{n}" for n in dropped]})
        else:
            # The copy is there; only the clean-up failed. Said, not raised.
            log.warning("Kunne ikke liste kopiene i Supabase (%s)", listed.status_code)
    log.info("Sikkerhetskopi sendt til Supabase: %s/%s", prefix, name)
    return {"object": f"{bucket}/{prefix}/{name}", "bytes": len(body), "dropped": len(dropped)}


# ------------------------------------------------------------ restoring
def open_copy(path: Path, into: Path) -> list[str]:
    """Unpack a copy (encrypted or not) into an empty folder. Returns what it held."""
    if into.exists() and any(into.iterdir()):
        raise BackupError(f"{into} er ikke tom. Pakk ut i en ny mappe.")
    into.mkdir(parents=True, exist_ok=True)
    data = path.read_bytes()
    if path.name.endswith(".enc"):
        data = decrypt(data)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as f:
        f.write(data)
        f.flush()
        with tarfile.open(f.name, "r:gz") as tar:
            names = tar.getnames()
            tar.extractall(into, filter="data")
    return names
