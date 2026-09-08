"""The CFO agent: Claude with the Tripletex MCP server and a Python sandbox.

Tool calls against Tripletex are executed by Anthropic server-side through the
MCP connector, so there is no tool-execution loop to maintain here. We stream
the turn and forward three things to the browser: assistant text, a summary of
Claude's reasoning, and a live feed of which Tripletex report is being opened.
"""
import logging
from typing import AsyncIterator

from anthropic import AsyncAnthropic, BadRequestError

import config
from prompt import system_prompt

log = logging.getLogger("cfo.agent")

client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

# Flipped off permanently if this account/model rejects the parameter, so a
# deployment without the beta still runs instead of failing every request.
_fallbacks_enabled = True

# Norwegian labels for the tool feed. Anything unmapped falls back to the raw
# tool name, which is still more useful to a CFO than a spinner.
TOOL_LABELS = {
    "fetch_report": "Henter rapport fra Tripletex",
    "get_report_details": "Slår opp rapportdefinisjon",
    "get_balance_sheet": "Henter saldobalanse",
    "search_ledger_postings": "Søker i hovedboken",
    "search_invoices": "Henter utgående fakturaer",
    "search_supplier_invoices": "Henter leverandørfakturaer",
    "search_customers": "Slår opp kunder",
    "search_employees": "Slår opp ansatte",
    "search_projects": "Slår opp prosjekter",
    "search_hour_entries": "Henter timeføringer",
    "search_result_budgets": "Henter budsjett",
    "get_voucher_inbox_count": "Sjekker bilagsinnboks",
    "get_supplier_invoices_for_approval": "Sjekker fakturaer til godkjenning",
    "logged_in_user_info": "Bekrefter selskapskontekst",
    "list_active_companies": "Slår opp selskap",
    "tripletex_run_script": "Kjører spørring mot Tripletex",
    "code_execution": "Regner i Python",
    "bash_code_execution": "Regner i Python",
}

TOOL_BLOCK_TYPES = {
    "mcp_tool_use",
    "server_tool_use",
    "tool_use",
    "code_execution_tool_use",
    "bash_code_execution_tool_use",
}


def _tools() -> list[dict]:
    return [
        {"type": "mcp_toolset", "mcp_server_name": "tripletex"},
        {"type": "code_execution_20260521", "name": "code_execution"},
    ]


def _mcp_servers() -> list[dict]:
    server: dict = {
        "type": "url",
        "url": config.TRIPLETEX_MCP_URL,
        "name": "tripletex",
    }
    if config.TRIPLETEX_MCP_TOKEN:
        server["authorization_token"] = config.TRIPLETEX_MCP_TOKEN
    return [server]


def _request_kwargs(messages: list[dict]) -> dict:
    betas = ["mcp-client-2025-11-20", "code-execution-2025-08-25"]
    kwargs: dict = {
        "model": config.CFO_MODEL,
        "max_tokens": config.MAX_TOKENS,
        "system": system_prompt(),
        "messages": messages,
        "tools": _tools(),
        "mcp_servers": _mcp_servers(),
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": config.CFO_EFFORT},
    }
    if _fallbacks_enabled:
        betas.append("server-side-fallback-2026-07-01")
        kwargs["fallbacks"] = "default"
    kwargs["betas"] = betas
    return kwargs


def _label(name: str) -> str:
    return TOOL_LABELS.get(name, name.replace("_", " "))


async def run_turn(messages: list[dict]) -> AsyncIterator[dict]:
    """Stream one assistant turn, yielding UI events.

    Mutates `messages` in place with the assistant turns it produces, so the
    caller's conversation history is correct when this returns.
    """
    global _fallbacks_enabled

    # A server tool can pause a turn mid-flight; resume until it settles.
    for _ in range(10):
        try:
            final = None
            async with client.beta.messages.stream(**_request_kwargs(messages)) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type in TOOL_BLOCK_TYPES:
                            name = getattr(block, "name", "") or block.type
                            yield {"type": "tool", "label": _label(name), "name": name}
                        elif block.type == "text":
                            yield {"type": "text_start"}
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
                # This account/model does not take the fallbacks parameter.
                # Drop it for the rest of the process and retry once.
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
            yield {
                "type": "error",
                "message": "Modellen avslo forespørselen. Formuler spørsmålet på nytt.",
            }
            return

        if final.stop_reason == "pause_turn":
            continue  # resume the paused turn with history intact

        yield {
            "type": "done",
            "usage": {
                "input": final.usage.input_tokens,
                "output": final.usage.output_tokens,
            },
        }
        return

    yield {"type": "error", "message": "Turen ble avbrutt etter for mange runder."}
