"""Holder et gyldig access token for Tripletex MCP.

Refresh-tokenet kommer fra innstillingen TRIPLETEX_REFRESH_TOKEN (satt i .env
av scripts/oauth_login.py, eller i Renders innstillinger) og utløper ikke.
Access-tokens er kortlevde, så de veksles inn ved behov og caches til like før
de går ut.

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


class TokenManager:
    def __init__(self, store: Path | None = None) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._refresh: str | None = None   # read on first use, not at import
        self._client_id = config.TRIPLETEX_CLIENT_ID
        self._store = store or config.STATE / "tripletex.json"
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self._current_refresh() and self._client_id)

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
                detail, hint = "", "Kjør scripts/oauth_login.py på nytt."
                try:
                    body = r.json()
                    detail = (f"{body.get('error', '')}: "
                              f"{body.get('error_description', '')}").strip(": ")
                    if body.get("error") == "invalid_client":
                        hint = ("Klienten er ikke gyldig lenger — registrer "
                                "den på nytt med scripts/oauth_login.py.")
                except Exception:  # noqa: BLE001
                    detail = r.text[:200]
                log.error("Tripletex avviste fornyelsen (%s): %s",
                          r.status_code, detail)
                raise OAuthError(
                    f"Kunne ikke fornye Tripletex-tilgangen ({r.status_code})"
                    + (f" — {detail}. " if detail else ". ") + hint
                )

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
