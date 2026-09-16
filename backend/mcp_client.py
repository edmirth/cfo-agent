"""Snakker direkte med Tripletex MCP, uten å gå veien om modellen.

Tall til dashbordet hentes herfra: det er gratis, eksakt og raskt. Modellen
brukes bare når noen faktisk stiller et spørsmål.

Håndtrykket gjøres én gang og sesjonen gjenbrukes, så parallelle kall er
faktisk parallelle. Låsen dekker kun oppsettet.
"""
import asyncio
import itertools
import json
import logging

import httpx2 as httpx

import config
from tlx_oauth import tokens

log = logging.getLogger("cfo.mcp")


class McpError(RuntimeError):
    pass


def _parse(body: str) -> dict:
    """MCP-endepunktet svarer som SSE; hent JSON ut av data-linja."""
    if "data: " in body:
        body = next(l[6:] for l in body.splitlines() if l.startswith("data: "))
    return json.loads(body)


class McpClient:
    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None
        self._session_id: str | None = None
        self._ready = False
        self._lock = asyncio.Lock()
        self._ids = itertools.count(1)

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        self._ready = False

    def _headers(self, access_token: str) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session_id:
            h["mcp-session-id"] = self._session_id
        return h

    async def _connect(self) -> None:
        """Etabler sesjonen. Kun denne delen er serialisert."""
        async with self._lock:
            if self._ready:
                return
            if self._http is None:
                self._http = httpx.AsyncClient(timeout=120)
            at = await tokens.access_token()
            self._session_id = None
            r = await self._http.post(config.TRIPLETEX_MCP_URL + "/", headers=self._headers(at), json={
                "jsonrpc": "2.0", "id": next(self._ids), "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "cfo-agent", "version": "0.1.0"}}})
            if r.status_code != 200:
                raise McpError(f"MCP initialize svarte {r.status_code}: {r.text[:200]}")
            self._session_id = r.headers.get("mcp-session-id")
            await self._http.post(config.TRIPLETEX_MCP_URL + "/", headers=self._headers(at),
                                  json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            self._ready = True
            log.info("MCP-sesjon etablert")

    async def call(self, tool: str, arguments: dict | None = None) -> dict:
        """Kall ett MCP-verktøy og returner det strukturerte innholdet."""
        for attempt in (1, 2):
            await self._connect()
            at = await tokens.access_token()
            assert self._http is not None
            r = await self._http.post(config.TRIPLETEX_MCP_URL + "/", headers=self._headers(at), json={
                "jsonrpc": "2.0", "id": next(self._ids), "method": "tools/call",
                "params": {"name": tool, "arguments": arguments or {}}})

            # Sesjonen kan ha falt ut; bygg den på nytt og prøv én gang til.
            if r.status_code in (401, 404) and attempt == 1:
                log.info("MCP-sesjonen var utgått, kobler opp på nytt")
                self._ready = False
                continue
            if r.status_code != 200:
                raise McpError(f"{tool} svarte {r.status_code}: {r.text[:200]}")

            payload = _parse(r.text)
            if "error" in payload:
                raise McpError(f"{tool}: {payload['error'].get('message')}")
            result = payload.get("result", {})

            # Tripletex returnerer JSON i en tekstblokk; plukk ut den største.
            best: dict = {}
            for block in result.get("content", []):
                text = block.get("text", "")
                start = text.find("{")
                if start == -1:
                    continue
                try:
                    parsed = json.loads(text[start:])
                except json.JSONDecodeError:
                    continue
                if len(json.dumps(parsed)) > len(json.dumps(best)):
                    best = parsed
            return best or result

        raise McpError(f"{tool}: kunne ikke etablere MCP-sesjon")


mcp = McpClient()
