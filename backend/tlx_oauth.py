"""Holder et gyldig access token for Tripletex MCP.

Refresh-tokenet kommer fra innstillingen TRIPLETEX_REFRESH_TOKEN (satt i .env
av scripts/oauth_login.py, eller i Renders innstillinger). Det kan utløpe: det
gjorde det 7. oktober 2026 (`invalid_grant: Refresh token expired`), og da
hjelper bare en ny innlogging i nettleseren. Access-tokens er kortlevde, så de
veksles inn ved behov og caches til like før de går ut.

Tripletex roterer refresh-tokenet ved fornyelse. Det nye lagres i
`state/tripletex.json`, på disken ved siden av databasen, ikke i .env: en
server på Render har ingen .env å skrive til, og ved første omstart ville den
ha tatt det gamle tokenet fra innstillingen igjen, som Tripletex da har
forkastet. Fila husker også hvilken innstilling den startet fra. Står det et
annet token i innstillingen enn det, er det en ny innlogging, og den vinner.
"""
import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path

import httpx2 as httpx

from dotenv import dotenv_values

import config

log = logging.getLogger("cfo.oauth")

TOKEN_URL = "https://mcp.tripletex.no/token"
# Refresh this many seconds before the server says it expires.
SKEW = 90


def _fingerprint(token: str) -> str:
    """Which setting a stored token started from, without storing it twice."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


class OAuthError(RuntimeError):
    pass


# Tripletex's answers that only a person at a browser can mend: the session is
# gone, or the registered client is. Anything else (a 5xx, a timeout) may pass.
DEAD = ("invalid_grant", "invalid_client")

# What the owner reads when the login is gone, on every page that needs figures.
LOGIN_LOST = "Tripletex-innloggingen virker ikke, så ingen tall kan hentes."


def login_fix() -> str:
    """The way back, for where the app runs."""
    fix = "Logg inn på nytt: ./.venv/bin/python scripts/oauth_login.py på Macen."
    if config.HOSTED:
        fix += (" Legg så TRIPLETEX_REFRESH_TOKEN fra .env inn i Renders "
                "innstillinger, og TRIPLETEX_CLIENT_ID hvis den er ny, og start "
                "appen på nytt.")
    return fix


def is_login_error(exc: BaseException) -> bool:
    """A Tripletex login only a person can mend. The module that hit it often
    wraps it in its own error, so its fix is looked for in the words too."""
    return isinstance(exc, OAuthError) or "oauth_login.py" in str(exc)


class TokenManager:
    def __init__(self, store: Path | None = None, env: Path | None = None) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._refresh: str | None = None   # read on first use, not at import
        self._client_id = config.TRIPLETEX_CLIENT_ID
        self._store = store or config.STATE / "tripletex.json"
        self._env = env or config.ROOT / ".env"
        self._lock = asyncio.Lock()
        # Set when Tripletex has said the login is gone: (why, the settings it
        # died with). Every renewal after it fails at once with the same words,
        # instead of the thirty requests behind the lock each asking again.
        self._dead: tuple[str, tuple[str, str]] | None = None

    @property
    def configured(self) -> bool:
        return bool(self._current_refresh() and self._client_id)

    def status(self) -> dict:
        """The login as the owner needs to know it: ok, expired or missing,
        or untested while nothing has asked Tripletex since the start."""
        if config.DEMO:
            return {"login": "demo"}
        self._revive()
        if self._dead:
            return {"login": "expired", "message": self._dead[0], "fix": login_fix()}
        if not self.configured:
            return {"login": "missing",
                    "message": "Tripletex-innloggingen er ikke satt opp.",
                    "fix": login_fix()}
        return {"login": "ok" if self._token else "untested"}

    def _settings(self) -> tuple[str, str]:
        """The login as the settings hold it now: .env, which the login script
        writes while the app runs, over what the process started with."""
        try:
            env = dotenv_values(self._env) if self._env.exists() else {}
        except OSError:
            env = {}
        return (env.get("TRIPLETEX_REFRESH_TOKEN") or config.TRIPLETEX_REFRESH_TOKEN,
                env.get("TRIPLETEX_CLIENT_ID") or config.TRIPLETEX_CLIENT_ID)

    def _revive(self) -> None:
        """After a dead login, a new one in the settings is tried; the same one
        is not. A restart starts afresh anyway."""
        if not self._dead:
            return
        refresh, client = self._settings()
        if (refresh, client) == self._dead[1] or not (refresh and client):
            return
        log.info("Ny Tripletex-innlogging i innstillingene; prøver den")
        config.TRIPLETEX_REFRESH_TOKEN, config.TRIPLETEX_CLIENT_ID = refresh, client
        self._client_id, self._refresh, self._token = client, None, None
        self._expires_at, self._dead = 0.0, None

    def _current_refresh(self) -> str:
        """The refresh token to renew with: the stored one, unless the setting is newer.

        The stored token wins while the setting is the one it started from:
        that is the same login, rotated since. A setting the file has not seen
        is a new login, put there because the old one stopped working, so it
        replaces the file.
        """
        if self._refresh is not None:
            return self._refresh
        setting = config.TRIPLETEX_REFRESH_TOKEN
        stored = self._read_store()
        if stored and setting and stored.get("from_setting") != _fingerprint(setting):
            log.info("Ny Tripletex-innlogging i innstillingene; den erstatter den lagrede")
            stored = None
        if stored and stored.get("refresh_token"):
            self._refresh = stored["refresh_token"]
        else:
            self._refresh = setting
            if setting:
                self._persist_refresh(setting)
        return self._refresh

    def _read_store(self) -> dict | None:
        try:
            return json.loads(self._store.read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.error("Kunne ikke lese %s (%s); bruker innstillingen", self._store, exc)
            return None

    def _persist_refresh(self, value: str) -> None:
        """Keep the newest refresh token on the disk, beside the database.

        Written through a temporary file and renamed into place. A half-written
        file loses the only credential that cannot be regenerated without a
        human at a browser, and rewriting it in place risks exactly that if the
        process dies mid-write.
        """
        setting = config.TRIPLETEX_REFRESH_TOKEN
        body = {"refresh_token": value,
                "from_setting": _fingerprint(setting) if setting else None,
                "saved": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        tmp = self._store.with_suffix(".tmp")
        try:
            self._store.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(body, f)
            os.replace(tmp, self._store)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            log.error("Kunne ikke lagre det roterte refresh-tokenet: %s", exc)

    async def access_token(self) -> str:
        if config.DEMO:
            # Demo mode never holds a Tripletex token, so it can never renew
            # (and rotate away) the real one.
            raise OAuthError("Demomodus bruker ikke Tripletex.")
        if not self.configured:
            raise OAuthError(
                "Mangler TRIPLETEX_CLIENT_ID / TRIPLETEX_REFRESH_TOKEN. "
                "Kjør: ./.venv/bin/python scripts/oauth_login.py"
            )
        async with self._lock:
            self._revive()
            if self._dead:
                raise OAuthError(self._dead[0])
            if self._token and time.time() < self._expires_at:
                return self._token

            async with httpx.AsyncClient(timeout=40) as c:
                r = await c.post(TOKEN_URL, data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._current_refresh(),
                    "client_id": self._client_id,
                }, headers={"Content-Type": "application/x-www-form-urlencoded"})

            if r.status_code != 200:
                # Tripletex says why in the body, and the reasons need
                # different fixes: "invalid_grant" means the session is gone
                # and only a new browser login helps, while "invalid_client"
                # means the registration is wrong and logging in again will
                # not touch it. Throwing the body away turned a five-second
                # diagnosis into guesswork.
                detail, hint, error = "", "Kjør scripts/oauth_login.py på nytt.", ""
                try:
                    body = r.json()
                    error = body.get("error") or ""
                    detail = (f"{error}: "
                              f"{body.get('error_description', '')}").strip(": ")
                    if error == "invalid_client":
                        hint = ("Klienten er ikke gyldig lenger — registrer en "
                                "ny med scripts/oauth_login.py --ny-klient.")
                except Exception:  # noqa: BLE001
                    detail = r.text[:200]
                log.error("Tripletex avviste fornyelsen (%s): %s",
                          r.status_code, detail)
                message = (f"Kunne ikke fornye Tripletex-tilgangen ({r.status_code})"
                           + (f" — {detail}. " if detail else ". ") + hint)
                if error in DEAD:
                    # Asking again with the same login only earns «Session not
                    # found». Stop here until the settings hold a new one.
                    self._dead = (message, self._settings())
                    log.error("Tripletex-innloggingen er død; ingen nye forsøk "
                              "før en ny innlogging eller en omstart")
                raise OAuthError(message)

            d = r.json()
            self._token = d.get("access_token")
            if not self._token:
                raise OAuthError("Svaret fra Tripletex manglet access_token.")
            self._expires_at = time.time() + max(int(d.get("expires_in", 3600)) - SKEW, 60)

            rotated = d.get("refresh_token")
            if rotated and rotated != self._refresh:
                self._refresh = rotated
                self._persist_refresh(rotated)
                log.info("Refresh token rotated and saved")

            log.info("Tripletex access token fornyet, varer ~%ss", d.get("expires_in"))
            return self._token


tokens = TokenManager()
