"""PlateMath API. Run it with:  uvicorn api.main:app --reload"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Protocol

import httpx2
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .errors import NotConfiguredError, ServiceError
from .fdc import FdcClient, FoodMatch
from .parser import ParsedIngredient, parse_recipe

logger = logging.getLogger("platemath")


class FoodSearch(Protocol):
    async def search(self, query: str, *, limit: int = 5) -> list[FoodMatch]: ...


class ParseRequest(BaseModel):
    text: str = Field(max_length=20_000, description="Ingredient list, one ingredient per line")


class ParseResponse(BaseModel):
    ingredients: list[ParsedIngredient]


class SearchResponse(BaseModel):
    query: str
    foods: list[FoodMatch]


class HealthResponse(BaseModel):
    ok: bool
    food_search: bool = Field(description="False until FDC_API_KEY is set")


def create_app(food_search: FoodSearch | None = None) -> FastAPI:
    """Builds the app. Tests pass a fake `food_search`; otherwise one is made from FDC_API_KEY."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.food_search is not None:
            yield
            return
        load_dotenv()
        api_key = os.environ.get("FDC_API_KEY", "").strip()
        if not api_key:
            logger.warning("FDC_API_KEY isn't set, so food search is off. See .env.example.")
            yield
            return
        async with httpx2.AsyncClient(timeout=10.0) as http:
            app.state.food_search = FdcClient(api_key, http=http)
            yield
            app.state.food_search = None

    app = FastAPI(
        title="PlateMath API",
        summary="Paste a recipe, get nutrition per serving.",
        version="0.0.0",
        lifespan=lifespan,
    )
    app.state.food_search = food_search

    @app.exception_handler(ServiceError)
    async def service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        logger.warning("%s: %s", type(exc).__name__, exc.message, exc_info=exc.__cause__)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.get("/api/health")
    async def health(request: Request) -> HealthResponse:
        return HealthResponse(ok=True, food_search=request.app.state.food_search is not None)

    @app.post("/api/parse")
    async def parse(body: ParseRequest) -> ParseResponse:
        """Splits an ingredient list into quantity, unit, size, name and notes for each line."""
        return ParseResponse(ingredients=parse_recipe(body.text))

    @app.get("/api/foods/search")
    async def search_foods(
        request: Request,
        q: Annotated[str, Query(min_length=1, max_length=100, description="What to search for")],
        limit: Annotated[int, Query(ge=1, le=25)] = 5,
    ) -> SearchResponse:
        """Foods in FoodData Central that match `q`, best first, with nutrients per 100 g."""
        query = " ".join(q.split())
        if not query:
            raise HTTPException(status_code=422, detail="q can't be blank")
        searcher: FoodSearch | None = request.app.state.food_search
        if searcher is None:
            raise NotConfiguredError("Food search is off because the server has no FDC_API_KEY")
        return SearchResponse(query=query, foods=await searcher.search(query, limit=limit))

    return app


app = create_app()
