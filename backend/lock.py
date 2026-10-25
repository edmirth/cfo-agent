"""One server per installation, enforced.

Two servers on the same port is not the failure that happened — the OS already
refuses that. What happened is two servers on *different* ports sharing one
login: Tripletex rotates the refresh token on every renewal and
`tlx_oauth.py` keeps the new one in the state directory, so the second process renews with a
token the first has already replaced, Tripletex rejects it, and the account is
locked out until somebody logs in through a browser again. Binding a port does
not protect a file, so the lock is taken on the state directory instead.

`flock` rather than a PID file: the kernel releases it when the process dies,
however it dies. A PID file left behind by a crash has to be second-guessed —
is 41288 still our server, or someone else's process with a recycled id — and
guessing wrong means either refusing to start for no reason or starting a
second server anyway, which is the thing being prevented.
"""
import atexit
import fcntl
import json
import logging
import os
import socket
from datetime import datetime

import config

log = logging.getLogger("cfo.lock")

LOCKFILE = config.STATE / "server.lock"

_handle = None


class AlreadyRunning(RuntimeError):
    """Another server holds the lock. Carries what is known about it."""

    def __init__(self, holder: dict | None) -> None:
        self.holder = holder or {}
        who = (f"PID {self.holder['pid']}, startet {self.holder.get('started', '?')}"
               if self.holder.get("pid") else "ukjent prosess")
        super().__init__(
            f"En annen CFO-server kjører allerede ({who}).\n\n"
            f"To servere deler .env og fornyer det samme Tripletex-tokenet. "
            f"Tokenet roteres ved hver fornyelse, så den ene ugyldiggjør den "
            f"andre, og da må noen logge inn i nettleseren på nytt for å "
            f"komme i gang igjen. Derfor startes ikke denne.\n\n"
            f"Stopp den som kjører først"
            + (f":  kill {self.holder['pid']}" if self.holder.get("pid") else "."))


def _read_holder(fh) -> dict | None:
    try:
        fh.seek(0)
        return json.loads(fh.read() or "{}") or None
    except (json.JSONDecodeError, OSError):
        return None


def acquire() -> dict:
    """Take the lock, or raise AlreadyRunning with who has it."""
    global _handle
    LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    fh = open(LOCKFILE, "a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        holder = _read_holder(fh)
        fh.close()
        raise AlreadyRunning(holder) from None

    info = {"pid": os.getpid(), "host": socket.gethostname(),
            "started": datetime.now().isoformat(timespec="seconds")}
    fh.seek(0)
    fh.truncate()
    fh.write(json.dumps(info, ensure_ascii=False))
    fh.flush()
    os.fsync(fh.fileno())
    _handle = fh
    atexit.register(release)
    log.info("Serverlås tatt (PID %s)", info["pid"])
    return info


def release() -> None:
    """Give up the lock. Safe to call twice; the kernel does it anyway."""
    global _handle
    if _handle is None:
        return
    try:
        _handle.seek(0)
        _handle.truncate()
        fcntl.flock(_handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        try:
            _handle.close()
        except OSError:
            pass
        _handle = None


def holder() -> dict | None:
    """Who holds the lock right now, without taking it."""
    if not LOCKFILE.exists():
        return None
    try:
        with open(LOCKFILE, "r+", encoding="utf-8") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return _read_holder(fh)          # held by someone else
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            return None                          # free
    except OSError:
        return None
