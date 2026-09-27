"""Builds the CFO system prompt from the shared agent definition.

Two blocks, on purpose. The first is the persona and the standing framework —
identical on every request, so it carries the cache breakpoint and a follow-up
turn reads it rather than paying for it. The second holds what changes: today's
date and the controller's memory. Keeping them apart means writing a finding
mid-conversation costs one small uncached block instead of re-writing the whole
prompt cache.
"""
from datetime import date

import asyncio
import logging

import cards
import cashflow
import company
import definitions
import commitments
import memory
import preflight
from config import AGENT_DEFINITION, COMPANY_NAME

log = logging.getLogger("cfo.prompt")


def _strip_frontmatter(text: str) -> str:
    """Drop the YAML frontmatter Claude Code uses to register the subagent."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4 :].lstrip("\n")


def _persona() -> str:
    """The agent definition plus how this company works.

    Both are stable between turns, so they share the cached block; editing
    either costs one cache write and then nothing.
    """
    body = _strip_frontmatter(AGENT_DEFINITION.read_text(encoding="utf-8"))
    context = company.briefing()
    return f"{body}\n\n{context}" if context else body


def _deployment() -> str:
    return (
        "## This deployment\n\n"
        f"You are the CFO of {COMPANY_NAME}. Today is "
        f"{date.today().isoformat()}.\n\n"
        "You are speaking to the CEO through a chat interface on the company's "
        "own site, not a terminal. Two consequences:\n\n"
        "- Answer in the chat. Write in Markdown — headings, tables and short "
        "paragraphs render properly. Put figures in tables when there is more "
        "than one of them.\n"
        "- Keep a normal question to a normal answer. Do not run the full "
        "standing analysis unless a review was actually asked for.\n\n"
        "You reach Tripletex through connected tools. Call them whenever a "
        "question touches the company's actual numbers — never answer from "
        "memory or from earlier in the conversation when a figure could have "
        "changed since.\n\n"
        "You can also run Python. Use it for modelling the ledger cannot "
        "answer on its own: forecasts, scenarios, sensitivities, budget "
        "models, valuations. Pull the real figures from Tripletex first and "
        "build the model on those — never on invented inputs. Show the "
        "assumptions next to the result, and say which are the CEO's to set."
    )


MISSING = (
    "## {title} — ikke tilgjengelig i dag\n\n"
    "This section could not be computed ({why}). You do not have these "
    "figures. Do not reconstruct them from memory, from an earlier "
    "conversation, or by adjusting a figure you saw before — a number "
    "assembled to fill this gap will look right and be wrong. If the CEO asks "
    "something that depends on it, say plainly that the figure could not be "
    "fetched today and what you would need to answer properly."
)


async def _section(title: str, build) -> str:
    """One computed block, or an explicit statement that it is missing.

    Dropping a failed block silently is what invites invention: the agent sees
    no figures, assumes it simply has to work them out, and produces something
    plausible. Saying the section is unavailable costs a few tokens and closes
    that door.
    """
    try:
        return await build()
    except Exception as exc:  # noqa: BLE001
        log.exception("%s unavailable", title)
        return MISSING.format(title=title, why=str(exc)[:120])


async def _condition() -> str:
    """How the books are standing today."""
    return await _section("Tilstanden på bøkene", lambda: _wrap(
        preflight.cached(), preflight.briefing))


async def _commitments() -> str:
    """What of the money on the account is actually the company's."""
    return await _section("Hvor mye av pengene på konto som er selskapets",
                          lambda: _wrap(commitments.cached(),
                                        commitments.briefing))


async def _forecast() -> str:
    """The thirteen weeks ahead."""
    return await _section("De neste 13 ukene", lambda: _wrap(
        cashflow.cached(), cashflow.briefing))


async def _wrap(coro, render):
    return render(await coro)


async def system_blocks() -> list[dict]:
    """System prompt as API content blocks: stable first, volatile after."""
    stable = {"type": "text", "text": _persona(),
              "cache_control": {"type": "ephemeral"}}
    condition, money, ahead = await asyncio.gather(
        _condition(), _commitments(), _forecast())
    parts = [_deployment(), definitions.briefing(), condition, money, ahead,
             cards.briefing(), memory.briefing()]
    return [stable, {"type": "text", "text": "\n\n".join(p for p in parts if p)}]
