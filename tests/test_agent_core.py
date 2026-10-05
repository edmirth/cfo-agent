import asyncio
import logging
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import anthropic
import httpx2

import summary
import industry
from agent import core, tools
from tests._claude import claude, message, text, tool_use

BACKEND = Path(__file__).resolve().parent.parent / "backend"


def _run(job, messages, outcome=None):
    async def collect():
        return [e async for e in core.run(job, messages, outcome)]
    return asyncio.run(collect())


def test_only_the_core_talks_to_anthropic():
    """The map's rule: one module holds the client, so every model call gets
    the read-only toolset, verify and the cost line."""
    talkers = sorted(
        p.relative_to(BACKEND).as_posix() for p in BACKEND.rglob("*.py")
        if re.search(r"^\s*(from|import) anthropic\b",
                     p.read_text(encoding="utf-8"), re.M))
    assert talkers == ["agent/core.py"], talkers


def test_every_module_loads_first_in_a_fresh_interpreter():
    """The suite imports modules in one order and the server in another, and
    an import loop only breaks in the order that closes it. The server's order
    once failed on memory → definitions → industry → agent.core."""
    for module in ("agent.jobs.chat", "agent.core", "agent.tools", "memory",
                   "definitions", "cards", "industry", "summary", "prompt"):
        r = subprocess.run([sys.executable, "-c", f"import {module}"],
                           cwd=BACKEND, capture_output=True, text=True)
        assert r.returncode == 0, f"import {module}:\n{r.stderr[-600:]}"


def test_a_job_is_offered_only_its_own_tools():
    job = core.Job(name="t", tools=("calculate",))
    kwargs = asyncio.run(core._request(job, [{"role": "user", "content": "x"}]))
    assert [t["name"] for t in kwargs["tools"]] == ["calculate"]
    assert "mcp_servers" not in kwargs                  # no Tripletex unless asked

    bare = asyncio.run(core._request(core.Job(name="b"), []))
    assert "tools" not in bare and "system" not in bare and "thinking" not in bare


def test_a_job_cannot_name_a_tool_that_does_not_exist():
    try:
        core.Job(name="t", tools=("send_invoice",))
    except ValueError as exc:
        assert "send_invoice" in str(exc)
    else:
        raise AssertionError("an unknown tool was accepted")


def test_a_tool_the_job_was_not_given_is_refused_not_run():
    ran = []

    async def fake_run(name, args):
        ran.append(name)
        return "Kalkulert: 4"

    job = core.Job(name="t", tools=("calculate",))
    original = tools.run
    tools.run = fake_run
    try:
        with claude(
            message("tool_use", tool_use("propose_card", {"title": "x"}, "t1"),
                    tool_use("calculate", {"expression": "2+2"}, "t2")),
            message("end_turn", text("Ferdig.")),
        ) as fake:
            _run(job, [{"role": "user", "content": "Hei"}])
    finally:
        tools.run = original

    assert ran == ["calculate"]                         # propose_card never ran
    answers = {r["tool_use_id"]: r["content"]
               for r in fake.requests[1]["messages"][-1]["content"]}
    assert answers["t1"] == "No such tool: propose_card."
    assert answers["t2"] == "Kalkulert: 4"


def test_the_outcome_counts_every_round_and_every_unsourced_figure():
    outcome = core.Outcome("t")
    job = core.Job(name="t", tools=("calculate",))
    with claude(
        message("tool_use", tool_use("calculate", {"expression": "2+2"}),
                input_tokens=1000, output_tokens=50, cache_read_input_tokens=9000,
                cache_creation_input_tokens=400),
        # 1 500 000 was in the prompt; 987 654 was not.
        message("end_turn", text("Banken har 1 500 000 kr, ikke 987 654 kr."),
                input_tokens=200, output_tokens=30),
    ):
        _run(job, [{"role": "user", "content": "Saldoen er 1500000."}], outcome)

    assert outcome.status == "done" and outcome.rounds == 2
    assert (outcome.input_tokens, outcome.output_tokens) == (1200, 80)
    assert (outcome.cache_read, outcome.cache_write) == (9000, 400)
    assert outcome.unverified == 1
    expected = (1200 * 5 + 80 * 25 + 9000 * 0.5 + 400 * 5 * 1.25) / 1_000_000
    assert abs(outcome.cost_usd - expected) < 1e-12


def test_every_run_is_logged_with_tokens_cost_and_unverified_figures():
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("cfo.agent")
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with claude(message("end_turn", text("Svar uten tall."),
                            input_tokens=123, output_tokens=45)):
            _run(core.Job(name="probe"), [{"role": "user", "content": "Hei"}])
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)

    line = next(r.getMessage() for r in records
                if r.getMessage().startswith("Jobb probe:"))
    assert "done etter 1 runde(r)" in line
    assert "123 inn" in line and "45 ut" in line
    assert "$0.0017" in line                            # 123*5 + 45*25 per million
    assert "0 tall uten kilde" in line


