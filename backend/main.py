"""FastAPI app serving the CFO chat UI and its streaming backend."""
import json
import logging
import uuid
from datetime import date
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
from agent import run_turn
from mcp_client import McpError
from overview import cached as overview_cached
import auth
import brief
import cards
import company
import conversations
import db
import definitions
import job_runs
import lock
import scheduler
import scoring
import toolset
import trace
from cashflow import cached as cashflow_cached
from cashflow import rules as cashflow_rules
from commitments import cached as commitments_cached
from industry import dashboard as industry_dashboard
from preflight import cached as preflight_cached
from summary import cached as summary_cached

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

# Also before anything binds: a server that would answer anyone stops here.
auth.check_config()

app = FastAPI(title="CFO Agent", version="0.1.0")
# In front of every route, so a route added later is covered without anyone
# remembering to. Only /api/auth/config answers without a login.
app.middleware("http")(auth.middleware)

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


def _panel(exc: Exception, what: str) -> dict:
    """What a front-page panel is allowed to say when it cannot be computed.

    These routes answer 200 with an `error` field on purpose — the frontend
    throws per panel, so one dead panel does not take the page down. What they
    must not do is put `str(exc)` in it: an MCP transport message or a
    provider's billing URL is not something a managing director can act on, and
    the request ids in it belong in the log. The log already has the traceback;
    this is the sentence on the screen.
    """
    if isinstance(exc, McpError):
        cause = "Tripletex svarte ikke på oppslaget."
    elif "credit balance is too low" in str(exc):
        cause = "Det er ikke kreditt på Anthropic-kontoen."
    else:
        cause = "Noe feilet i beregningen."
    return {"error": f"{what} kunne ikke hentes nå. {cause} "
                     f"Detaljene ligger i serverloggen."}


@app.get("/api/auth/config")
async def auth_config() -> dict:
    """Det nettleseren trenger for å logge inn. Den eneste ruten uten innlogging."""
    return auth.public_config()


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
        "scheduler": scheduler.running(),
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
        return _panel(exc, "Verktøylista")


def _open_database() -> None:
    """Create or upgrade the database, and import the JSON files the first time.

    Unlike the checks below, a failure here stops the server: an app that
    cannot remember would serve a CFO that forgets every decision, and a
    half-run migration is better looked at than worked around.
    """
    try:
        cid = db.company_id()
    except Exception:
        log.critical("Databasen %s kunne ikke åpnes eller oppgraderes", db.PATH)
        raise
    log.info("Database: %s, selskap %d", db.PATH.name, cid)


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
    _open_database()
    job_runs.close_orphans()
    await _check_definitions()
    await _check_toolset()
    scheduler.start()
    yield
    await scheduler.stop()
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
        return _panel(exc, "Nøkkeltallene")
    data["company"] = config.COMPANY_NAME
    return data


@app.get("/api/preflight")
async def preflight() -> dict:
    """Om bøkene er ajour. Samme kontroll som agenten leser før den svarer."""
    try:
        return await preflight_cached()
    except Exception as exc:  # noqa: BLE001
        log.exception("Preflight failed")
        return _panel(exc, "Tilstanden i regnskapet")


@app.get("/api/commitments")
async def commitments() -> dict:
    """Hvor mye av pengene på konto som faktisk er selskapets."""
    try:
        return await commitments_cached()
    except Exception as exc:  # noqa: BLE001
        log.exception("Commitments failed")
        return _panel(exc, "Forpliktelsene")


@app.get("/api/cashflow")
async def cashflow() -> dict:
    """Tretten uker fram: hva som kommer inn, hva som skal ut, og når det er tynnest."""
    try:
        return await cashflow_cached()
    except Exception as exc:  # noqa: BLE001
        log.exception("Cashflow failed")
        return _panel(exc, "Kontantstrømmen")


@app.get("/api/rules")
async def rules() -> dict:
    """Selskapets regler slik beregningene bruker dem nå.

    Gulvet regnes mot prognosens månedslønn, så forsiden og sakene måler mot
    det samme tallet. Kan ikke prognosen bygges, svarer dette likevel — da står
    gulvet på standardverdien, og `basis` sier det."""
    try:
        cf = await cashflow_cached()
    except Exception as exc:  # noqa: BLE001 — reglene skal kunne leses uansett
        log.warning("Reglene uten prognose: %s", exc)
        cf = None
    return {"rules": cashflow_rules(cf)}


