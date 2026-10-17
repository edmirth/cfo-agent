"""One way to run an AI job: Claude, the read-only toolset, and the checks.

Every job the product does with a model — the chat, the front-page summary,
the industry classification, and the brief, watch and health check still to
come — needs the same machinery: a client, a tool loop, the local tools it is
allowed and no others, `verify` on every figure in the answer, a turn that
rolls back when it does not finish, and a record of what it cost. Built once
here, and a job is described rather than re-implemented:

    Job(name, system, tools, tripletex, output)

`stream` runs one and yields events as they happen (the chat). `complete`
runs one to the end and hands back the text, or the parsed JSON (everything
else).

Tripletex tool calls are executed by Anthropic through the MCP connector, and
code execution runs server-side too, which is what lets the agent build a
forecast on figures it just pulled. Which Tripletex tools exist at all for the
model is decided in `toolset.py` — reads only, by name.
"""
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from anthropic import (APIConnectionError, APIError, AsyncAnthropic,
                       AuthenticationError, BadRequestError, OverloadedError,
                       PermissionDeniedError, RateLimitError)

import config
import db
import job_runs
import toolset
import verify
from agent import tools
from labels import label
from tlx_oauth import OAuthError, tokens

log = logging.getLogger("cfo.agent")

client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

# Turned off permanently if this account rejects the parameter, so a deployment
# without the beta still runs instead of failing every request.
_fallbacks_enabled = True

CODE_TOOL = {"type": "code_execution_20260521", "name": "code_execution"}
TOOL_BLOCK_TYPES = {
    "tool_use", "server_tool_use", "mcp_tool_use",
    "code_execution_tool_use", "bash_code_execution_tool_use",
}

# USD per million tokens, input and output, first-party API rates. Cache reads
# are billed at a tenth of input, five-minute cache writes at 1.25×. A model
# not listed is logged without a cost rather than with a guessed one.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0), "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0), "claude-opus-4-7": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0), "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0), "claude-haiku-4-5": (1.0, 5.0),
}
CACHE_READ, CACHE_WRITE = 0.1, 1.25


# How a run ended, in the log's words and in the job_runs status.
OUTCOMES = {"ok": "ferdig", "partial": "kuttet", "failed": "feilet"}


def _demo_tools() -> frozenset:
    from demo.tripletex import AGENT_TOOL_NAMES
    return AGENT_TOOL_NAMES


async def _demo_call(name: str, args: dict) -> str:
    """A Tripletex tool in demo mode, answered from the demo's books."""
    from mcp_client import mcp
    try:
        return json.dumps(await mcp.call(name, args), ensure_ascii=False, default=str)
    except Exception as e:  # noqa: BLE001 — a refused call is the model's to read
        return f"Error: {e}"


@dataclass(frozen=True)
class Job:
    """What a job is: its prompt, what it may use, and what it must produce.

    `system` is awaited per request, so figures in it are as fresh as the
    caches behind it. `tools` names the local tools the job may call; nothing
    outside it is offered, and a call to anything outside it is refused.
    `tripletex` opens the read-only Tripletex toolset and the Python sandbox.
    `output` is "text" or "json"; `complete` parses the latter and fails the
    job when the answer is not JSON.
    """
    name: str
    system: Callable[[], Awaitable[list[dict]]] | None = None
    tools: frozenset[str] = frozenset()
    tripletex: bool = False
    output: str = "text"
    max_tokens: int = config.MAX_TOKENS
    effort: str | None = None
    thinking: dict | None = None
    max_rounds: int = config.MAX_TOOL_ROUNDS
    # How the evidence is labelled when a figure is traced back to it.
    prompt_source: str = "det du skrev"
    system_source: str = "forsiden (beregnet her)"

    def __post_init__(self):
        tools.pick(self.tools)          # an unknown tool name fails at import
        if self.output not in ("text", "json"):
            raise ValueError(f"Ukjent output for jobb {self.name}: {self.output}")


class JobError(RuntimeError):
    """A job that did not produce its output. The message is the provider's
    own where there is one, so callers can tell a billing stop from a bug."""


@dataclass
class Result:
    text: str
    data: dict | None
    check: dict
    usage: dict = field(default_factory=dict)


CUT_KEEP_CHARS = 4000           # of a cut-off answer, kept in job_runs.details

# Stop reasons that end the answer before the model meant to. Without these
# the turn went straight to "done", and the CEO read half an answer as a whole.
CUT_OFF = {
    "max_tokens": ("Svaret ble kuttet fordi det ble for langt, og er ikke "
                   "fullstendig. Be om resten, eller still et smalere spørsmål."),
    "model_context_window_exceeded": (
        "Samtalen er blitt så lang at svaret ikke fikk plass, og det er ikke "
        "fullstendig. Start en ny samtale for å fortsette."),
}


