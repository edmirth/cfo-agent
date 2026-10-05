"""The CFO in chat: the CEO's questions, answered on live Tripletex figures.

The chat is one job on the shared core, and so far the only one with the whole
toolbox: Tripletex, the Python sandbox and every local tool. It gets all of
them because a question can be about anything.
"""
from collections.abc import AsyncIterator

import config
from agent import core, tools
from prompt import system_blocks

CHAT = core.Job(
    name="chat",
    tools=tools.NAMES,
    tripletex=True,
    code=True,
    # The breakpoint sits inside system_blocks(), on the persona — the part
    # that repeats identically on every tool round. Memory follows it uncached
    # so a note written mid-turn costs a small block, not the lot.
    system=system_blocks,
    max_tokens=config.MAX_TOKENS,
    thinking={"type": "adaptive", "display": "summarized"},
    effort=config.CFO_EFFORT,
)


def run_turn(messages: list[dict]) -> AsyncIterator[dict]:
    """Stream one answer to the CEO as UI events. See `core.run`."""
    return core.run(CHAT, messages)
