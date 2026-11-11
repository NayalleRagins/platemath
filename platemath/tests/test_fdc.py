import asyncio
import json
from pathlib import Path

import httpx2
import pytest

from api.errors import RateLimitedError, UpstreamError
from api.fdc import FdcClient, Nutrients, to_food_match

# A real FoodData Central search for "all-purpose flour", recorded on 2026-11-09
# and trimmed to 3 foods and the nutrients PlateMath reads (plus iron, to check
# that unrelated nutrients are ignored).
FLOUR = json.loads((Path(__file__).parent / "fixtures" / "fdc-search-all-purpose-flour.json").read_text("utf-8"))

pytestmark = pytest.mark.anyio


def make_client(handler, *, api_key="test-key"):
    """An FdcClient whose HTTP requests go to `handler`. Returns (client, list of requests)."""
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(record))
    return FdcClient(api_key, http=http), requests


def answer(status=200, body=None, **kwargs):
    """A handler that always sends the same response. `body` is sent as JSON."""
    if body is not None:
        kwargs["json"] = body
    return lambda request: httpx2.Response(status, **kwargs)


async def test_returns_matches_with_nutrients_per_100g():
    fdc, _ = make_client(answer(200, FLOUR))

    foods = await fdc.search("all-purpose flour")

    assert [f.fdc_id for f in foods] == [789890, 790018, 168894]
    first = foods[0]
    assert first.description == "Flour, wheat, all-purpose, enriched, bleached"
    assert first.data_type == "Foundation"
    assert first.category == "Cereal Grains and Pasta"
    assert first.per_100g == Nutrients(
        calories_kcal=366,
        protein_g=10.9,
        fat_g=1.48,
        saturated_fat_g=None,  # not in this Foundation record
        carbs_g=77.3,
        fiber_g=None,
        sugars_g=None,
        sodium_mg=2.0,
        cholesterol_mg=None,
    )
    sr_legacy = foods[2].per_100g
    assert (sr_legacy.saturated_fat_g, sr_legacy.sugars_g, sr_legacy.cholesterol_mg) == (0.155, 0.27, 0)


async def test_sends_the_key_in_a_header_never_in_the_url():
    fdc, requests = make_client(answer(200, FLOUR), api_key="secret-key-123")
    await fdc.search("flour", limit=3)

    (request,) = requests
    assert request.headers["X-Api-Key"] == "secret-key-123"
    assert "secret-key-123" not in str(request.url)
    assert request.url.path == "/fdc/v1/foods/search"
    assert request.url.params["query"] == "flour"
    assert request.url.params["dataType"] == "Foundation,SR Legacy"
    assert request.url.params["pageSize"] == "3"


async def test_repeat_searches_come_from_the_cache():
    fdc, requests = make_client(answer(200, FLOUR))

    await fdc.search("all-purpose flour")
    await fdc.search("  All-Purpose   FLOUR ")

    assert len(requests) == 1


async def test_searches_at_the_same_time_share_one_request():
    fdc, requests = make_client(answer(200, FLOUR))

    await asyncio.gather(fdc.search("flour"), fdc.search("flour"), fdc.search("flour"))

    assert len(requests) == 1


async def test_blank_query_makes_no_request():
    fdc, requests = make_client(answer(200, FLOUR))
    assert await fdc.search("   ") == []
    assert requests == []


def test_requires_an_api_key():
    with pytest.raises(ValueError, match="API key"):
        FdcClient("", http=httpx2.AsyncClient())


@pytest.mark.parametrize(
    ("handler", "error", "message"),
    [
        (answer(429), RateLimitedError, "rate limit"),
        (answer(403, {"error": {"code": "API_KEY_INVALID"}}), UpstreamError, "API key"),
        (answer(500), UpstreamError, "HTTP 500"),
        (answer(200, text="<html>maintenance</html>"), UpstreamError, "isn't JSON"),
        (answer(200, {"totalHits": 0}), UpstreamError, "without a food list"),
    ],
)
async def test_upstream_problems_become_clear_errors(handler, error, message):
    fdc, _ = make_client(handler)
    with pytest.raises(error, match=message):
        await fdc.search("flour")


async def test_network_failure_is_an_upstream_error():
    def fail(request):
        raise httpx2.ConnectError("connection refused", request=request)

    fdc, _ = make_client(fail)
    with pytest.raises(UpstreamError, match="Couldn't reach"):
        await fdc.search("flour")


async def test_failures_are_not_cached():
    responses = iter([httpx2.Response(500), httpx2.Response(200, json=FLOUR)])
    fdc, requests = make_client(lambda request: next(responses))

    with pytest.raises(UpstreamError):
        await fdc.search("flour")
    assert len(await fdc.search("flour")) == 3
    assert len(requests) == 2


async def test_skips_malformed_foods():
    body = {"foods": [{"description": "no id"}, "junk", FLOUR["foods"][0]]}
    fdc, _ = make_client(answer(200, body))
    assert [f.fdc_id for f in await fdc.search("flour")] == [789890]


# The foods below are made up, to cover cases the flour search doesn't.


def food(*nutrients):
    return {
        "fdcId": 1,
        "description": "Test food",
        "dataType": "Foundation",
        "foodNutrients": [{"nutrientId": i, "unitName": u, "value": v} for i, u, v in nutrients],
    }


def test_calories_fall_back_to_atwater_energy():
    match = to_food_match(food((2047, "KCAL", 143.0), (1062, "kJ", 599.0)))
    assert match.per_100g.calories_kcal == 143.0


def test_calories_fall_back_to_kilojoules():
    match = to_food_match(food((1062, "kJ", 599.0)))
    assert match.per_100g.calories_kcal == 143.2


def test_missing_nutrients_are_none_not_zero():
    match = to_food_match(food((1003, "G", 12.0)))
    assert match.per_100g.protein_g == 12.0
    assert match.per_100g.calories_kcal is None
    assert match.per_100g.fat_g is None
