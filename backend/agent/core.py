"""The CFO agent itself, and the one place this server talks to Anthropic.

A job is a piece of work the agent does: answer the CEO in chat, write the
front page's summary, decide the industry. A job is described rather than
coded. A `Job` says what the agent is given, which tools it may use and what
it must hand back, and `run()` does the rest the same way for every job. It
builds the request, offers only the job's tools, runs the tool loop, rolls
back a turn that does not finish, traces every figure in the answer back to
what the agent was given, and logs what the run cost.

Tripletex tool calls are executed by Anthropic through the MCP connector, and
code execution runs server-side too, which is what lets the agent build a
forecast on figures it just pulled. Which Tripletex tools exist at all for the
model is decided in `toolset.py` — reads only, by name. The only tools executed
here are the ones in `agent/tools.py`.
"""
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from anthropic import AsyncAnthropic, BadRequestError

import config
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


@dataclass(frozen=True)
class Job:
    """One kind of agent work: what it is given, and what it hands back."""

    name: str
    # Local tools from agent/tools.py the job may call. Any other tool is
    # never offered to the model, and is not run if the model asks for it.
    tools: tuple[str, ...] = ()
    # The read-only Tripletex toolset and the Python sandbox. Anthropic runs
    # both.
    tripletex: bool = False
    code: bool = False
    # Built again before every round, so a note written mid-turn is in the
    # next one.
    system: Callable[[], Awaitable[list[dict]]] | None = None
    # "text" is the answer as written; "json" is one object, read out of it.
    output: str = "text"
    max_tokens: int = config.MAX_TOKENS
    thinking: dict | None = None
    effort: str | None = None
    # How the prompt is named when a figure in the answer is traced to it.
    given_as: str = "det du skrev"

    def __post_init__(self) -> None:
        tools.definitions(self.tools)          # an unknown name fails at import
        if self.output not in ("text", "json"):
            raise ValueError(f"Ukjent utdata for {self.name}: {self.output}")


# ------------------------------------------------------------------ cost
# USD per million tokens: input, output, cache read. These are Anthropic's
# list prices as of 2026-09. A cache write costs 1.25 x input for the
# five-minute cache this app uses, and 2 x input for the one-hour cache. The
# sandbox and the MCP connector are billed on other meters. So this is the
# token cost of a run, not the whole invoice.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-opus-4-7": (5.00, 25.00, 0.50),
    "claude-opus-4-6": (5.00, 25.00, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
    "claude-fable-5-1": (10.00, 50.00, 0.25),
    "claude-fable-5": (10.00, 50.00, 1.00),
}


def _n(obj, name: str) -> int:
    return int(getattr(obj, name, 0) or 0)


def cost(model: str | None, usage) -> float | None:
    """What one response cost in dollars. None for a model not priced here.

    A model with no price gets None, not 0, because a zero would read as a
    free run.
    """
    price = PRICES.get(model or "")
    if price is None or usage is None:
        return None
    inp, out, read = price
    written = _n(usage, "cache_creation_input_tokens")
    hour = min(_n(getattr(usage, "cache_creation", None),
                  "ephemeral_1h_input_tokens"), written)
    return (_n(usage, "input_tokens") * inp
            + _n(usage, "output_tokens") * out
            + _n(usage, "cache_read_input_tokens") * read
            + (written - hour) * inp * 1.25
            + hour * inp * 2) / 1_000_000


@dataclass
class Outcome:
    """How one run ended and what it cost. Filled in while the job runs."""

    job: str
    # started → done | cut | refused | error, or interrupted / failed
    status: str = "started"
    rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float | None = 0.0
    # None until the answer has been checked. A run that never finished was
    # never checked, which is not the same as nothing unverified.
    unverified: int | None = None
    # The provider's own words. They go to the log and to the caller, never
    # to the screen.
    error: str | None = None
    text: str = ""                       # the final answer's text

    def add(self, message) -> None:
        """Count one response's tokens and its cost.

        With a server-side fallback, the usage covers the attempt that
        answered. An attempt the first model declined is not in it.
        """
        u = getattr(message, "usage", None)
        self.rounds += 1
        self.input_tokens += _n(u, "input_tokens")
        self.output_tokens += _n(u, "output_tokens")
        self.cache_read += _n(u, "cache_read_input_tokens")
        self.cache_write += _n(u, "cache_creation_input_tokens")
        c = cost(getattr(message, "model", None) or config.CFO_MODEL, u)
        self.cost_usd = None if c is None or self.cost_usd is None else self.cost_usd + c


