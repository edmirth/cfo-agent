import asyncio

import freshness


def _run(coro):
    return asyncio.run(coro)


def test_two_cold_callers_cause_one_build():
    calls = []

    async def build():
        calls.append(1)
        await asyncio.sleep(0.05)          # long enough for the second caller
        return {"n": len(calls)}

    c = freshness.Cached(build, seconds=600)

    async def both():
        return await asyncio.gather(c.get(), c.get())

    a, b = _run(both())
    assert len(calls) == 1, f"built {len(calls)} times, expected 1"
    assert a is b


def test_a_caller_giving_up_does_not_cancel_the_build():
    done = []

    async def build():
        await asyncio.sleep(0.05)
        done.append(1)
        return {"ok": True}

    c = freshness.Cached(build, seconds=600)

    async def scenario():
        quitter = asyncio.create_task(c.get())
        waiter = asyncio.create_task(c.get())
        await asyncio.sleep(0.01)
        quitter.cancel()                   # browser navigates away
        return await waiter

    assert _run(scenario()) == {"ok": True}
    assert done == [1]


def test_a_failed_build_is_retried_not_remembered():
    attempts = []

    async def build():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("Tripletex svarte 500")
        return {"ok": True}

    c = freshness.Cached(build, seconds=600)

    async def scenario():
        try:
            await c.get()
        except RuntimeError:
            pass
        return await c.get()

    assert _run(scenario()) == {"ok": True}
    assert len(attempts) == 2


def test_a_degraded_build_expires_quickly():
    c = freshness.Cached(lambda: _ok({"partial": ["Resultatrapport"]}),
                         seconds=600, degraded=lambda d: bool(d.get("partial")),
                         degraded_seconds=45)
    _run(c.get())
    assert c._ttl(c._data) == 45, "a partial build must not be held for 10 minutes"


def test_a_whole_build_is_held_for_the_full_ttl():
    c = freshness.Cached(lambda: _ok({"partial": None}), seconds=600,
                         degraded=lambda d: bool(d.get("partial")))
    _run(c.get())
    assert c._ttl(c._data) == 600


async def _ok(d):
    return d
