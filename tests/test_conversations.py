"""Chat history and job runs in the database."""
import asyncio
import json
from types import SimpleNamespace as NS

from anthropic.types.beta import BetaMessage

import conversations
import db
import job_runs
import main
import memory
from agent import core, tools
from tests import _tmp
from tests.test_agent_core import _final, _play

# An assistant turn as the API returns it: thinking with its signature, a
# server-side MCP call and its result, a client tool call. All of it has to
# come back exactly as it went in, or the next request on the session fails.
API_TURN = {
    "id": "msg_01", "type": "message", "role": "assistant", "model": "claude-opus-5",
    "stop_reason": "tool_use", "stop_sequence": None,
    "usage": {"input_tokens": 10, "output_tokens": 5},
    "content": [
        {"type": "thinking", "thinking": "Saldoen først.", "signature": "c2lnbmF0dXJl"},
        {"type": "text", "text": "Jeg henter saldoen."},
        {"type": "mcp_tool_use", "id": "mcptoolu_1", "name": "get_balance_sheet",
         "server_name": "tripletex", "input": {"dateFrom": "2026-10-01"}},
        {"type": "mcp_tool_result", "tool_use_id": "mcptoolu_1", "is_error": False,
         "content": [{"type": "text", "text": "{\"balanceOut\": 2625898.93}"}]},
        {"type": "tool_use", "id": "toolu_1", "name": "calculate",
         "input": {"expression": "2625898.93 + 376904.04"}},
    ],
}


def _turn():
    final = BetaMessage.model_validate(API_TURN)
    return [{"role": "user", "content": "Hvor mye har vi i banken?"},
            {"role": "assistant", "content": final.content},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                          "content": "3 002 802.97"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "3 002 803 kr."}]}]


# ----------------------------------------------------------- conversations
def test_a_conversation_survives_a_restart_with_every_block_as_the_api_sent_it():
    _tmp.db()
    conversations.append("s1", _turn())
    db._ready.clear()                        # a new process opens the same file
    history = conversations.load("s1")
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    assert history[1]["content"] == API_TURN["content"]
    assert history[0]["content"] == "Hvor mye har vi i banken?"


def test_turns_are_appended_in_order():
    _tmp.db()
    conversations.append("s1", _turn())
    conversations.append("s1", [{"role": "user", "content": "Og i morgen?"},
                                {"role": "assistant", "content": [{"type": "text", "text": "Det samme."}]}])
    history = conversations.load("s1")
    assert history[-2]["content"] == "Og i morgen?" and len(history) == 6


def test_trimming_happens_on_reading_and_deletes_nothing():
    _tmp.db()
    for i in range(20):
        conversations.append("s1", _turn())
    history = conversations.load("s1", limit=10)
    assert len(history) <= 10
    assert history[0]["role"] == "user" and isinstance(history[0]["content"], str)
    with db.read() as conn:
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 80


def test_deleting_a_conversation_removes_its_messages():
    _tmp.db()
    conversations.append("s1", _turn())
    conversations.append("s2", _turn())
    conversations.delete("s1")
    assert conversations.load("s1") == [] and len(conversations.load("s2")) == 4
    with db.read() as conn:
        assert conn.execute("SELECT count(*) FROM messages WHERE conversation_id = 's1'"
                            ).fetchone()[0] == 0


# ------------------------------------------------------------ the endpoint
def _chat(message, session_id, turn):
    """Post one chat message with the agent replaced by `turn`."""
    original = main.run_turn
    main.run_turn = turn
    try:
        async def go():
            resp = await main.chat(main.ChatRequest(message=message, session_id=session_id))
            return [json.loads(chunk[6:]) async for chunk in resp.body_iterator]
        return asyncio.run(go())
    finally:
        main.run_turn = original


def _answering(text, seen=None):
    async def turn(history):
        if seen is not None:
            seen.append([m["role"] for m in history])
        history.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
        yield {"type": "text", "text": text}
        yield {"type": "done", "usage": {}, "job_run_id": None}
    return turn


def _failing(history):
    async def turn(history):
        history.append({"role": "assistant", "content": [{"type": "text", "text": "Halv"}]})
        yield {"type": "error", "message": "Modellen avviste forespørselen."}
    return turn(history)


def test_the_endpoint_reloads_the_conversation_and_saves_only_whole_turns():
    _tmp.db()
    main.config.ANTHROPIC_API_KEY = main.config.ANTHROPIC_API_KEY or "test"
    _chat("Hei", "web-1", _answering("Hei tilbake."))
    _chat("Feiler denne?", "web-1", _failing)
    seen = []
    _chat("Og nå?", "web-1", _answering("Nå går det.", seen))
    # The failed question was never saved, so it is not stacked under the next.
    assert seen == [["user", "assistant", "user"]]
    assert [m["content"] if isinstance(m["content"], str) else m["content"][0]["text"]
            for m in conversations.load("web-1")] == [
        "Hei", "Hei tilbake.", "Og nå?", "Nå går det."]


# ----------------------------------------------------------------- job runs
def test_every_run_is_recorded_with_its_cost_and_ending():
    _tmp.db()
    job = core.Job(name="sjekk")
    _play(job, [_final("end_turn", [NS(type="text", text="Det ble 777 kr.")],
                       i=1000, o=100, cr=5000, cw=200)])
    _play(job, [_final("refusal", [])])
    _play(job, [_final("max_tokens", [NS(type="text", text="Halv")])])
    runs = job_runs.recent("sjekk")
    assert [r["status"] for r in runs] == ["partial", "failed", "ok"]
    ok = runs[2]
    assert (ok["input_tokens"], ok["output_tokens"], ok["cache_read_tokens"]) == (1000, 100, 5000)
    assert ok["details"]["cache_write_tokens"] == 200 and ok["details"]["rounds"] == 1
    assert ok["unverified"] == 1 and ok["cost_usd"] > 0
    assert ok["finished_at"] >= ok["started_at"] and ok["model"]
    assert "avslo" in runs[1]["error"]


def test_the_done_event_names_the_run_and_what_the_run_wrote_points_back():
    _tmp.db()
    original = tools.run

    async def note(name, args):
        return memory.add_finding("Lønnsandel", "high", "Over målet")["id"]

    tools.run = note
    try:
        job = core.Job(name="chat-test", tools=frozenset({"remember_finding"}))
        events, _ = _play(job, [
            _final("tool_use", [NS(type="tool_use", id="tu_1", name="remember_finding",
                                   input={})]),
            _final("end_turn", [NS(type="text", text="Notert.")])])
    finally:
        tools.run = original
    run_id = next(e for e in events if e["type"] == "done")["job_run_id"]
    assert run_id is not None
    with db.read() as conn:
        assert conn.execute("SELECT job_run_id FROM findings").fetchone()[0] == run_id
    assert db.job_run.get() is None            # nothing leaks past the run
