# Changelog

Notable changes go here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

- Project started.
- FastAPI app with `GET /api/health`.
- `POST /api/parse`: splits ingredient lines into quantity, unit, size, name and notes. Handles fractions, ranges, unicode fractions, metric and US units, and skips blank lines and section headings.
- `GET /api/foods/search`: searches FoodData Central's generic foods and returns nutrients per 100 g. The API key stays on the server and goes in a header, never the URL. Results are cached for a day.
- Tests for the parser, the cache, the FoodData Central client and the HTTP routes, using a recorded FoodData Central response. GitHub Actions runs them on Python 3.11 to 3.13.