def _answered_only(content: list) -> list:
    """The assistant turn without tool calls that never got a result.

    A turn cut off mid-call stores a tool_use with nothing answering it, and
    the API rejects every later request on the session until it is gone.
    Server-side calls carry their result in the same message; a client-side
    tool_use never does, so on a cut-off turn it is always dropped.
    """
    answered = {getattr(b, "tool_use_id", None) for b in content}
    kept = [b for b in content
            if getattr(b, "type", None) not in TOOL_BLOCK_TYPES
            or getattr(b, "id", None) in answered]
    return kept or [{"type": "text", "text": "(Svaret ble avbrutt.)"}]


async def _request_kwargs(job: Job, messages: list[dict]) -> dict:
    kwargs: dict = {"model": config.CFO_MODEL, "max_tokens": job.max_tokens,
                    "messages": messages}
    betas: list[str] = []
    if job.system:
        # The breakpoint sits inside the job's system blocks, on the part that
        # repeats identically on every tool round.
        kwargs["system"] = await job.system()
    offered: list[dict] = []
    if job.tripletex and config.DEMO:
        # Demo mode: the books are on this machine, which Anthropic's MCP
        # connector cannot reach. The same read tools run here instead, as
        # ordinary tools answered by the demo's Tripletex (backend/demo/).
        from demo.tripletex import AGENT_TOOLS
        betas += ["code-execution-2025-08-25"]
        offered += AGENT_TOOLS + [CODE_TOOL]
    elif job.tripletex:
        # The Tripletex toolset is closed by default and opened tool by tool
        # in toolset.py. A write tool is not offered to the model at all, so
        # read-only stops depending on the model choosing to obey.
        betas += ["code-execution-2025-08-25", "mcp-client-2025-11-20"]
        offered += [toolset.toolset("tripletex"), CODE_TOOL]
        kwargs["mcp_servers"] = [{
            "type": "url",
            "url": config.TRIPLETEX_MCP_URL,
            "name": "tripletex",
            "authorization_token": await tokens.access_token(),
        }]
    offered += tools.pick(job.tools)
    if offered:
        kwargs["tools"] = offered
    if job.thinking:
        kwargs["thinking"] = job.thinking
    if job.effort:
        kwargs["output_config"] = {"effort": job.effort}
    if _fallbacks_enabled:
        betas.append("server-side-fallback-2026-07-01")
        kwargs["fallbacks"] = "default"
    kwargs["betas"] = betas
    return kwargs


def cost(usage: dict, model: str | None = None) -> float | None:
    """USD for this usage at first-party rates, or None for an unpriced model."""
    price = PRICES.get(model or config.CFO_MODEL)
    if not price:
        return None
    p_in, p_out = price
    return (usage.get("input", 0) * p_in
            + usage.get("cache_read", 0) * p_in * CACHE_READ
            + usage.get("cache_write", 0) * p_in * CACHE_WRITE
            + usage.get("output", 0) * p_out) / 1_000_000


def _log_run(job: Job, run_id: int | None, run: dict, status: str) -> None:
    """Say what the run cost and how it ended — in the log and in job_runs."""
    usage, usd = run["usage"], cost(run["usage"])
    log.info("jobb %s %s: %d runder, %d inn, %d ut, cache %d lest / %d skrevet, "
             "%s, %s tall uten kilde",
             job.name, OUTCOMES[status], run["rounds"], usage["input"],
             usage["output"], usage["cache_read"], usage["cache_write"],
             f"{usd:.4f} USD" if usd is not None else "ukjent pris",
             "?" if run["unverified"] is None else run["unverified"])
    job_runs.finish(run_id, status, usage=usage, cost_usd=usd,
                    unverified=run["unverified"], error=run.get("error"),
                    details={"rounds": run["rounds"],
                             "cache_write_tokens": usage["cache_write"],
                             "stop_reason": run.get("stop_reason"),
                             **({"cut_off": run["cut_off"]} if run.get("cut_off") else {})})


