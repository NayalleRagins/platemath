"""Client for the USDA FoodData Central API (https://fdc.nal.usda.gov/api-guide)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx2

from .cache import TtlCache
from .errors import RateLimitedError, UpstreamError

FDC_BASE_URL = "https://api.nal.usda.gov/fdc/v1"

# Foundation and SR Legacy are USDA's generic foods ("Flour, wheat, all-purpose"),
# which fit recipes better than the hundreds of thousands of branded products.
DEFAULT_DATA_TYPES = ("Foundation", "SR Legacy")

# FDC updates its data a few times a year, so a day is plenty fresh.
SEARCH_TTL_SECONDS = 24 * 60 * 60

logger = logging.getLogger("platemath.fdc")


@dataclass(frozen=True)
class Nutrients:
    """Amounts in 100 g of the food. None means FoodData Central has no value for it."""

    calories_kcal: float | None
    protein_g: float | None
    fat_g: float | None
    saturated_fat_g: float | None
    carbs_g: float | None
    fiber_g: float | None
    sugars_g: float | None
    sodium_mg: float | None
    cholesterol_mg: float | None


@dataclass(frozen=True)
class FoodMatch:
    fdc_id: int
    description: str
    data_type: str
    category: str | None
    per_100g: Nutrients


# FDC nutrient IDs for each field. When a food has more than one, the first wins.
_NUTRIENT_IDS: dict[str, tuple[int, ...]] = {
    "protein_g": (1003,),  # Protein
    "fat_g": (1004, 1085),  # Total lipid (fat); Total fat (NLEA)
    "saturated_fat_g": (1258,),  # Fatty acids, total saturated
    "carbs_g": (1005, 1050),  # Carbohydrate, by difference; by summation
    "fiber_g": (1079,),  # Fiber, total dietary
    "sugars_g": (2000, 1063),  # Total Sugars; Sugars, Total NLEA
    "sodium_mg": (1093,),  # Sodium, Na
    "cholesterol_mg": (1253,),  # Cholesterol
}
# Energy in kcal. Some newer Foundation foods only list the Atwater versions.
_KCAL_IDS = (1008, 2047, 2048)  # Energy; Atwater General Factors; Atwater Specific Factors
_KJ_ID = 1062
_KJ_PER_KCAL = 4.184


class FdcClient:
    """Searches FoodData Central. The API key only ever goes in a request header."""

    def __init__(
        self,
        api_key: str,
        *,
        http: httpx2.AsyncClient,
        base_url: str = FDC_BASE_URL,
        cache: TtlCache | None = None,
        data_types: Iterable[str] = DEFAULT_DATA_TYPES,
    ) -> None:
        if not api_key:
            raise ValueError("FdcClient needs an API key")
        self._api_key = api_key
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._cache = cache if cache is not None else TtlCache()
        self._data_types = ",".join(data_types)

    async def search(self, query: str, *, limit: int = 5) -> list[FoodMatch]:
        """Foods matching `query`, best match first, with nutrients per 100 g."""
        query = " ".join(query.lower().split())
        if not query:
            return []
        return await self._cache.get_or_load(
            ("search", query, limit),
            SEARCH_TTL_SECONDS,
            lambda: self._search(query, limit),
        )

    async def _search(self, query: str, limit: int) -> list[FoodMatch]:
        data = await self._get_json(
            "/foods/search",
            {"query": query, "dataType": self._data_types, "pageSize": limit},
        )
        foods = data.get("foods") if isinstance(data, dict) else None
        if not isinstance(foods, list):
            raise UpstreamError("FoodData Central sent a search result without a food list")
        matches = (to_food_match(food) for food in foods)
        return [match for match in matches if match is not None]

    async def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        url = self._base_url + path
        try:
            res = await self._http.get(url, params=params, headers={"X-Api-Key": self._api_key})
        except httpx2.HTTPError as exc:
            raise UpstreamError("Couldn't reach FoodData Central") from exc

        if res.status_code == 429:
            raise RateLimitedError("FoodData Central's rate limit is used up for now. Try again later.")
        if res.status_code in (401, 403):
            logger.error("FoodData Central rejected the API key (HTTP %s). Check FDC_API_KEY.", res.status_code)
            raise UpstreamError("FoodData Central rejected the server's API key")
        if not res.is_success:
            raise UpstreamError(f"FoodData Central returned HTTP {res.status_code}")
        try:
            return res.json()
        except ValueError as exc:
            raise UpstreamError("FoodData Central sent a response that isn't JSON") from exc


def to_food_match(food: Any) -> FoodMatch | None:
    """Converts one food from an FDC search result. Returns None if it's malformed."""
    if not isinstance(food, dict):
        return None
    fdc_id, description = food.get("fdcId"), food.get("description")
    if not isinstance(fdc_id, int) or not isinstance(description, str):
        return None

    by_id: dict[int, dict[str, Any]] = {}
    for nutrient in food.get("foodNutrients") or []:
        if isinstance(nutrient, dict) and _is_number(nutrient.get("value")):
            by_id.setdefault(nutrient.get("nutrientId"), nutrient)

    def first(ids: tuple[int, ...], unit: str | None = None) -> float | None:
        for nutrient_id in ids:
            nutrient = by_id.get(nutrient_id)
            if nutrient and (unit is None or str(nutrient.get("unitName", "")).upper() == unit):
                return float(nutrient["value"])
        return None

    calories = first(_KCAL_IDS, "KCAL")
    if calories is None:
        kilojoules = first((_KJ_ID,), "KJ")
        calories = round(kilojoules / _KJ_PER_KCAL, 1) if kilojoules is not None else None

    category = food.get("foodCategory")
    return FoodMatch(
        fdc_id=fdc_id,
        description=description,
        data_type=str(food.get("dataType", "")),
        category=category if isinstance(category, str) else None,
        per_100g=Nutrients(
            calories_kcal=calories,
            **{field: first(ids) for field, ids in _NUTRIENT_IDS.items()},
        ),
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
