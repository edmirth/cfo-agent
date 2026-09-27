"""FastAPI app serving the CFO chat UI and its streaming backend."""
import json
import logging
import uuid
from datetime import date
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
from agent import run_turn
from overview import cached as overview_cached
import cards
import company
import definitions
import lock
import toolset
import trace
from cashflow import cached as cashflow_cached
from commitments import cached as commitments_cached
from industry import dashboard as industry_dashboard, profile as industry_profile
from preflight import cached as preflight_cached

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("cfo.api")

# Frontenden er React + shadcn, bygget med Vite. Er det ikke bygget ennå,
# serves den gamle vanilla-frontenden, så serveren alltid har noe å vise.
_ROOT = Path(__file__).resolve().parent.parent
_BUILT = _ROOT / "frontend-react" / "dist"
FRONTEND = _BUILT if (_BUILT / "index.html").exists() else _ROOT / "frontend"

# Taken at import, before uvicorn binds anything: a second server must fail
# here rather than reach the point where it renews the Tripletex token and
# locks the first one out.
try:
    _LOCK = lock.acquire()
except lock.AlreadyRunning as exc:
    print(f"\n! {exc}\n", flush=True)
    raise SystemExit(1) from None

app = FastAPI(title="CFO Agent", version="0.1.0")

# In-memory conversation store. One process only — move to Redis or Postgres
# before running more than one worker. Oldest sessions are evicted so a
# long-running server cannot grow without bound.
SESSIONS: dict[str, list[dict]] = {}
MAX_SESSIONS = 200


def _touch(session_id: str) -> list[dict]:
    """Fetch a session and mark it most recently used."""
    history = SESSIONS.pop(session_id, [])
    SESSIONS[session_id] = history
    while len(SESSIONS) > MAX_SESSIONS:
        SESSIONS.pop(next(iter(SESSIONS)))
    return history


def _answers_a_tool(msg: dict) -> bool:
    """True when this user message only carries tool results."""
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any((b.get("type") if isinstance(b, dict) else getattr(b, "type", None))
               == "tool_result" for b in content)

DAILY_BRIEF = (
    "Hvordan går det med selskapet akkurat nå? Hent ferske tall. Start med "
    "hva som har endret seg siden sist, hva det betyr for meg i praksis, og "
    "hva jeg bør gjøre i dag. Forklar det uten regnskapsord — jeg er ikke "
    "økonom. Hvis ingenting haster, si det på én linje."
)

PRESETS = [
    {"id": "daily", "label": "Hvordan går det egentlig?", "prompt": DAILY_BRIEF},
    {
        "id": "money",
        "label": "Hvor mye av pengene på konto er mine?",
        "prompt": "Hvor mye av pengene som står på konto er faktisk "
                  "selskapets? Vis hva som allerede er lovet bort til moms, "
                  "skattetrekk, arbeidsgiveravgift, feriepenger og skatt, når "
                  "hver av delene forfaller, og hva jeg står igjen med.",
    },
    {
        "id": "ar",
        "label": "Hvem skylder meg penger?",
        "prompt": "Hvem skylder meg penger nå, hvor lenge har de ventet, og "
                  "hvem bør jeg purre i dag? Si hvor mye det utgjør, og hvem "
                  "som er størst — hvis én kunde er mye av det, vil jeg vite "
                  "det.",
    },
    {
        "id": "margin",
        "label": "Hvorfor blir det så lite igjen?",
        "prompt": "Av hver hundrelapp jeg fakturerer — hvor mye blir igjen, og "
                  "hvor blir resten av? Vis de største kostnadene, si om noe "
                  "har endret seg i det siste, og om det er varig eller en "
                  "engangsgreie.",
    },
    {
        "id": "forecast",
        "label": "Hvordan ser resten av året ut?",
        "prompt": "Hvordan ser resten av året ut hvis det fortsetter som nå? "
                  "Vis hva du regner med, hva som må til for at det går bedre, "
                  "og hva som skjer hvis det går dårligere. Si hvilke "
                  "forutsetninger som er mine å bestemme.",
    },
    {
        "id": "weeks",
        "label": "Klarer jeg meg de neste ukene?",
        "prompt": "Hvordan ser pengene ut uke for uke framover? Si når det er "
                  "tynnest, hvor mye jeg har igjen da, og hva som må til for at "
                  "det skal gå bra. Skill mellom det som er sikkert og det du "
                  "regner med.",
    },
    {
        "id": "afford",
        "label": "Har jeg råd til å ansette en til?",
        "prompt": "Har jeg råd til å ansette én person til? Regn på hva en "
                  "ansatt faktisk koster meg i året med arbeidsgiveravgift, "
                  "feriepenger og pensjon, hva det gjør med pengene på konto "
                  "måned for måned, og hvor mye vedkommende må fakturere for "
                  "at det skal lønne seg.",
    },
]


