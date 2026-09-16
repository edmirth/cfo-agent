"""Snakker direkte med Tripletex MCP, uten å gå veien om modellen.

Tall til dashbordet hentes herfra: det er gratis, eksakt og raskt. Modellen
brukes bare når noen faktisk stiller et spørsmål.
"""
import asyncio
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
        self._session_id: str | None = None
        self._lock = asyncio.Lock()

    async def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {await tokens.access_token()}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session_id:
            h["mcp-session-id"] = self._session_id
        return h

    async def _handshake(self, c: httpx.AsyncClient) -> None:
        r = await c.post(config.TRIPLETEX_MCP_URL + "/", headers=await self._headers(), json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "cfo-agent", "version": "0.1.0"}}})
        if r.status_code != 200:
            raise McpError(f"MCP initialize svarte {r.status_code}: {r.text[:200]}")
        self._session_id = r.headers.get("mcp-session-id")
        await c.post(config.TRIPLETEX_MCP_URL + "/", headers=await self._headers(),
                     json={"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def call(self, tool: str, arguments: dict | None = None) -> dict:
        """Kall ett MCP-verktøy og returner det strukturerte innholdet."""
        async with self._lock:
            async with httpx.AsyncClient(timeout=120) as c:
                await self._handshake(c)
                r = await c.post(config.TRIPLETEX_MCP_URL + "/", headers=await self._headers(), json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments or {}}})
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


mcp = McpClient()
