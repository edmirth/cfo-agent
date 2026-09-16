"""The CFO agent: Claude, Tripletex over MCP, and a Python sandbox.

Tripletex tool calls are executed by Anthropic through the MCP connector, so
there is no tool-execution loop here. Code execution runs server-side too, which
is what lets the agent build a forecast on figures it just pulled.
"""
import logging
from typing import AsyncIterator

from anthropic import AsyncAnthropic, BadRequestError

import config
from labels import label
from prompt import system_prompt
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


async def _request_kwargs(messages: list[dict]) -> dict:
    betas = ["code-execution-2025-08-25", "mcp-client-2025-11-20"]
    kwargs: dict = {
        "model": config.CFO_MODEL,
        "max_tokens": config.MAX_TOKENS,
        # One cache breakpoint here covers the tool definitions and the system
        # prompt — the part that repeats identically on every tool round.
        "system": [{"type": "text", "text": system_prompt(),
                    "cache_control": {"type": "ephemeral"}}],
        "messages": messages,
        "tools": [{"type": "mcp_toolset", "mcp_server_name": "tripletex"}, CODE_TOOL],
        "mcp_servers": [{
            "type": "url",
            "url": config.TRIPLETEX_MCP_URL,
            "name": "tripletex",
            "authorization_token": await tokens.access_token(),
        }],
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

    Mutates `messages` in place with the assistant turns it produces, so the
    caller's history is correct when this returns.
    """
    global _fallbacks_enabled

    for _ in range(config.MAX_TOOL_ROUNDS):
        try:
            kwargs = await _request_kwargs(messages)
        except OAuthError as exc:
            yield {"type": "error", "message": str(exc)}
            return

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
            # Every tool here is server-side, so this should not happen. Stop
            # rather than loop: replaying an unanswered tool_use is rejected.
            names = [getattr(b, "name", "?") for b in final.content
                     if getattr(b, "type", None) == "tool_use"]
            log.error("Unexpected client-side tool_use: %s", names)
            yield {"type": "error",
                   "message": "Modellen ba om et verktøy som ikke finnes her. Prøv igjen."}
            return

        u = final.usage
        yield {"type": "done", "usage": {
            "input": u.input_tokens, "output": u.output_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
        }}
        return

    yield {"type": "error", "message": "Turen ble avbrutt etter for mange verktøyrunder."}