def _log_run(o: Outcome) -> None:
    """One line per run. Card 4 stores the same fields in the job-runs table."""
    spent = f"${o.cost_usd:.4f}" if o.cost_usd is not None else "ukjent pris"
    checked = ("ikke sjekket" if o.unverified is None
               else f"{o.unverified} tall uten kilde")
    log.info("Jobb %s: %s etter %d runde(r) · %d inn, %d fra cache, %d til "
             "cache, %d ut · %s · %s", o.job, o.status, o.rounds,
             o.input_tokens, o.cache_read, o.cache_write, o.output_tokens,
             spent, checked)


# --------------------------------------------------------------- request

async def _request(job: Job, messages: list[dict]) -> dict:
    """The request for one round of a job."""
    kwargs: dict = {"model": config.CFO_MODEL, "max_tokens": job.max_tokens}
    if job.system is not None:
        kwargs["system"] = await job.system()
    kwargs["messages"] = messages

    offered: list[dict] = []
    betas: list[str] = []
    if job.tripletex:
        # The Tripletex toolset is closed by default and opened tool by tool
        # in toolset.py. A write tool is not offered to the model at all, so
        # read-only stops depending on the model choosing to obey.
        offered.append(toolset.toolset("tripletex"))
        kwargs["mcp_servers"] = [{
            "type": "url",
            "url": config.TRIPLETEX_MCP_URL,
            "name": "tripletex",
            "authorization_token": await tokens.access_token(),
        }]
    if job.code:
        offered.append(CODE_TOOL)
        betas.append("code-execution-2025-08-25")
    if job.tripletex:
        betas.append("mcp-client-2025-11-20")
    offered += tools.definitions(job.tools)
    if offered:
        kwargs["tools"] = offered

    if job.thinking is not None:
        kwargs["thinking"] = job.thinking
    if job.effort is not None:
        kwargs["output_config"] = {"effort": job.effort}
    if _fallbacks_enabled:
        betas.append("server-side-fallback-2026-07-01")
        kwargs["fallbacks"] = "default"
    if betas:
        kwargs["betas"] = betas
    return kwargs


# ------------------------------------------------------------------- run

async def run(job: Job, messages: list[dict],
              outcome: Outcome | None = None) -> AsyncIterator[dict]:
    """Run one turn of a job, yielding UI events.

    Mutates `messages` in place with the assistant turns it produces, so the
    caller's history is correct when this returns — and only then: an
    interrupted turn is rolled back entirely. Pass an `Outcome` to read how
    the run ended once it has.
    """
    outcome = outcome if outcome is not None else Outcome(job.name)
    # Everything the agent is given this turn, so the figures in its answer can
    # be traced back to a source afterwards.
    corpus = verify.Corpus()
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            corpus.add(m["content"], job.given_as)

    # A turn that does not finish must not leave half of itself in the
    # history. An assistant message ending in a tool call with no result, or
    # a paused server turn, makes every later request on the session fail —
    # and a client closing the tab mid-answer is the ordinary way to get one.
    start = len(messages)
    completed = False
    try:
        async for event in _turn(job, messages, corpus, outcome):
            if event.get("type") == "done":
                completed = True
            yield event
    except Exception as exc:
        outcome.status, outcome.error = "failed", str(exc)
        raise
    finally:
        if not completed:
            del messages[start:]
            if outcome.status == "started":
                outcome.status = "interrupted"
        _log_run(outcome)


class JobFailed(RuntimeError):
    """A job that did not produce its output.

    The message is the provider's own words. The caller translates it for the
    screen.
    """


async def complete(job: Job, prompt: str):
    """Run a job on one prompt to the end, and return what it produced.

    For a "text" job that is the text it wrote. For a "json" job it is the
    object in that text.
    """
    outcome = Outcome(job.name)
    async for _ in run(job, [{"role": "user", "content": prompt}], outcome):
        pass
    if outcome.status not in ("done", "cut"):
        raise JobFailed(outcome.error or outcome.status)
    if job.output == "text":
        return outcome.text
    raw = outcome.text
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Jobben «{job.name}» svarte ikke med JSON: {raw[:200]}")
    return json.loads(raw[start:end + 1])


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


