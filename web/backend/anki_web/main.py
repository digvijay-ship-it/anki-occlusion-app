from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .schemas import AppSummary, DeckNode, HealthResponse, RateRequest, RateResponse, ReviewItem
from .store import AnkiWebStore


def get_store() -> AnkiWebStore:
    return AnkiWebStore()


def create_app() -> FastAPI:
    app = FastAPI(title="Anki Occlusion Web API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/api/summary", response_model=AppSummary)
    def summary(store: AnkiWebStore = Depends(get_store)) -> dict:
        return store.summary()

    @app.get("/api/decks", response_model=list[DeckNode])
    def decks(store: AnkiWebStore = Depends(get_store)) -> list[dict]:
        return store.list_decks()

    @app.get("/api/review/items", response_model=list[ReviewItem])
    def review_items(
        deck_id: int | str | None = None,
        store: AnkiWebStore = Depends(get_store),
    ) -> list[dict]:
        return store.review_items(deck_id=deck_id)

    @app.post("/api/review/rate", response_model=RateResponse)
    def rate_review_item(
        request: RateRequest,
        store: AnkiWebStore = Depends(get_store),
    ) -> dict:
        return store.rate(request)

    return app


app = create_app()

