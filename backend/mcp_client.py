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
import random

import httpx2 as httpx

import config
from tlx_oauth import tokens

log = logging.getLogger("cfo.mcp")

# Tripletex answers a burst with HTTP 500 and an HTML error page, not a 429, so
# there is no Retry-After to obey and we have to hold the line ourselves.
# Measured over 1 173 calls: 0.3 % fail with four or fewer requests in flight in
# the same second, 7 % at nine to fifteen, 32 % at sixteen or more. Eight
# modules here call asyncio.gather and they nest — industry gathers overview,
# which gathers four reports — so a cold front page put sixteen-plus report
# requests on the wire at once and roughly a third of them fell over.
#
# Six is measured, not guessed. A cold front page fires 43 calls whatever the
# cap: at six the busiest second carries eight, with no 500s and no retries, and
# the slowest endpoint lands in 8.8s. Four is equally clean but 15.5s, because
# then the queue does the waiting.
MAX_INFLIGHT = 6
_inflight = asyncio.Semaphore(MAX_INFLIGHT)

# A 5xx from an overloaded report engine is transient: the same report fetched
# on its own succeeds every time. Retrying is right, but only behind the
# semaphore, or the retries are themselves the next burst.
RETRY_STATUS = (500, 502, 503, 504)
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 0.4


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

    async def list_tools(self) -> list[dict]:
        """Alle verktøy serveren tilbyr.

        Brukes til å holde lesetilgangslista ærlig: dukker det opp et nytt
        skriveverktøy hos Tripletex, skal vi oppdage det, ikke la det gli inn.
        """
        await self._connect()
        at = await tokens.access_token()
        assert self._http is not None
        r = await self._http.post(
            config.TRIPLETEX_MCP_URL + "/", headers=self._headers(at),
            json={"jsonrpc": "2.0", "id": next(self._ids), "method": "tools/list"})
        if r.status_code != 200:
            raise McpError(f"tools/list svarte {r.status_code}: {r.text[:200]}")
        payload = _parse(r.text)
        if "error" in payload:
            raise McpError(f"tools/list: {payload['error'].get('message')}")
        return payload.get("result", {}).get("tools", []) or []

    async def call(self, tool: str, arguments: dict | None = None) -> dict:
        """Kall ett MCP-verktøy og returner det strukturerte innholdet."""
        reconnected = False
        for attempt in range(1, MAX_ATTEMPTS + 1):
            await self._connect()
            at = await tokens.access_token()
            assert self._http is not None
            # Held only around the request itself. The handshake has its own
            # lock and runs once; queueing it here would deadlock the first
            # caller behind requests that cannot start until it finishes.
            async with _inflight:
                r = await self._http.post(config.TRIPLETEX_MCP_URL + "/", headers=self._headers(at), json={
                    "jsonrpc": "2.0", "id": next(self._ids), "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments or {}}})

            # Sesjonen kan ha falt ut; bygg den på nytt og prøv én gang til.
            if r.status_code in (401, 404) and not reconnected:
                log.info("MCP-sesjonen var utgått, kobler opp på nytt")
                reconnected = True
                self._ready = False
                continue
            if r.status_code in RETRY_STATUS and attempt < MAX_ATTEMPTS:
                # Jittered, so callers that failed together do not come back
                # together and rebuild the burst that failed them.
                delay = BACKOFF_SECONDS * 2 ** (attempt - 1) * (1 + random.random())
                log.warning("%s svarte %s, forsøk %s av %s — venter %.1fs",
                            tool, r.status_code, attempt, MAX_ATTEMPTS, delay)
                await asyncio.sleep(delay)
                continue
            if r.status_code != 200:
                raise McpError(f"{tool} svarte {r.status_code}: {r.text[:200]}")

            payload = _parse(r.text)
            if "error" in payload:
                raise McpError(f"{tool}: {payload['error'].get('message')}")
            result = payload.get("result", {})

            # Et avvist kall kommer tilbake som HTTP 200 med isError satt, ikke
            # som en JSON-RPC-feil. Uten dette ser en avvist forespørsel ut som
            # tomt resultat hos den som spør — og tomt leses som «ingenting å
            # melde», som er den ene tolkningen som aldri er trygg.
            if result.get("isError"):
                text = " ".join(b.get("text", "") for b in result.get("content", []))
                raise McpError(f"{tool}: {text[:300] or 'avvist uten begrunnelse'}")

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


if config.DEMO:
    # A made-up company's books, answered here. No session, no token, no
    # request to Tripletex can come from this process (backend/demo/).
    from demo.companies import SPECS
    from demo.tripletex import FakeTripletex
    mcp = FakeTripletex(SPECS[config.DEMO])
else:
    mcp = McpClient()
