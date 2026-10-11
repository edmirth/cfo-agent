"""The front-page summary does not pay for a retry on every page load.

Only success was remembered, so while the text could not be written every
load of the front page called the model again — four cut-off answers at
$0.044 each on 10–11 October, all from page loads.
"""
import asyncio
import json

import summary
from tests import _tmp


class _Model:
    """Stands in for `build`: fails until told otherwise, counting calls."""
    def __init__(self):
        self.calls, self.ok = 0, False

    async def __call__(self, today=None):
        self.calls += 1
        if not self.ok:
            raise RuntimeError("Svaret ble kuttet fordi det ble for langt")
        return {"verdict": "Solid drift", "text": "Det går bra.",
                "written": summary.date.today().isoformat(), "unverified": []}


def _setup(yesterday=True):
    path = _tmp.store(summary, "STORE")
    if yesterday:
        path.write_text(json.dumps({"verdict": "Presset", "text": "I går.",
                                    "written": "2000-01-01"}), encoding="utf-8")
    summary._failed.clear()
    model, clock = _Model(), [1000.0]
    real = summary.build, summary._clock
    summary.build, summary._clock = model, (lambda: clock[0])
    return model, clock, real


def test_a_failed_summary_is_not_retried_on_every_page_load():
    model, clock, real = _setup()
    try:
        first = asyncio.run(summary.cached())
        again = [asyncio.run(summary.cached()) for _ in range(5)]
        assert model.calls == 1
        assert first["stale"] and all(a["stale"] and a["text"] == "I går." for a in again)
        # Half an hour on, it is worth another try.
        clock[0] += summary.RETRY_AFTER_S
        model.ok = True
        fresh = asyncio.run(summary.cached())
        assert model.calls == 2 and fresh["text"] == "Det går bra." and "stale" not in fresh
        # Written today: read from disk, never written again.
        asyncio.run(summary.cached())
        assert model.calls == 2
    finally:
        summary.build, summary._clock = real


def test_the_rewrite_button_always_tries():
    model, clock, real = _setup()
    try:
        asyncio.run(summary.cached())
        asyncio.run(summary.cached(refresh=True))
        assert model.calls == 2
    finally:
        summary.build, summary._clock = real


def test_with_nothing_on_disk_the_card_says_why():
    model, clock, real = _setup(yesterday=False)
    try:
        out = asyncio.run(summary.cached())
        assert asyncio.run(summary.cached()) == out and model.calls == 1
        assert "fikk ikke skrevet" in out["error"]
    finally:
        summary.build, summary._clock = real
