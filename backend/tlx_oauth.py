"""Holder et gyldig access token for Tripletex MCP.

Refresh-tokenet lagres i .env av scripts/oauth_login.py og utløper ikke.
Access-tokens er kortlevde, så de veksles inn ved behov og caches til like før
de går ut. Roterer serveren refresh-tokenet, skrives det nye tilbake til .env.
"""
import asyncio
import logging
import os
import re
import time
from pathlib import Path

import httpx2 as httpx

import config

log = logging.getLogger("cfo.oauth")

TOKEN_URL = "https://mcp.tripletex.no/token"
# Refresh this many seconds before the server says it expires.
SKEW = 90


class OAuthError(RuntimeError):
    pass


class TokenManager:
    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._refresh = config.TRIPLETEX_REFRESH_TOKEN
        self._client_id = config.TRIPLETEX_CLIENT_ID
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self._refresh and self._client_id)

    def _persist_refresh(self, value: str) -> None:
        """The server may rotate the refresh token; keep .env in step.

        Written through a temporary file and renamed into place. A half-written
        .env loses the only credential that cannot be regenerated without a
        human at a browser, and rewriting it in place risks exactly that if the
        process dies mid-write.
        """
        env = Path(config.ROOT) / ".env"
        if not env.exists():
            return
        text = env.read_text()
        updated, count = re.subn(r"^TRIPLETEX_REFRESH_TOKEN=.*$",
                                 f"TRIPLETEX_REFRESH_TOKEN={value}", text,
                                 flags=re.MULTILINE)
        if not count:
            log.error("Fant ingen TRIPLETEX_REFRESH_TOKEN-linje i .env; det "
                      "roterte tokenet ble ikke lagret og går tapt ved omstart")
            return
        tmp = env.with_suffix(".env.tmp")
        try:
            tmp.write_text(updated)
            tmp.chmod(0o600)
            os.replace(tmp, env)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            log.error("Kunne ikke lagre det roterte refresh-tokenet: %s", exc)

    async def access_token(self) -> str:
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
                    "refresh_token": self._refresh,
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