async def stream(job: Job, messages: list[dict], *, raise_errors: bool = False,
                 triggered_by: str | None = None) -> AsyncIterator[dict]:
    """Run one turn of `job`, yielding UI events.

    Mutates `messages` in place with the assistant turns it produces, so the
    caller's history is correct when this returns — and only then: an
    interrupted turn is rolled back entirely.

    With `raise_errors`, a rejected request raises with the provider's own
    message instead of yielding the sentence meant for the CEO's screen.

    Every run is recorded in `job_runs` — opened as running, closed with what
    it cost — and its id is in `db.job_run` while it works, so what it writes
    carries it. The `done` event carries it too, for the caller to file the
    turn under. Without `triggered_by` the run is filed under whoever set
    `job_runs.trigger` — the scheduler, or else the user.
    """
    # Everything the agent is given this turn, so the figures in its answer can
    # be traced back to a source afterwards.
    corpus = verify.Corpus()
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            corpus.add(m["content"], job.prompt_source)
    run = {"usage": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0},
           "rounds": 0, "unverified": None}

    # A turn that does not finish must not leave half of itself in the
    # history. An assistant message ending in a tool call with no result, or
    # a paused server turn, makes every later request on the session fail —
    # and a client closing the tab mid-answer is the ordinary way to get one.
    start = len(messages)
    completed = False
    run_id = job_runs.start(job.name, triggered_by, config.CFO_MODEL)
    token = db.job_run.set(run_id)
    try:
        async for event in _turn(job, messages, corpus, run, raise_errors):
            if event.get("type") == "done":
                completed = True
                event = {**event, "job_run_id": run_id}
            elif event.get("type") == "error":
                run.setdefault("error", event.get("message"))
            yield event
    except BaseException as exc:
        run.setdefault("error", str(exc) or type(exc).__name__)
        raise
    finally:
        if not completed:
            del messages[start:]
            run.setdefault("error", "avbrutt før svaret var ferdig")
        status = ("failed" if not completed
                  else "partial" if run.get("stop_reason") in CUT_OFF else "ok")
        _log_run(job, run_id, run, status)
        try:
            db.job_run.reset(token)
        except ValueError:
            # An abandoned stream is closed from another context; there is
            # nothing of this run's left to reset there.
            db.job_run.set(None)


async def _turn(job, messages, corpus, run, raise_errors) -> AsyncIterator[dict]:
    global _fallbacks_enabled
    system_seen = False
    said: list[str] = []

    for _ in range(job.max_rounds):
        try:
            kwargs = await _request_kwargs(job, messages)
        except OAuthError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        if not system_seen:
            # The condition, commitments, forecast and memory blocks are
            # figures this server computed; quoting them is quoting a source.
            for block in kwargs.get("system") or []:
                corpus.add(block.get("text", ""), job.system_source)
            system_seen = True

        try:
            final = None
            async with client.beta.messages.stream(**kwargs) as s:
                async for event in s:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type in TOOL_BLOCK_TYPES:
                            name = getattr(block, "name", "") or block.type
                            yield {"type": "tool", "label": label(name), "name": name}
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            said.append(delta.text)
                            yield {"type": "text", "text": delta.text}
                        elif delta.type == "thinking_delta":
                            yield {"type": "reasoning", "text": delta.thinking}
                final = await s.get_final_message()

        except BadRequestError as exc:
            detail = str(exc)
            if _fallbacks_enabled and "fallback" in detail.lower():
                log.warning("Disabling server-side fallbacks: %s", detail)
                _fallbacks_enabled = False
                continue
            log.exception("Request rejected (%s)", job.name)
            if raise_errors:
                raise JobError(detail) from exc
            # The full provider error — request id, billing links, internals —
            # belongs in the log, not on the CEO's screen. Out of credits is the
            # one case worth naming, because only the owner can fix it.
            if "credit balance is too low" in detail:
                shown = ("Anthropic-kontoen er tom for kreditt, så modellen "
                         "svarer ikke. Tallene på forsiden virker fortsatt.")
            else:
                shown = ("Modellen avviste forespørselen. Detaljene ligger i "
                         "serverloggen.")
            yield {"type": "error", "message": shown}
            return
        except APIError as exc:
            # Everything else the provider can answer with: busy, a dropped
            # connection, a key that no longer works. Only the bad request was
            # caught before, and the rest reached the CEO's screen as the
            # provider's own text, request id and all.
            log.exception("Modellkallet feilet (%s)", job.name)
            if raise_errors:
                raise JobError(str(exc)) from exc
            yield {"type": "error", "message": _plain_error(exc)}
            return

        if final is None:
            yield {"type": "error", "message": "Tomt svar fra modellen."}
            return

        run["rounds"] += 1
        u = final.usage
        round_usage = {
            "input": u.input_tokens, "output": u.output_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
        }
        for k, v in round_usage.items():
            run["usage"][k] += v

        run["stop_reason"] = final.stop_reason
        cut = CUT_OFF.get(final.stop_reason)
        if cut:
            # Kept so a cut-off answer can be read afterwards: what it had
            # written, and what else spent the budget (thinking, tool calls).
            # Thrown away, the only trace was "700 out", and no way to tell a
            # cap set too low from an answer that ran on.
            run["cut_off"] = {
                "blocks": [b.type for b in final.content],
                "text": "".join(getattr(b, "text", "") or "" for b in final.content
                                if b.type == "text")[:CUT_KEEP_CHARS]}
            log.warning("jobb %s kuttet ved %s: %s", job.name, final.stop_reason,
                        run["cut_off"]["text"][:300])
        messages.append({"role": "assistant",
                         "content": _answered_only(final.content) if cut
                         else final.content})
        # Tool results are the evidence: what Tripletex actually returned, and
        # each one keeps the name of the call that produced it.
        for where, text in verify.sources(final.content, run.setdefault("names", {})):
            corpus.add(text, where)

        if final.stop_reason == "refusal":
            yield {"type": "error",
                   "message": "Modellen avslo forespørselen. Formuler spørsmålet på nytt."}
            return

        if final.stop_reason == "pause_turn":
            continue  # a server tool paused the turn; resume it

        if final.stop_reason == "tool_use":
            # Every block must be answered in the same user turn, including
            # one we do not run — an unanswered tool_use is rejected on the
            # next request. A tool the job was not given is refused, whatever
            # the model was told: the list it was offered is the permission.
            results = []
            for b in final.content:
                if getattr(b, "type", None) != "tool_use":
                    continue
                if b.name in job.tools:
                    text = await tools.run(b.name, b.input or {})
                elif config.DEMO and job.tripletex and b.name in _demo_tools():
                    text = await _demo_call(b.name, b.input or {})
                else:
                    log.error("Jobb %s kalte et verktøy den ikke har: %s",
                              job.name, b.name)
                    text = f"No such tool: {b.name}."
                corpus.add(text, f"{b.name} (regnet ut her)")
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": text})
            messages.append({"role": "user", "content": results})
            continue

        check = verify.check("".join(said), corpus)
        run["unverified"] = len(check["unverified"])
        if check["unverified"]:
            log.warning("Svaret inneholder %d tall uten kilde",
                        len(check["unverified"]))
        for t in check["traced"][:6]:
            log.info("spor: %s ← %s", verify.fmt(t["value"]),
                     ", ".join(t["from"]))
        yield {"type": "check", **check}
        if cut:
            # After the text, so it reads as a note on the answer, not instead
            # of it. Both frontends show an error below what was written.
            log.warning("Svaret stoppet på %s", final.stop_reason)
            yield {"type": "error", "message": cut}

        yield {"type": "done", "usage": round_usage}
        return

    yield {"type": "error", "message": "Turen ble avbrutt etter for mange verktøyrunder."}


