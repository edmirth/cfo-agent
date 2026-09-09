"""The CFO agent: Claude, the Tripletex tools, and a Python sandbox.

Tripletex tools run here in-process, authenticated per customer with the
consumer + employee token pair. Code execution runs server-side at Anthropic so
the agent can build forecasts and scenarios on figures it just pulled.
"""
import logging
from typing import AsyncIterator

from anthropic import AsyncAnthropic, BadRequestError

import config
import tools as tooling
from prompt import system_prompt
from tripletex import TripletexClient, TripletexError

log = logging.getLogger("cfo.agent")

client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

_tlx: TripletexClient | None = None

# Turned off permanently if this account rejects the parameter, so a deployment
# without the beta still runs instead of failing every request.
_fallbacks_enabled = True

CODE_TOOL = {"type": "code_execution_20260521", "name": "code_execution"}
TOOL_NAMES = {t["name"] for t in tooling.TOOLS}
TOOL_BLOCK_TYPES = {
    "tool_use", "server_tool_use",
    "code_execution_tool_use", "bash_code_execution_tool_use",
}


def tripletex() -> TripletexClient:
    global _tlx
    if _tlx is None:
        _tlx = TripletexClient(config.TRIPLETEX_CONSUMER_TOKEN, config.TRIPLETEX_EMPLOYEE_TOKEN)
    return _tlx


def _request_kwargs(messages: list[dict]) -> dict:
    betas = ["code-execution-2025-08-25"]
    kwargs: dict = {
        "model": config.CFO_MODEL,
        "max_tokens": config.MAX_TOKENS,
        "system": system_prompt(),
        "messages": messages,
        "tools": [*tooling.TOOLS, CODE_TOOL],
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": config.CFO_EFFORT},
    }
    if _fallbacks_enabled:
        betas.append("server-side-fallback-2026-07-01")
        kwargs["fallbacks"] = "default"
    kwargs["betas"] = betas
    return kwargs


async def run_turn(messages: list[dict]) -> AsyncIterator[dict]:
    """Stream one assistant turn, yielding UI events.

    Mutates `messages` in place with the assistant and tool-result turns it
    produces, so the caller's history is correct when this returns.
    """
    global _fallbacks_enabled

    for _ in range(config.MAX_TOOL_ROUNDS):
        try:
            final = None
            async with client.beta.messages.stream(**_request_kwargs(messages)) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type in TOOL_BLOCK_TYPES:
                            name = getattr(block, "name", "") or block.type
                            yield {"type": "tool", "label": tooling.label(name), "name": name}
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
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
            log.exception("Request rejected")
            yield {"type": "error", "message": f"Forespørselen ble avvist: {detail}"}
            return

        if final is None:
            yield {"type": "error", "message": "Tomt svar fra modellen."}
            return

        messages.append({"role": "assistant", "content": final.content})

        if final.stop_reason == "refusal":
            yield {"type": "error",
                   "message": "Modellen avslo forespørselen. Formuler spørsmålet på nytt."}
            return

        if final.stop_reason == "pause_turn":
            continue  # a server tool paused the turn; resume it

        if final.stop_reason == "tool_use":
            calls = [b for b in final.content
                     if getattr(b, "type", None) == "tool_use" and b.name in TOOL_NAMES]
            if not calls:
                # Only server-side tools were used; nothing for us to execute.
                continue

            try:
                tlx = tripletex()
            except TripletexError as exc:
                yield {"type": "error", "message": str(exc)}
                return

            results = []
            for call in calls:
                args = call.input if isinstance(call.input, dict) else {}
                yield {"type": "tool", "label": tooling.label(call.name, args), "name": call.name}
                payload = await tooling.dispatch(tlx, call.name, args)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": payload,
                    "is_error": payload.startswith('{"error"'),
                })
            # All results for one assistant turn go back in a single user message.
            messages.append({"role": "user", "content": results})
            continue

        yield {"type": "done",
               "usage": {"input": final.usage.input_tokens, "output": final.usage.output_tokens}}
        return

    yield {"type": "error", "message": "Turen ble avbrutt etter for mange verktøyrunder."}
