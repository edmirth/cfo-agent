"""FastAPI app serving the CFO chat UI and its streaming backend."""
import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
from agent import run_turn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("cfo.api")

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="CFO Agent", version="0.1.0")

# In-memory conversation store. One process only — move to Redis or Postgres
# before running more than one worker.
SESSIONS: dict[str, list[dict]] = {}

DAILY_BRIEF = (
    "Kjør den daglige gjennomgangen. Hent ferske tall fra Tripletex og gå "
    "gjennom inntjening, kontanter mot resultat, kundefordringer, "
    "konsentrasjon, likviditet og forpliktelser som bygger seg opp. "
    "Svar kort: hva har endret seg siden i går eller siste virkedag, hva "
    "betyr det, og hva bør jeg gjøre i dag. Hvis ingenting krever handling, "
    "si det på én linje i stedet for å fylle ut en rapport."
)

PRESETS = [
    {"id": "daily", "label": "Daglig brief", "prompt": DAILY_BRIEF},
    {
        "id": "cash",
        "label": "Likviditet",
        "prompt": "Hvordan ligger vi an på likviditet? Bygg broen fra inngående "
                  "til dagens saldo og vis hva som binder kapital.",
    },
    {
        "id": "ar",
        "label": "Kundefordringer",
        "prompt": "Gå gjennom kundefordringene. Total, kredittid, aldersfordeling "
                  "og de største eksponeringene. Hvem må purres nå?",
    },
    {
        "id": "margin",
        "label": "Marginer",
        "prompt": "Hvordan utvikler marginene seg? Vis kostnadsstrukturen som "
                  "andel av omsetning og sammenlign mot budsjett og mot i fjor.",
    },
    {
        "id": "forecast",
        "label": "Prognosemodell",
        "prompt": "Bygg en resultatprognose ut året basert på faktiske tall "
                  "hittil. Vis forutsetningene, og lag et lavt, et forventet og "
                  "et høyt scenario.",
    },
]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": bool(config.ANTHROPIC_API_KEY),
        "company": config.COMPANY_NAME,
        "model": config.CFO_MODEL,
        "mcp_url": config.TRIPLETEX_MCP_URL,
        "mcp_authenticated": bool(config.TRIPLETEX_MCP_TOKEN),
    }


@app.get("/api/presets")
async def presets() -> dict:
    return {"presets": [{"id": p["id"], "label": p["label"]} for p in PRESETS]}


@app.post("/api/session/reset")
async def reset(session_id: str) -> dict:
    SESSIONS.pop(session_id, None)
    return {"ok": True}


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY er ikke satt.")

    session_id = req.session_id or uuid.uuid4().hex
    history = SESSIONS.setdefault(session_id, [])

    # A preset id sent as the message body expands to its full prompt.
    text = next((p["prompt"] for p in PRESETS if p["id"] == req.message), req.message)
    history.append({"role": "user", "content": text})

    # Trim oldest turns, keeping the list starting on a user message so the
    # API never sees a history that opens with an assistant turn.
    if len(history) > config.MAX_HISTORY_MESSAGES:
        del history[: len(history) - config.MAX_HISTORY_MESSAGES]
        while history and history[0]["role"] != "user":
            history.pop(0)

    async def stream():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
        try:
            async for event in run_turn(history):
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
            log.exception("Turn failed")
            payload = {"type": "error", "message": f"Uventet feil: {exc}"}
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="static")
