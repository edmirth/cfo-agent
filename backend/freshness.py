"""One build at a time, per cached figure.

Every front-page figure is cached for ten minutes, and each module checked it
the same way: read the cache, `await build()`, store. Between the check and the
store there is an await, so two callers arriving on a cold cache both miss and
both build. That is not theoretical — `/api/overview` and `/api/dashboard` are
fetched together by the front page, and `industry.py` awaits `overview.cached()`
inside its own gather, so a cold load fired four redundant Tripletex report
calls for one overview.

A plain lock is the wrong fix: it would queue the second caller behind the
first and then let it build anyway, against a cache that is warm by then. What
should be shared is the work in flight, not the right to start it. So the task
is the thing held, and everyone who arrives while it runs awaits the same one.

`asyncio.shield` matters here: awaiting a task propagates cancellation into it,
so one caller giving up — a browser navigating away mid-load — would otherwise
cancel the build that the others are still waiting on.
"""
import asyncio
import time
from collections.abc import Awaitable, Callable


class Cached:
    """A value rebuilt on demand, at most once at a time."""

    def __init__(self, build: Callable[[], Awaitable[dict]], seconds: int,
                 degraded: Callable[[dict], bool] | None = None,
                 degraded_seconds: int = 45) -> None:
        self._build = build
        self._seconds = seconds
        # A build can succeed and still be missing half its figures, when a
        # report failed and the caller carried on without it. Holding that for
        # the full ten minutes is how a two-second upstream blip blanked the
        # front page: we cause the failure, then we memorise it. Keep it just
        # long enough to stop a stampede, then go and ask again.
        self._degraded = degraded
        self._degraded_seconds = degraded_seconds

        self._data: dict | None = None
        self._at = 0.0
        self._flight: asyncio.Task | None = None

    def _ttl(self, data: dict) -> int:
        if self._degraded is not None and self._degraded(data):
            return self._degraded_seconds
        return self._seconds

    def fresh(self) -> dict | None:
        """The cached value while it still counts as current, else None."""
        if self._data is not None and time.time() - self._at < self._ttl(self._data):
            return self._data
        return None

    async def _run(self) -> dict:
        data = await self._build()
        # Stored here rather than in `get`, so it happens once per build no
        # matter how many callers are waiting on it.
        self._data, self._at = data, time.time()
        return data

    async def get(self) -> dict:
        hit = self.fresh()
        if hit is not None:
            return hit
        flight = self._flight
        if flight is None or flight.done():
            flight = self._flight = asyncio.create_task(self._run())
        return await asyncio.shield(flight)

    def clear(self) -> None:
        """Forget the value. The build in flight, if any, is left to finish."""
        self._data, self._at = None, 0.0
