# Roadmap

Rough plan. Estimates are my guesses and will change.

## v0.1.0: first usable version
- [x] FastAPI app with a health check
- [x] Parse ingredient lines: fractions, ranges, units, sizes and notes (`POST /api/parse`)
- [x] Search FoodData Central with the key kept on the server, results cached (`GET /api/foods/search`)
- [x] Tests and GitHub Actions CI
- [ ] Gram weights: load each food's portions (`/v1/food/{fdcId}`) and convert cups, spoons and counts ("2 large eggs") to grams (~4h)
- [ ] Pick the best match for each line automatically, and flag weak matches for the user to check (~3h)
- [ ] Per-serving totals: `POST /api/analyze` takes the recipe and servings, returns totals and the lines it couldn't convert (~3h)
- [ ] React (Vite) client: paste box, servings, a table of matches and totals (~6h)
- [ ] Deploy the API and the client, then tag v0.1.0 (~3h)

## v0.2.0
- [ ] Let the user pick a different match for any line (~4h)
- [ ] Printable nutrition label (~5h)
- [ ] Unusual units: pinch, dash, stick, and package sizes like "1 (14.5 oz) can" (~3h)
- [ ] Lines with two amounts: "1 cup plus 2 tablespoons", "100g/3½oz" (~2h)

## Later
- [ ] Import a recipe from a URL using its schema.org Recipe data (~4h)
- [ ] Rate limiting on the API (~1h)
- [ ] Client tests (~2h)
- [ ] Accessibility and mobile layout pass (~2h)
