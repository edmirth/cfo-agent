"""The chat: the CEO asks, the CFO answers from the books.

The one job with the whole kit — the read-only Tripletex toolset, the sandbox,
every local tool — and the front page's figures in its system prompt.
"""
from collections.abc import AsyncIterator

import config
from agent import core, tools
from prompt import system_blocks

CHAT = core.Job(
    name="chat",
    system=system_blocks,
    # Everything but the morning watch's tools, which act only inside a watch run.
    tools=tools.NAMES - tools.WATCH,
    tripletex=True,
    thinking={"type": "adaptive", "display": "summarized"},
    effort=config.CFO_EFFORT,
)


def run_turn(messages: list[dict]) -> AsyncIterator[dict]:
    """Stream one assistant turn; see `core.stream`."""
    return core.stream(CHAT, messages)