@app.get("/api/summary")
async def summary(refresh: bool = False) -> dict:
    """Hvordan det går, skrevet av CFO-en. Ett modellkall per dag; refresh=true
    tvinger en ny tekst."""
    try:
        return await summary_cached(refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        log.exception("Summary failed")
        return _panel(exc, "Oppsummeringen")


@app.get("/api/brief")
async def weekly_brief() -> dict:
    """Mandagsbrevet: det siste som ble skrevet, og om det er denne ukas.
    Skrives av planleggeren; for hånd med POST /api/schedule/weekly_brief/run."""
    try:
        return {"brief": brief.latest()}
    except Exception as exc:  # noqa: BLE001
        log.exception("Mandagsbrevet kunne ikke leses")
        return _panel(exc, "Mandagsbrevet")


@app.get("/api/dashboard")
async def dashboard(refresh: bool = False) -> dict:
    """Bransjen selskapet er i, og nøkkeltallene som betyr noe i den bransjen.

    Bransjen bestemmes én gang og leses deretter fra disk; refresh=true tvinger
    en ny vurdering."""
    try:
        return await industry_dashboard(refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        log.exception("Dashboard failed")
        return _panel(exc, "Bransjetallene")


@app.get("/api/cards")
async def get_cards(refresh: bool = True) -> dict:
    """Arbeidet som ligger klart til godkjenning.

    Bygges på nytt som standard, slik at forsiden viser det som gjelder nå og
    ikke det som gjaldt sist noen spurte."""
    try:
        return await cards.refresh() if refresh else cards.deck()
    except Exception as exc:  # noqa: BLE001
        log.exception("Cards failed")
        return _panel(exc, "Sakene")


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
        past = definitions.history(id)
        if not past:
            raise HTTPException(404, f"Ingen definisjon med id «{id}».")
        return {"id": id, "history": past}
    try:
        ledger = definitions.registry()
    except Exception as exc:  # noqa: BLE001
        log.exception("Definitions registry failed")
        return _panel(exc, "Definisjonene")
    return {**definitions.stamp(),
            "definitions": {k: {"version": h[-1]["version"],
                                "label": h[-1]["label"],
                                "formula": h[-1]["formula"],
                                "since": h[-1]["recorded"],
                                "revisions": len(h)}
                            for k, h in sorted(ledger.items()) if h}}


@app.get("/api/trace")
async def trace_account(
    account: int = Query(gt=0, description="Kontonummer, positivt"),
    date_from: str = Query(...),
    date_to: str = Query(...),
) -> dict:
    """Posteringene bak en saldo. Sluttdato er inklusiv, slik folk mener den."""
    parsed = {}
    for label, value in (("date_from", date_from), ("date_to", date_to)):
        try:
            parsed[label] = date.fromisoformat(value)
        except ValueError:
            raise HTTPException(400, f"{label} må være YYYY-MM-DD, fikk «{value}»") from None
    # Caught here rather than upstream: Tripletex rejects a reversed range with a
    # message about the exclusive end date it never saw, which reads as our bug.
    if parsed["date_from"] > parsed["date_to"]:
        raise HTTPException(400, f"date_from ({date_from}) kan ikke være etter "
                                 f"date_to ({date_to}).")
    try:
        return await trace.account(account, date_from, date_to)
    except Exception as exc:  # noqa: BLE001
        # A failed call is not a result. Returning 200 with an error body let a
        # client treat the rejection as data.
        log.exception("Trace failed")
        raise HTTPException(502, f"Oppslaget mot Tripletex feilet: {exc}") from exc


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


@app.get("/api/forecast-accuracy")
async def forecast_accuracy() -> dict:
    """How close each Monday's forecast came, 1, 2 and 4 weeks later."""
    try:
        return scoring.track_record()
    except Exception as exc:  # noqa: BLE001
        log.exception("Treffsikkerheten feilet")
        return _panel(exc, "Treffsikkerheten")


@app.get("/api/job-runs")
async def runs(job: str | None = None,
               limit: int = Query(50, ge=1, le=500)) -> dict:
    """What ran, newest first: status, tokens, cost and figures without a source."""
    rows = job_runs.recent(job, limit)
    return {"runs": rows,
            "cost_usd": round(sum(r["cost_usd"] or 0 for r in rows), 4),
            "failed": sum(r["status"] == "failed" for r in rows)}


@app.get("/api/schedule")
async def schedule() -> dict:
    """What runs on its own, when it runs next, and whether the last run did
    its job. `attention` is the sentence the front page shows when not."""
    return scheduler.status()


@app.post("/api/schedule/{name}/run")
async def run_scheduled(name: str) -> dict:
    """Run a scheduled job now, by hand. Answers when it is done."""
    try:
        j = scheduler.job(name)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        return await scheduler.run(j, triggered_by="user")
    except scheduler.Busy as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/presets")
async def presets() -> dict:
    return {"presets": [{"id": p["id"], "label": p["label"]} for p in PRESETS]}


@app.post("/api/session/reset")
async def reset(session_id: str) -> dict:
    conversations.delete(session_id)
    return {"ok": True}


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY er ikke satt.")

    session_id = req.session_id or uuid.uuid4().hex
    # From the database, already trimmed to open on a real question. A turn
    # that failed or was interrupted was never saved, so there is no
    # unanswered question left to stack the new one under.
    history = conversations.load(session_id)

    # A preset id sent as the message body expands to its full prompt.
    text = next((p["prompt"] for p in PRESETS if p["id"] == req.message), req.message)
    history.append({"role": "user", "content": text})
    asked = len(history) - 1

    async def stream():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
        try:
            async for event in run_turn(history):
                if event.get("type") == "done":
                    # Saved once the answer is whole — the question and
                    # everything the answer produced, in one transaction — and
                    # before the last event goes out, so a browser that closes
                    # on "done" cannot cost the conversation its last turn.
                    try:
                        conversations.append(session_id, history[asked:],
                                             job_run_id=event.get("job_run_id"))
                    except Exception:  # noqa: BLE001 — he has the answer
                        log.exception("Kunne ikke lagre samtalen %s", session_id)
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