class DecisionRequest(BaseModel):
    option: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": bool(config.ANTHROPIC_API_KEY),
        "pid": _LOCK["pid"],
        "started": _LOCK["started"],
        "company": config.COMPANY_NAME,
        "model": config.CFO_MODEL,
        "tripletex_configured": bool(
            config.TRIPLETEX_CLIENT_ID and config.TRIPLETEX_REFRESH_TOKEN
        ),
        "read_only": True,
        "tools_allowed": len(toolset.READ_TOOLS),
    }


@app.get("/api/toolset")
async def toolset_audit() -> dict:
    """Hvilke verktøy agenten faktisk kan nå, målt mot det serveren tilbyr.

    Lista råtner: Tripletex legger til verktøy, og et nytt skriveverktøy skal
    ikke kunne gli inn ubemerket."""
    try:
        report = await toolset.audit()
        return {**report, "allowed_tools": sorted(toolset.READ_TOOLS)}
    except Exception as exc:  # noqa: BLE001
        log.exception("Toolset audit failed")
        return {"error": str(exc)}


async def _check_definitions() -> None:
    """Record any definition that changed since the last run, before serving."""
    try:
        r = definitions.sync()
        log.info("Definisjoner: %d i kraft, %d nye, %d endret",
                 r["total"], len(r["added"]), len(r["changed"]))
        if r["changed"]:
            log.warning("ENDRET BETYDNING: %s — eldre tall beholder sin gamle "
                        "definisjon", ", ".join(r["changed"]))
    except Exception as exc:  # noqa: BLE001
        log.error("Kunne ikke versjonere definisjonene: %s", exc)


async def _check_toolset() -> None:
    """Say out loud, once, what the agent can reach."""
    try:
        a = await toolset.audit()
        log.info("Lesetilgang: %d av %d verktøy åpne, %d stengt",
                 a["allowed"], a["server_tools"],
                 a["server_tools"] - a["allowed"])
        if a["missing"]:
            log.warning("Verktøy på lista finnes ikke hos serveren: %s",
                        ", ".join(a["missing"]))
    except Exception as exc:  # noqa: BLE001 — never block startup on this
        log.warning("Kunne ikke kontrollere verktøylista ved oppstart: %s", exc)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """What runs once at start and once at stop."""
    await _check_definitions()
    await _check_toolset()
    yield
    lock.release()


app.router.lifespan_context = _lifespan


@app.get("/api/overview")
async def overview() -> dict:
    """Nøkkeltall til forsiden. Hentes direkte fra Tripletex, ikke via modellen,
    så en sidelast koster ingenting og tallene er eksakte."""
    try:
        data = await overview_cached()
    except Exception as exc:  # noqa: BLE001 — forsiden skal vise en feil, ikke 500
        log.exception("Overview failed")
        return {"error": str(exc)}
    data["company"] = config.COMPANY_NAME
    return data


@app.get("/api/preflight")
async def preflight() -> dict:
    """Om bøkene er ajour. Samme kontroll som agenten leser før den svarer."""
    try:
        return await preflight_cached()
    except Exception as exc:  # noqa: BLE001
        log.exception("Preflight failed")
        return {"error": str(exc)}


@app.get("/api/commitments")
async def commitments() -> dict:
    """Hvor mye av pengene på konto som faktisk er selskapets."""
    try:
        return await commitments_cached()
    except Exception as exc:  # noqa: BLE001
        log.exception("Commitments failed")
        return {"error": str(exc)}


@app.get("/api/cashflow")
async def cashflow() -> dict:
    """Tretten uker fram: hva som kommer inn, hva som skal ut, og når det er tynnest."""
    try:
        return await cashflow_cached()
    except Exception as exc:  # noqa: BLE001
        log.exception("Cashflow failed")
        return {"error": str(exc)}


