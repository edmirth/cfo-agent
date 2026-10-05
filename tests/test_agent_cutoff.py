import asyncio
from types import SimpleNamespace as NS

from agent import core
from agent.jobs import chat


class _Stream:
    """Plays back one model response the way the SDK streams it."""

    def __init__(self, final, text):
        self.final, self.text = final, text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def events():
            yield NS(type="content_block_delta",
                     delta=NS(type="text_delta", text=self.text))
        return events()

    async def get_final_message(self):
        return self.final


def _run(stop_reason, content, text="Likviditeten er"):
    final = NS(stop_reason=stop_reason, content=content,
               usage=NS(input_tokens=1, output_tokens=1))
    fake = NS(beta=NS(messages=NS(stream=lambda **kw: _Stream(final, text))))

    async def kwargs(job, messages):
        return {"system": [], "messages": messages}

    originals = core.client, core._request
    core.client, core._request = fake, kwargs
    messages = [{"role": "user", "content": "Hvordan går det?"}]
    try:
        async def collect():
            return [e async for e in chat.run_turn(messages)]
        return asyncio.run(collect()), messages
    finally:
        core.client, core._request = originals


def test_a_cut_off_answer_says_so():
    events, messages = _run("max_tokens", [NS(type="text", text="Likviditeten er")])
    kinds = [e["type"] for e in events]
    # Text first, then the warning, then done — not straight to done.
    assert kinds.index("text") < kinds.index("error") < kinds.index("done")
    error = next(e for e in events if e["type"] == "error")
    assert "ikke fullstendig" in error["message"]
    assert messages[-1]["role"] == "assistant"         # the partial answer is kept


def test_a_call_cut_off_halfway_is_not_left_in_the_session():
    content = [NS(type="text", text="Jeg henter saldoen"),
               NS(type="tool_use", id="toolu_1", name="calculate", input={})]
    _, messages = _run("max_tokens", content)
    kept = messages[-1]["content"]
    assert [b.type for b in kept] == ["text"]          # no unanswered tool_use


def test_a_finished_answer_has_no_warning():
    content = [NS(type="text", text="Likviditeten er god.")]
    events, messages = _run("end_turn", content, text="Likviditeten er god.")
    assert "error" not in [e["type"] for e in events]
    assert messages[-1]["content"] is content           # stored untouched


def test_an_answered_server_call_survives_the_cut():
    content = [NS(type="server_tool_use", id="srv_1"),
               NS(type="code_execution_tool_result", tool_use_id="srv_1"),
               NS(type="text", text="Resultatet viser")]
    assert core._answered_only(content) == content