async def _turn(job: Job, messages: list[dict], corpus: verify.Corpus,
                outcome: Outcome) -> AsyncIterator[dict]:
    global _fallbacks_enabled
    said: list[str] = []
    tool_names: dict[str, str] = {}   # id -> name, kept across rounds
    system_seen = False

    for _ in range(config.MAX_TOOL_ROUNDS):
        try:
            kwargs = await _request(job, messages)
        except OAuthError as exc:
            outcome.status, outcome.error = "error", str(exc)
            yield {"type": "error", "message": str(exc)}
            return

        if not system_seen:
            # The condition, commitments, forecast and memory blocks are
            # figures this server computed; quoting them is quoting a source.
            for block in kwargs.get("system") or []:
                corpus.add(block.get("text", ""), "forsiden (beregnet her)")
            system_seen = True

        try:
            final = None
            async with client.beta.messages.stream(**kwargs) as stream:
                async for event in stream:
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
                final = await stream.get_final_message()

        except BadRequestError as exc:
            detail = str(exc)
            if _fallbacks_enabled and "fallback" in detail.lower():
                log.warning("Disabling server-side fallbacks: %s", detail)
                _fallbacks_enabled = False
                continue
            log.exception("Request rejected (%s)", job.name)
            outcome.status, outcome.error = "error", detail
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

        if final is None:
            outcome.status, outcome.error = "error", "Tomt svar fra modellen."
            yield {"type": "error", "message": "Tomt svar fra modellen."}
            return

        outcome.add(final)
        cut = CUT_OFF.get(final.stop_reason)
        messages.append({"role": "assistant",
                         "content": _answered_only(final.content) if cut
                         else final.content})
        # Tool results are the evidence: what Tripletex actually returned, and
        # each one keeps the name of the call that produced it.
        for where, text in verify.sources(final.content, tool_names):
            corpus.add(text, where)

        if final.stop_reason == "refusal":
            outcome.status, outcome.error = "refused", "refusal"
            yield {"type": "error",
                   "message": "Modellen avslo forespørselen. Formuler spørsmålet på nytt."}
            return

        if final.stop_reason == "pause_turn":
            continue  # a server tool paused the turn; resume it

        if final.stop_reason == "tool_use":
            # Only the local tools run here, and only the ones this job was
            # given. Every block must be answered in the same user turn,
            # including one we refuse — an unanswered tool_use is rejected on
            # the next request.
            results = []
            for b in final.content:
                if getattr(b, "type", None) != "tool_use":
                    continue
                if b.name in job.tools:
                    text = await tools.run(b.name, b.input or {})
                else:
                    log.error("Jobben %s har ikke verktøyet %s", job.name, b.name)
                    text = f"No such tool: {b.name}."
                corpus.add(text, f"{b.name} (regnet ut her)")
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": text})
            messages.append({"role": "user", "content": results})
            continue

        check = verify.check("".join(said), corpus)
        outcome.unverified = len(check["unverified"])
        if check["unverified"]:
            log.warning("Svaret fra %s inneholder %d tall uten kilde",
                        job.name, len(check["unverified"]))
        for t in check["traced"][:6]:
            log.info("spor: %s ← %s", verify.fmt(t["value"]),
                     ", ".join(t["from"]))
        yield {"type": "check", **check}
        outcome.text = "".join(getattr(b, "text", "") for b in final.content
                               if getattr(b, "type", None) == "text")
        if cut:
            # After the text, so it reads as a note on the answer, not instead
            # of it. Both frontends show an error below what was written.
            log.warning("Svaret stoppet på %s", final.stop_reason)
            yield {"type": "error", "message": cut}

        outcome.status = "cut" if cut else "done"
        u = final.usage
        yield {"type": "done", "usage": {
            "input": u.input_tokens, "output": u.output_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
        }}
        return

    outcome.status, outcome.error = "error", "for mange verktøyrunder"
    yield {"type": "error", "message": "Turen ble avbrutt etter for mange verktøyrunder."}
