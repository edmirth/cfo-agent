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

**Restoring** is a copy put in `state/restore/` and a restart: at start-up,
before anything opens the database, the server checks the copy, moves what
is there now aside into `state/before-restore-<time>/`, and puts the copy in
its place. Swapping `cfo.db` under a running server would corrupt it; this
way nothing has it open. `docs/hosting.md`, «Restoring a backup».
"""
import logging
import os
import re
import sqlite3
import tarfile
import shutil
import tempfile
from datetime import date, datetime
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
        raise BackupError("CFO_BACKUP_KEY er ikke en gyldig nøkkel: tom, kuttet, eller "
                          "med mellomrom eller anførselstegn rundt. Lim inn nøkkelen "
                          "fra passordbehandleren på nytt. (En ny nøkkel fra "
                          "scripts/backup.py key åpner ikke kopier som alt er laget.)") from exc


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


async def remote() -> list[str]:
    """The copies outside the host for this company, oldest first."""
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(_storage(f"object/list/{config.BACKUP_BUCKET}"), headers=_headers(),
                         json={"prefix": company_slug(), "limit": 1000,
                               "sortBy": {"column": "name", "order": "asc"}})
    if r.status_code != 200:
        raise BackupError(f"Supabase svarte {r.status_code}: {r.text[:200]}")
    return sorted(o["name"] for o in r.json()
                  if NAME.match(o.get("name", "").removesuffix(".enc")))


async def fetch(name: str, into: Path) -> Path:
    """Fetch one copy from outside the host into `into`, still encrypted."""
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get(_storage(f"object/{config.BACKUP_BUCKET}/{company_slug()}/{name}"),
                        headers=_headers())
    if r.status_code != 200:
        # Supabase answers 400 for a file that is not there as well as for a
        # wrong key, so say where it looked: a COMPANY_NAME that differs from
        # the one the copy was made under looks in another folder.
        raise BackupError(
            f"Fant ikke {name} i Supabase, i mappa «{company_slug()}/» i bøtta "
            f"«{config.BACKUP_BUCKET}» ({r.status_code}: {r.text[:120]}). Mappa kommer "
            f"fra COMPANY_NAME («{config.COMPANY_NAME}»); den må være den samme som "
            f"da kopien ble laget. «scripts/backup.py list» viser hva som ligger der.")
    into.mkdir(parents=True, exist_ok=True)
    target = into / name
    target.write_bytes(r.content)
    return target


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


def restore_pending() -> str | None:
    """Put a copy waiting in `state/restore/` in place. Called at start-up,
    after the server lock and before anything opens the database.

    Returns the copy's name, or None when there is nothing to restore. A copy
    that will not open or check out is left where it is and the server starts
    on what it has: a failed restore must not cost the data that is there.
    """
    inbox = SOURCE / "restore"
    waiting = sorted(p for p in inbox.iterdir()
                     if p.name.endswith((".tar.gz", ".tar.gz.enc"))) if inbox.exists() else []
    if not waiting:
        return None
    if len(waiting) > 1:
        log.error("Mer enn én kopi i %s; legg bare den som skal tilbake der. "
                  "Ingenting ble tilbakeført.", inbox)
        return None
    copy = waiting[0]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    unpacked = SOURCE / f".restoring-{stamp}"
    try:
        open_copy(copy, unpacked)
        conn = sqlite3.connect(unpacked / "cfo.db")
        try:
            verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        if verdict != "ok":
            raise BackupError(f"databasen i kopien er skadet ({verdict})")
    except Exception as exc:  # noqa: BLE001 — start on what is there instead
        shutil.rmtree(unpacked, ignore_errors=True)
        log.error("Kunne ikke tilbakeføre %s: %s. Serveren starter på dataene "
                  "den har.", copy.name, exc)
        return None

    aside = SOURCE / f"before-restore-{stamp}"
    aside.mkdir()
    for current in [db.PATH, db.PATH.with_name(db.PATH.name + "-wal"),
                    db.PATH.with_name(db.PATH.name + "-shm"),
                    *(SOURCE / name for name in FILES)]:
        if current.exists():
            os.replace(current, aside / current.name)
    for restored in unpacked.iterdir():
        target = db.PATH if restored.name == "cfo.db" else SOURCE / restored.name
        os.replace(restored, target)
    unpacked.rmdir()
    os.replace(copy, aside / copy.name)       # so the next restart does not do it again
    log.warning("Tilbakeført fra %s. Det som lå der før, er flyttet til %s.",
                copy.name, aside.name)
    return copy.name