@app.get("/api/dashboard")
async def dashboard(refresh: bool = False) -> dict:
    """Bransjen selskapet er i, og nøkkeltallene som betyr noe i den bransjen.

    Bransjen bestemmes én gang og leses deretter fra disk; refresh=true tvinger
    en ny vurdering."""
    try:
        if refresh:
            await industry_profile(refresh=True)
        return await industry_dashboard()
    except Exception as exc:  # noqa: BLE001
        log.exception("Dashboard failed")
        return {"error": str(exc)}


@app.get("/api/cards")
async def get_cards(refresh: bool = True) -> dict:
    """Arbeidet som ligger klart til godkjenning.

    Bygges på nytt som standard, slik at forsiden viser det som gjelder nå og
    ikke det som gjaldt sist noen spurte."""
    try:
        return await cards.refresh() if refresh else cards.deck()
    except Exception as exc:  # noqa: BLE001
        log.exception("Cards failed")
        return {"error": str(exc)}


@app.post("/api/cards/{card_id}/decide")
async def decide_card(card_id: str, req: DecisionRequest) -> dict:
    """Registrer hva daglig leder valgte, og gjør det valget faktisk betyr."""
    try:
        return {"card": cards.decide(card_id, req.option, req.note)}
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Decision failed")
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/definitions")
async def definitions_registry(id: str | None = None) -> dict:
    """Hva hvert tall betyr, og hva det har betydd tidligere."""
    if id:
        return {"id": id, "history": definitions.history(id)}
    try:
        ledger = definitions.registry()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {**definitions.stamp(),
            "definitions": {k: {"version": h[-1]["version"],
                                "label": h[-1]["label"],
                                "formula": h[-1]["formula"],
                                "since": h[-1]["recorded"],
                                "revisions": len(h)}
                            for k, h in sorted(ledger.items()) if h}}


@app.get("/api/trace")
async def trace_account(account: int, date_from: str, date_to: str) -> dict:
    """Posteringene bak en saldo. Sluttdato er inklusiv, slik folk mener den."""
    for label, value in (("date_from", date_from), ("date_to", date_to)):
        try:
            date.fromisoformat(value)
        except ValueError:
            raise HTTPException(400, f"{label} må være YYYY-MM-DD, fikk «{value}»") from None
    try:
        return await trace.account(account, date_from, date_to)
    except Exception as exc:  # noqa: BLE001
        log.exception("Trace failed")
        return {"error": str(exc)}


class CompanyText(BaseModel):
    text: str = Field(max_length=20_000)


def _company_payload(d: dict) -> dict:
    return {
        "exists": d["exists"],
        "text": company.raw(),
        "settings": d["settings"],
        "notes": d.get("notes", []),
        "used_in_calculations": sorted(
            k for k in d["settings"] if k in company.KNOWN),
        "known_settings": {k: v[1] for k, v in company.KNOWN.items()},
    }


@app.get("/api/company")
async def company_context() -> dict:
    """Det selskapet har fortalt om seg selv, og hva av det som brukes i tall."""
    return _company_payload(company.load(force=True))


@app.put("/api/company")
async def save_company(req: CompanyText) -> dict:
    """Lagre det klienten har skrevet. Forrige versjon tas vare på."""
    try:
        return _company_payload(company.save(req.text))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        log.exception("Kunne ikke lagre company.md")
        raise HTTPException(500, str(exc)) from exc


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
    history = _touch(session_id)

    # A question the assistant never answered — the previous turn failed or
    # was interrupted — is dropped rather than stacked under the new one.
    while history and history[-1]["role"] == "user":
        history.pop()

    # A preset id sent as the message body expands to its full prompt.
    text = next((p["prompt"] for p in PRESETS if p["id"] == req.message), req.message)
    history.append({"role": "user", "content": text})

    # Trim oldest turns. The history must open on a real user message: an
    # assistant turn, or a user turn carrying tool results whose tool_use has
    # just been trimmed away, is rejected by the API.
    if len(history) > config.MAX_HISTORY_MESSAGES:
        del history[: len(history) - config.MAX_HISTORY_MESSAGES]
        while history and (history[0]["role"] != "user" or _answers_a_tool(history[0])):
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
