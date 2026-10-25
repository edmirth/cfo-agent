"""The nightly backup: whole, kept for 14 nights, and unreadable outside the host."""
import asyncio
import sqlite3
import tarfile
import tempfile
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from cryptography.fernet import Fernet

import backup
import config
import db
import scheduler


@contextmanager
def _folders(key: str = ""):
    saved = backup.DIR, backup.SOURCE, config.BACKUP_KEY
    root = Path(tempfile.mkdtemp())
    backup.DIR, backup.SOURCE = root / "backups", root
    config.BACKUP_KEY = key
    (root / "company.md").write_text("---\nkontantgulv: 500000\n---\n", encoding="utf-8")
    try:
        yield root
    finally:
        backup.DIR, backup.SOURCE, config.BACKUP_KEY = saved


def test_a_copy_holds_the_database_and_the_rulebook_and_opens():
    with db.tx() as conn:
        db.next_ref(conn, "backup-test", "B")
    with _folders() as root:
        copy = backup.make(date(2026, 10, 25))
        assert copy.name == f"{backup.company_slug()}-2026-10-25.tar.gz"
        with tarfile.open(copy) as tar:
            assert set(tar.getnames()) == {"cfo.db", "company.md"}
        held = backup.open_copy(copy, root / "restored")
        assert "cfo.db" in held
        conn = sqlite3.connect(root / "restored" / "cfo.db")
        try:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("select count(*) from counters where series = 'backup-test'"
                                ).fetchone()[0] == 1
        finally:
            conn.close()
        assert "kontantgulv" in (root / "restored" / "company.md").read_text(encoding="utf-8")


def test_fourteen_nights_are_kept_and_the_oldest_go():
    with _folders():
        first = date(2026, 10, 1)
        for n in range(16):
            backup.make(first + timedelta(days=n))
        assert len(backup.kept()) == backup.KEEP
        assert backup.kept()[0].name.endswith("2026-10-03.tar.gz")
        assert backup.kept()[-1].name.endswith("2026-10-16.tar.gz")


def test_the_copy_outside_is_unreadable_without_the_key():
    key = Fernet.generate_key().decode()
    with _folders(key) as root:
        copy = backup.make(date(2026, 10, 25))
        sealed = root / (copy.name + ".enc")
        sealed.write_bytes(backup.encrypt(copy.read_bytes()))
        assert b"SQLite format" not in sealed.read_bytes()
        assert "cfo.db" in backup.open_copy(sealed, root / "opened")

        config.BACKUP_KEY = Fernet.generate_key().decode()
        try:
            backup.open_copy(sealed, root / "wrong-key")
            raise AssertionError("opened with the wrong key")
        except backup.BackupError as exc:
            assert "Feil nøkkel" in str(exc)


def test_a_host_without_the_copy_outside_says_so_a_laptop_does_not():
    saved = config.HOSTED, config.BACKUP_SUPABASE_KEY
    with _folders():
        backup.make(date(2026, 10, 25))
        try:
            config.BACKUP_SUPABASE_KEY = ""
            config.HOSTED = False
            assert asyncio.run(scheduler._offsite()) == {"skipped": True}
            config.HOSTED = True
            out = asyncio.run(scheduler._offsite())
            assert out["partial"] and "Ingen kopi utenfor serveren" in out["cause"]
        finally:
            config.HOSTED, config.BACKUP_SUPABASE_KEY = saved


class _Supabase:
    """Supabase Storage, as far as the upload goes: keeps what it is sent."""

    objects: dict[str, bytes] = {}
    deleted: list[str] = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers, content=None, json=None):
        class R:
            status_code = 200
            text = ""

        r = R()
        if "/object/list/" in url:
            names = sorted(k.split("/", 1)[1] for k in _Supabase.objects)
            r.json = lambda: [{"name": n} for n in names]
        else:
            path = url.split("/object/backups/", 1)[1]
            _Supabase.objects[path] = content
        return r

    async def request(self, method, url, headers, json):
        assert method == "DELETE"
        for p in json["prefixes"]:
            _Supabase.deleted.append(p)
            _Supabase.objects.pop(p, None)