def _plain_error(exc: APIError) -> str:
    """What the CEO is told when the model could not be reached. The
    provider's words stay in the log."""
    if isinstance(exc, (OverloadedError, RateLimitError)) or "overloaded" in str(exc).lower():
        return "Modellen er travel akkurat nå. Prøv igjen om et par minutter."
    if isinstance(exc, APIConnectionError):
        return "Fikk ikke kontakt med modellen. Prøv igjen om litt."
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return ("Nøkkelen til Anthropic virker ikke lenger, så modellen svarer "
                "ikke. Tallene på forsiden virker fortsatt.")
    return "Modellen svarte med en feil. Detaljene ligger i serverloggen."


def parse_json(text: str, what: str) -> dict:
    """The JSON object in an answer, tolerating prose around it."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise JobError(f"{what} svarte ikke med JSON: {text[:200]}")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise JobError(f"{what} svarte med ugyldig JSON: {exc}") from exc


async def complete(job: Job, prompt: str | list[dict],
                   triggered_by: str | None = None) -> Result:
    """Run `job` to the end and return what it produced.

    For jobs that are not a conversation: the summary, the classification, and
    the brief, watch and health check to come. A cut-off or failed answer
    raises — a half-written summary on the front page is worse than none.
    """
    messages = ([{"role": "user", "content": prompt}] if isinstance(prompt, str)
                else prompt)
    text, check, usage, problems = [], {}, {}, []
    async for event in stream(job, messages, raise_errors=True,
                              triggered_by=triggered_by):
        kind = event["type"]
        if kind == "text":
            text.append(event["text"])
        elif kind == "check":
            check = {k: v for k, v in event.items() if k != "type"}
        elif kind == "error":
            problems.append(event["message"])
        elif kind == "done":
            usage = event["usage"]
    if problems:
        raise JobError(" ".join(problems))
    out = "".join(text)
    data = parse_json(out, job.name) if job.output == "json" else None
    return Result(text=out, data=data, check=check, usage=usage)
