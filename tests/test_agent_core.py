"""The agent core: one loop for every job, and the limits it holds each job to."""
import asyncio
import logging
from types import SimpleNamespace as NS

from agent import core, tools
from agent.jobs.chat import CHAT


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
                if getattr(b, "type", None) == "text":
                    yield NS(type="content_block_delta",
                             delta=NS(type="text_delta", text=b.text))
        return events()

    async def get_final_message(self):
        return self.final


def _final(stop, content, i=10, o=5, cr=0, cw=0):
    return NS(stop_reason=stop, content=content,
              usage=NS(input_tokens=i, output_tokens=o,
                       cache_read_input_tokens=cr, cache_creation_input_tokens=cw))


def _play(job, finals, prompt="Hva er saldoen?", sent=None, method="stream"):
    """Run a job against canned responses, one per round."""
    queue = list(finals)

    def stream(**kw):
        if sent is not None:
            sent.append(kw)
        return _Stream(queue.pop(0))

    fake = NS(beta=NS(messages=NS(stream=stream)))
    originals = core.client, core.tokens.access_token
    core.client = fake

    async def token():
        return "test-token"

    core.tokens.access_token = token
    try:
        if method == "complete":
            return asyncio.run(core.complete(job, prompt))
        messages = [{"role": "user", "content": prompt}]

        async def collect():
            return [e async for e in core.stream(job, messages)]
        return asyncio.run(collect()), messages
    finally:
        core.client, core.tokens.access_token = originals


async def _no_system():
    return [{"type": "text", "text": "Saldo 2 625 899 kr."}]


# --------------------------------------------------------- tools per job
def test_a_job_is_offered_only_the_local_tools_it_names():
    job = core.Job(name="t", tools=frozenset({"calculate"}))
    sent = []
    _play(job, [_final("end_turn", [NS(type="text", text="Ferdig.")])], sent=sent)
    names = [t.get("name") for t in sent[0]["tools"]]
    assert names == ["calculate"]
    assert "mcp_servers" not in sent[0]


def test_a_job_without_tools_or_tripletex_sends_no_tools_at_all():
    sent = []
    _play(core.Job(name="t"), [_final("end_turn", [NS(type="text", text="Ok.")])],
          sent=sent)
    assert "tools" not in sent[0] and "mcp_servers" not in sent[0]


def test_a_call_to_a_tool_the_job_was_not_given_is_refused():
    """Offered or not, a propose_card from a summary job must not open a card."""
    ran = []
    original = tools.run

    async def spy(name, args):
        ran.append(name)
        return "ran"

    tools.run = spy
    try:
        job = core.Job(name="t", tools=frozenset({"calculate"}))
        call = NS(type="tool_use", id="tu_1", name="propose_card", input={})
        events, messages = _play(job, [
            _final("tool_use", [call]),
            _final("end_turn", [NS(type="text", text="Ok.")])])
    finally:
        tools.run = original
    assert ran == []
    result = messages[2]["content"][0]
    assert result["tool_use_id"] == "tu_1" and "No such tool" in result["content"]


def test_an_unknown_tool_name_fails_when_the_job_is_defined():
    try:
        core.Job(name="t", tools=frozenset({"send_money"}))
    except ValueError as exc:
        assert "send_money" in str(exc)
    else:
        raise AssertionError("a job naming a tool that does not exist was accepted")


def test_chat_keeps_the_whole_kit():
    assert CHAT.tools == tools.NAMES and CHAT.tripletex
    sent = []
    _play(CHAT, [_final("end_turn", [NS(type="text", text="Ok.")])], sent=sent)
    names = {t.get("name") or t.get("mcp_server_name") for t in sent[0]["tools"]}
    assert tools.NAMES <= names and "code_execution" in names
    assert sent[0]["mcp_servers"][0]["authorization_token"] == "test-token"


# ------------------------------------------------------------- complete
def test_complete_returns_parsed_json_and_the_check():
    job = core.Job(name="t", system=_no_system, output="json")
    r = _play(job, [_final("end_turn", [NS(type="text", text=(
        'Her: {"text": "Saldoen er 2 625 899 kr, og 4 000 000 er målet."}'))])],
        method="complete")
    assert r.data["text"].startswith("Saldoen")
    assert r.check["unverified"] == [4_000_000.0]
    assert r.check["supported"] == 1


def test_complete_fails_on_an_answer_that_is_not_json():
    job = core.Job(name="oppsummering", output="json")
    try:
        _play(job, [_final("end_turn", [NS(type="text", text="Beklager.")])],
              method="complete")
    except core.JobError as exc:
        assert "oppsummering svarte ikke med JSON" in str(exc)
    else:
        raise AssertionError("prose was accepted as JSON")


def test_complete_fails_on_a_cut_off_answer():
    job = core.Job(name="t", output="json")
    try:
        _play(job, [_final("max_tokens", [NS(type="text", text='{"text": "Halv')])],
              method="complete")
    except core.JobError as exc:
        assert "ikke fullstendig" in str(exc)
    else:
        raise AssertionError("a cut-off answer was returned as finished")


# ---------------------------------------------------------- what it cost
def test_every_run_logs_tokens_cost_and_unverified_figures_over_all_rounds():
    records = []
    handler = logging.Handler()
    handler.emit = lambda r: records.append(r.getMessage())
    logger = logging.getLogger("cfo.agent")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    original = tools.run

    async def fake_run(name, args):
        return "Resultat: 12"

    tools.run = fake_run
    try:
        job = core.Job(name="sjekk", tools=frozenset({"calculate"}))
        _play(job, [
            _final("tool_use", [NS(type="tool_use", id="tu_1", name="calculate",
                                   input={})], i=1000, o=100, cr=5000, cw=200),
            _final("end_turn", [NS(type="text", text="Det ble 777 kr.")],
                   i=500, o=50)])
    finally:
        tools.run = original
        logger.removeHandler(handler)
    line = next(r for r in records if r.startswith("jobb sjekk"))
    assert "2 runder" in line and "1500 inn" in line and "150 ut" in line
    assert "cache 5000 lest / 200 skrevet" in line
    assert "1 tall uten kilde" in line
    usd = core.cost({"input": 1500, "output": 150, "cache_read": 5000,
                     "cache_write": 200}, "claude-opus-5")
    assert abs(usd - (1500 * 5 + 5000 * 0.5 + 200 * 6.25 + 150 * 25) / 1e6) < 1e-12
    assert f"{usd:.4f} USD" in line


def test_an_unpriced_model_is_logged_without_a_guessed_cost():
    assert core.cost({"input": 1, "output": 1}, "claude-unknown-9") is None


# ----------------------------------------------- the other jobs use it
def test_summary_and_classification_are_jobs_on_the_core():
    import industry
    import summary
    assert isinstance(summary.SUMMARY, core.Job) and summary.SUMMARY.output == "json"
    assert not summary.SUMMARY.tools and not summary.SUMMARY.tripletex
    assert isinstance(industry.CLASSIFY, core.Job) and industry.CLASSIFY.output == "json"
    assert not hasattr(summary, "client") and not hasattr(industry, "client")