def test_an_interrupted_run_is_rolled_back_and_logged_as_interrupted():
    outcome = core.Outcome("t")
    messages = [{"role": "user", "content": "Hei"}]

    async def first_event_only():
        gen = core.run(core.Job(name="t"), messages, outcome)
        await gen.__anext__()                           # the text, then the tab closes
        await gen.aclose()

    with claude(message("end_turn", text("Halvveis"))):
        asyncio.run(first_event_only())
    assert outcome.status == "interrupted"
    assert messages == [{"role": "user", "content": "Hei"}]


def test_cost_is_unknown_for_a_model_with_no_price():
    assert core.cost("claude-unknown-9", NS(input_tokens=1, output_tokens=1)) is None
    # An hour-long cache write costs twice the input rate, not 1.25 times.
    hour = NS(input_tokens=0, output_tokens=0, cache_creation_input_tokens=1_000_000,
              cache_creation=NS(ephemeral_1h_input_tokens=1_000_000))
    assert core.cost("claude-opus-5-5", hour) == 8.0


def test_complete_reads_the_object_out_of_the_answer():
    job = core.Job(name="t", output="json")
    with claude(message("end_turn", text('Her: {"verdict": "Solid", "n": 2}'))):
        assert asyncio.run(core.complete(job, "Svar med JSON")) == {"verdict": "Solid", "n": 2}


def test_complete_raises_with_the_providers_words_when_the_request_is_rejected():
    rejected = anthropic.BadRequestError(
        "Your credit balance is too low to access the Anthropic API.",
        response=httpx2.Response(400, request=httpx2.Request(
            "POST", "https://api.anthropic.com/v1/messages")),
        body=None)
    with claude(rejected):
        try:
            asyncio.run(core.complete(core.Job(name="t"), "Hei"))
        except core.JobFailed as exc:
            # summary.py and main.py read this to tell the CEO what is wrong.
            assert "credit balance is too low" in str(exc)
            assert "Ingen kreditt" in summary._human_error(exc)
        else:
            raise AssertionError("a rejected request returned normally")


def test_complete_raises_on_a_refusal():
    with claude(message("refusal")):
        try:
            asyncio.run(core.complete(core.Job(name="t"), "Hei"))
        except core.JobFailed as exc:
            assert str(exc) == "refusal"
        else:
            raise AssertionError("a refusal returned normally")


def test_the_summary_is_written_through_the_core():
    async def overview():
        return {"kpis": {"omsetning": 1_234_567}, "monthly": []}

    async def nothing():
        return {}

    patched = {"overview_cached": overview, "commitments_cached": nothing,
               "_shape": lambda *a: {"omsetning_hittil": 1_234_567},
               "_load_profile": lambda: None,
               "company": NS(briefing=lambda: "")}
    originals = {k: getattr(summary, k) for k in patched}
    cashflow_cached = summary.cashflow.cached
    for k, v in patched.items():
        setattr(summary, k, v)
    summary.cashflow.cached = nothing
    try:
        with claude(message("end_turn", text(
                '{"verdict": "Solid drift", "text": "Dere har fakturert 1 234 567 kr."}'
        ))) as fake:
            out = asyncio.run(summary.build())
    finally:
        for k, v in originals.items():
            setattr(summary, k, v)
        summary.cashflow.cached = cashflow_cached

    assert out["verdict"] == "Solid drift"
    assert out["text"] == "Dere har fakturert 1 234 567 kr."
    sent = fake.requests[0]
    assert sent["max_tokens"] == summary.MAX_TOKENS
    assert "tools" not in sent                          # it formulates, it does not fetch
    assert "1234567" in sent["messages"][0]["content"]


def test_the_industry_is_classified_through_the_core():
    ctx = {"revenue": 1_000_000, "wages": 600_000, "operating": 50_000}
    with claude(message("end_turn", text(
            '{"bransje": "Renhold", "nokkeltall": [{"id": "lonnsandel"}, '
            '{"id": "oppdiktet"}], "hovedtall": "oppdiktet"}'))) as fake:
        data = asyncio.run(industry.classify(ctx, {"selskap": "Test AS"}))

    assert data["bransje"] == "Renhold"
    assert [k["id"] for k in data["nokkeltall"]] == ["lonnsandel"]   # invented one dropped
    assert data["hovedtall"] == "lonnsandel"
    assert fake.requests[0]["max_tokens"] == 2000
    assert "tools" not in fake.requests[0]