def test_the_upload_is_encrypted_and_keeps_fourteen_there_too():
    key = Fernet.generate_key().decode()
    saved = backup.httpx.AsyncClient, config.BACKUP_SUPABASE_KEY, config.BACKUP_SUPABASE_URL
    backup.httpx.AsyncClient = _Supabase
    _Supabase.objects, _Supabase.deleted = {}, []
    config.BACKUP_SUPABASE_KEY, config.BACKUP_SUPABASE_URL = "service", "https://x.supabase.co"
    try:
        with _folders(key):
            first = date(2026, 10, 1)
            for n in range(15):
                out = asyncio.run(backup.upload(backup.make(first + timedelta(days=n))))
            slug = backup.company_slug()
            assert out["object"] == f"backups/{slug}/{slug}-2026-10-15.tar.gz.enc"
            assert len(_Supabase.objects) == backup.KEEP
            assert _Supabase.deleted == [f"{slug}/{slug}-2026-10-01.tar.gz.enc"]
            body = _Supabase.objects[f"{slug}/{slug}-2026-10-15.tar.gz.enc"]
            assert backup.decrypt(body)[:2] == b"\x1f\x8b"      # a gzip, once opened
    finally:
        backup.httpx.AsyncClient, config.BACKUP_SUPABASE_KEY, config.BACKUP_SUPABASE_URL = saved


def test_the_backup_runs_every_night_after_the_mornings_jobs_in_the_list():
    j = scheduler.job("backup")
    assert j is scheduler.JOBS[-1]
    assert all(j.runs_on(date(2026, 12, 24) + timedelta(days=n)) for n in range(14))
    assert [s.name for s in j.steps] == ["backup", "offsite"]


def test_the_company_in_a_file_name():
    saved = config.DEMO, config.COMPANY_NAME
    try:
        config.DEMO, config.COMPANY_NAME = None, "Ærlig Østby & Sønn AS"
        assert backup.company_slug() == "aerlig-ostby-sonn-as"
    finally:
        config.DEMO, config.COMPANY_NAME = saved


@contextmanager
def _own_database():
    saved = db.PATH
    db.PATH = Path(tempfile.mkdtemp()) / "cfo.db"
    try:
        yield db.PATH
    finally:
        db.PATH = saved


def _counter(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("select value from counters where series = 'restore-test'").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def test_a_copy_left_in_restore_is_put_in_place_at_start_and_the_old_kept_aside():
    key = Fernet.generate_key().decode()
    with _own_database() as path, _folders(key) as root:
        with db.tx() as conn:
            db.next_ref(conn, "restore-test", "R")
        copy = backup.make(date(2026, 10, 25))
        with db.tx() as conn:                      # written after the copy
            db.next_ref(conn, "restore-test", "R")
        assert _counter(path) == 2

        (root / "restore").mkdir()
        sealed = root / "restore" / (copy.name + ".enc")
        sealed.write_bytes(backup.encrypt(copy.read_bytes()))
        assert backup.restore_pending() == sealed.name

        assert _counter(path) == 1
        [aside] = root.glob("before-restore-*")
        assert _counter(aside / "cfo.db") == 2
        assert (aside / sealed.name).exists() and not any((root / "restore").iterdir())
        assert backup.restore_pending() is None    # the next start does nothing


def test_a_copy_that_will_not_open_leaves_the_data_alone():
    with _own_database() as path, _folders(Fernet.generate_key().decode()) as root:
        with db.tx() as conn:
            db.next_ref(conn, "restore-test", "R")
        (root / "restore").mkdir()
        (root / "restore" / "broken.tar.gz.enc").write_bytes(b"not a copy")
        assert backup.restore_pending() is None
        assert _counter(path) == 1
        assert not list(root.glob("before-restore-*"))
