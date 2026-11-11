"""Small in-memory cache with a time limit per entry."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

_MISSING = object()


class TtlCache:
    """Keeps values for a limited time so repeat lookups don't hit the API again.

    FoodData Central limits how many requests a key can make per hour, so
    this matters. If two requests for the same key arrive while the first is
    still loading, they share one upstream call.
    """

    def __init__(self, *, max_entries: int = 1000, clock: Callable[[], float] = time.monotonic) -> None:
        """
        max_entries: the oldest entries are dropped past this size.
        clock: returns the time in seconds. Tests pass a fake one.
        """
        self._entries: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._pending: dict[Hashable, asyncio.Task[Any]] = {}
        self._max_entries = max_entries
        self._clock = clock

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: Hashable, default: Any = None) -> Any:
        """Returns the cached value, or `default` if it's missing or expired."""
        entry = self._entries.get(key)
        if entry is None:
            return default
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._entries[key]
            return default
        return value

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        # Re-inserting moves the key to the end, so the dict stays oldest-first.
        self._entries.pop(key, None)
        self._entries[key] = (self._clock() + ttl, value)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    async def get_or_load(self, key: Hashable, ttl: float, load: Callable[[], Awaitable[Any]]) -> Any:
        """Returns the cached value for `key`, or awaits `load()` and caches the result for `ttl` seconds.

        Errors are not cached, so the next call tries again.
        """
        cached = self.get(key, _MISSING)
        if cached is not _MISSING:
            return cached

        task = self._pending.get(key)
        if task is None:
            task = asyncio.ensure_future(self._load(key, ttl, load))
            # Mark a failure as seen even if every caller has gone, so asyncio doesn't warn.
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
            self._pending[key] = task
        # shield: if one caller gives up (say the browser disconnects), the
        # others sharing this load still get their answer.
        return await asyncio.shield(task)

    async def _load(self, key: Hashable, ttl: float, load: Callable[[], Awaitable[Any]]) -> Any:
        try:
            value = await load()
            self.set(key, value, ttl)
            return value
        finally:
            self._pending.pop(key, None)
