import asyncio

import pytest

from api.cache import TtlCache


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_returns_a_value_until_it_expires():
    clock = FakeClock()
    cache = TtlCache(clock=clock)
    cache.set("a", 1, ttl=10)

    clock.now = 9.9
    assert cache.get("a") == 1

    clock.now = 10
    assert cache.get("a") is None
    assert len(cache) == 0


def test_drops_the_oldest_entries_past_max_entries():
    cache = TtlCache(max_entries=2)
    cache.set("a", 1, ttl=10)
    cache.set("b", 2, ttl=10)
    cache.set("c", 3, ttl=10)

    assert len(cache) == 2
    assert cache.get("a") is None
    assert cache.get("c") == 3


@pytest.mark.anyio
async def test_only_loads_once_while_fresh():
    clock = FakeClock()
    cache = TtlCache(clock=clock)
    calls = 0

    async def load():
        nonlocal calls
        calls += 1
        return calls

    assert await cache.get_or_load("k", 10, load) == 1
    assert await cache.get_or_load("k", 10, load) == 1
    clock.now = 10
    assert await cache.get_or_load("k", 10, load) == 2


@pytest.mark.anyio
async def test_caches_falsy_values():
    cache = TtlCache()
    calls = 0

    async def load():
        nonlocal calls
        calls += 1
        return []

    await cache.get_or_load("k", 10, load)
    await cache.get_or_load("k", 10, load)
    assert calls == 1


@pytest.mark.anyio
async def test_requests_at_the_same_time_share_one_load():
    cache = TtlCache()
    calls = 0
    gate = asyncio.Event()

    async def load():
        nonlocal calls
        calls += 1
        await gate.wait()
        return "value"

    both = asyncio.gather(cache.get_or_load("k", 10, load), cache.get_or_load("k", 10, load))
    await asyncio.sleep(0)
    gate.set()
    assert await both == ["value", "value"]
    assert calls == 1


@pytest.mark.anyio
async def test_does_not_cache_failures():
    cache = TtlCache()
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("upstream down")
        return "ok"

    with pytest.raises(RuntimeError, match="upstream down"):
        await cache.get_or_load("k", 10, flaky)
    assert await cache.get_or_load("k", 10, flaky) == "ok"
