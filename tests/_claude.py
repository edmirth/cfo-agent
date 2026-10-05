"""Stands in for Claude in a test: plays back responses the way the SDK streams them."""
from contextlib import contextmanager
from types import SimpleNamespace as NS

from agent import core


def text(value: str):
    return NS(type="text", text=value)


def tool_use(name: str, args: dict, id: str = "toolu_1"):
    return NS(type="tool_use", id=id, name=name, input=args)


def message(stop_reason: str, *content, model: str = "claude-opus-5", **usage):
    counts = {"input_tokens": 100, "output_tokens": 10, **usage}
    return NS(stop_reason=stop_reason, content=list(content), model=model,
              usage=NS(**counts))


class _Stream:
    def __init__(self, final):
        self.final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def events():
            for b in self.final.content:
                if b.type in core.TOOL_BLOCK_TYPES:
                    yield NS(type="content_block_start", content_block=b)
                elif b.type == "text":
                    yield NS(type="content_block_delta",
                             delta=NS(type="text_delta", text=b.text))
        return events()

    async def get_final_message(self):
        return self.final


class Fake:
    """Answers each request with the next message, and keeps what was asked."""

    def __init__(self, *messages):
        self.queue = list(messages)
        self.requests: list[dict] = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        # A copy: the core appends to the same list after the request is sent.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        nxt = self.queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return _Stream(nxt)


@contextmanager
def claude(*messages):
    """Point the core at a fake Claude that gives these answers in turn."""
    fake = Fake(*messages)
    original = core.client
    core.client = fake
    try:
        yield fake
    finally:
        core.client = original
