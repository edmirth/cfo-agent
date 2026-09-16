"""Holder et gyldig access token for Tripletex MCP.

Refresh-tokenet lagres i .env av scripts/oauth_login.py og utløper ikke.
Access-tokens er kortlevde, så de veksles inn ved behov og caches til like før
de går ut. Roterer serveren refresh-tokenet, skrives det nye tilbake til .env.
"""
import asyncio
import logging
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
        """The server may rotate the refresh token; keep .env in step."""
        env = Path(config.ROOT) / ".env"
        if not env.exists():
            return
        text = env.read_text()
        text = re.sub(r"^TRIPLETEX_REFRESH_TOKEN=.*$",
                      f"TRIPLETEX_REFRESH_TOKEN={value}", text, flags=re.MULTILINE)
        env.write_text(text)
        env.chmod(0o600)

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
                raise OAuthError(
                    f"Kunne ikke fornye Tripletex-tilgangen ({r.status_code}). "
                    "Kjør scripts/oauth_login.py på nytt."
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
