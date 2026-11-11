import pytest
from fastapi.testclient import TestClient

from api.errors import RateLimitedError, UpstreamError
from api.fdc import FoodMatch, Nutrients
from api.main import create_app

FLOUR = FoodMatch(
    fdc_id=789890,
    description="Flour, wheat, all-purpose, enriched, bleached",
    data_type="Foundation",
    category="Cereal Grains and Pasta",
    per_100g=Nutrients(366, 10.9, 1.48, None, 77.3, None, None, 2.0, None),
)


class FakeFoodSearch:
    """Stands in for FoodData Central, so these tests check only the HTTP layer."""

    def __init__(self):
        self.calls = []

    async def search(self, query, *, limit=5):
        self.calls.append((query, limit))
        if query == "rate limited":
            raise RateLimitedError("FoodData Central's rate limit is used up for now. Try again later.")
        if query == "down":
            raise UpstreamError("FoodData Central returned HTTP 500")
        if query == "bug":
            raise RuntimeError("secret internal detail")
        return [FLOUR]


@pytest.fixture
def search():
    return FakeFoodSearch()


@pytest.fixture
def client(search):
    return TestClient(create_app(food_search=search), raise_server_exceptions=False)


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True, "food_search": True}


def test_health_reports_missing_key():
    client = TestClient(create_app())  # no lifespan, so no FDC client is created
    assert client.get("/api/health").json() == {"ok": True, "food_search": False}


def test_parse(client):
    res = client.post("/api/parse", json={"text": "2 cups flour\n\n1 large egg, beaten"})
    assert res.status_code == 200
    assert res.json() == {
        "ingredients": [
            {
                "text": "2 cups flour",
                "quantity": 2.0,
                "quantity_max": None,
                "unit": "cup",
                "size": None,
                "name": "flour",
                "note": None,
            },
            {
                "text": "1 large egg, beaten",
                "quantity": 1.0,
                "quantity_max": None,
                "unit": None,
                "size": "large",
                "name": "egg",
                "note": "beaten",
            },
        ]
    }


@pytest.mark.parametrize("body", [{}, {"text": 5}, {"text": "x" * 20_001}])
def test_parse_rejects_bad_bodies(client, body):
    assert client.post("/api/parse", json=body).status_code == 422


def test_search(client, search):
    res = client.get("/api/foods/search", params={"q": "  all-purpose   flour ", "limit": 3})
    assert res.status_code == 200
    body = res.json()
    assert body["query"] == "all-purpose flour"
    assert body["foods"][0]["fdc_id"] == 789890
    assert body["foods"][0]["per_100g"]["calories_kcal"] == 366
    assert search.calls == [("all-purpose flour", 3)]


@pytest.mark.parametrize(
    "params",
    [{}, {"q": ""}, {"q": "   "}, {"q": "x" * 101}, {"q": "flour", "limit": 0}, {"q": "flour", "limit": 26}],
)
def test_search_rejects_bad_queries(client, search, params):
    assert client.get("/api/foods/search", params=params).status_code == 422
    assert search.calls == []


def test_search_without_api_key_is_503():
    client = TestClient(create_app())
    res = client.get("/api/foods/search", params={"q": "flour"})
    assert res.status_code == 503
    assert "FDC_API_KEY" in res.json()["detail"]


@pytest.mark.parametrize(("query", "status"), [("down", 502), ("rate limited", 503)])
def test_search_passes_on_upstream_errors(client, query, status):
    res = client.get("/api/foods/search", params={"q": query})
    assert res.status_code == status
    assert "FoodData Central" in res.json()["detail"]


def test_unexpected_errors_stay_hidden(client):
    res = client.get("/api/foods/search", params={"q": "bug"})
    assert res.status_code == 500
    assert "secret internal detail" not in res.text
