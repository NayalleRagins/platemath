# PlateMath



Paste a recipe, get nutrition per serving.

PlateMath matches each ingredient line to USDA FoodData Central, converts the units, and adds everything up. You can fix any match it gets wrong.

It's for recipes, not personal diet tracking. Nothing about you is stored.

## Status

Early. The API works: it splits ingredient lines into amount, unit and ingredient, and searches FoodData Central for matching foods with their nutrients per 100 g. Converting amounts to grams, per-serving totals and the React app are next. What's planned and what's done is in [ROADMAP.md](ROADMAP.md).

## Running it locally

Needs Python 3.11 or newer.

```bash

cp .env.example .env            # add your FoodData Central key

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
uvicorn api.main:app --reload   # interactive docs at http://localhost:8000/docs
```

Without a key, parsing still works and food search returns 503. The tests use a recorded FoodData Central response, so they need neither a key nor a network connection.

## API

### `POST /api/parse`

Splits an ingredient list into parts, one ingredient per line. Blank lines and headings like "For the glaze:" are skipped.

```bash
curl -X POST http://localhost:8000/api/parse \
  -H "Content-Type: application/json" \
  -d '{"text": "1 1/2 cups all-purpose flour\n2 large eggs, beaten\na pinch of salt"}'
```

```json
{
  "ingredients": [
    { "text": "1 1/2 cups all-purpose flour", "quantity": 1.5, "quantity_max": null, "unit": "cup", "size": null, "name": "all-purpose flour", "note": null },
    { "text": "2 large eggs, beaten", "quantity": 2.0, "quantity_max": null, "unit": null, "size": "large", "name": "eggs", "note": "beaten" },
    { "text": "a pinch of salt", "quantity": 1.0, "quantity_max": null, "unit": "pinch", "size": null, "name": "salt", "note": null }
  ]
}
```

It understands fractions (`1 1/2`, `1-1/2`, `½`, `1½`), ranges (`2-3`, `2 to 3`), metric and US units including `400g` written together, `T`/`t` for tablespoon/teaspoon, sizes (`large`), package sizes (`1 (14.5 oz) can`), and notes after a comma or in parentheses.

### `GET /api/foods/search?q=<text>&limit=<1-25>`

Foods in FoodData Central that match, best first, with nutrients per 100 g. Searches USDA's generic foods (Foundation and SR Legacy), not branded products.

```json
{
  "query": "all-purpose flour",
  "foods": [
    {
      "fdc_id": 789890,
      "description": "Flour, wheat, all-purpose, enriched, bleached",
      "data_type": "Foundation",
      "category": "Cereal Grains and Pasta",
      "per_100g": {
        "calories_kcal": 366.0, "protein_g": 10.9, "fat_g": 1.48, "saturated_fat_g": null,
        "carbs_g": 77.3, "fiber_g": null, "sugars_g": null, "sodium_mg": 2.0, "cholesterol_mg": null
      }
    }
  ]
}
```

`null` means FoodData Central has no value for that nutrient, which isn't the same as zero.

| Status | When |
| --- | --- |
| 200 | Search ran (the list can be empty) |
| 422 | `q` is missing, blank or over 100 characters, or `limit` is outside 1–25 |
| 502 | FoodData Central failed, couldn't be reached, or rejected the API key |
| 503 | The server has no `FDC_API_KEY`, or the key's hourly limit is used up |

Results are cached for a day, and identical searches that arrive together share one request, so the key's hourly limit goes further.

### `GET /api/health`

Returns `{ "ok": true, "food_search": true }`. `food_search` is `false` until `FDC_API_KEY` is set.

## Built with

Python and FastAPI for parsing and lookups, httpx2 for calls to FoodData Central, pytest and GitHub Actions for tests. The front end will be React (Vite). The API sits in between so the FoodData Central key never reaches the browser.

## Data

Nutrient data: U.S. Department of Agriculture, Agricultural Research Service. FoodData Central. https://fdc.nal.usda.gov/ (CC0). Numbers are estimates, not medical or dietary advice.

## License

MIT, see [LICENSE](LICENSE).
