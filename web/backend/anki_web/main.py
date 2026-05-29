from __future__ import annotations

import mimetypes
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from storage_paths import resolve_asset_path

from .commercial_store import CommercialWebStore, estimate_request_db_units
from .schemas import (
    AppSummary,
    ClientMetricRequest,
    ClientMetricResponse,
    CostSnapshotResponse,
    CurrentUserResponse,
    DeckNode,
    HealthResponse,
    PathRequest,
    RateRequest,
    RateResponse,
    RevealPathResponse,
    ReviewHistoryResponse,
    ReviewItem,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
)
from .store import AnkiWebStore


def get_store() -> AnkiWebStore:
    return AnkiWebStore()


def get_commercial_store() -> CommercialWebStore:
    return CommercialWebStore()


def request_user_id(request: Request) -> str | None:
    return request.headers.get("x-anki-user") or None


def get_current_user(
    request: Request,
    store: CommercialWebStore = Depends(get_commercial_store),
) -> dict:
    user = store.ensure_dev_user(request_user_id(request))
    if not user["entitled"]:
        raise HTTPException(status_code=402, detail="Active subscription required")
    return user


def reveal_file_in_folder(path: str) -> None:
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])


def create_app() -> FastAPI:
    app = FastAPI(title="Anki Occlusion Web API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def record_cost_metrics(request: Request, call_next):
        started = perf_counter()
        response = await call_next(request)
        duration_ms = (perf_counter() - started) * 1000.0
        request_bytes = int(request.headers.get("content-length") or 0)
        response_bytes = int(response.headers.get("content-length") or 0)
        db_reads, db_writes = estimate_request_db_units(
            request.method, request.url.path
        )
        try:
            CommercialWebStore().record_request_metric(
                user_id=request_user_id(request) or "dev-user",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                request_bytes=request_bytes,
                response_bytes=response_bytes,
                db_reads=db_reads,
                db_writes=db_writes,
            )
        except Exception:
            # Metrics should never break the user-facing API.
            pass
        return response

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/api/me", response_model=CurrentUserResponse)
    def me(
        request: Request,
        store: CommercialWebStore = Depends(get_commercial_store),
    ) -> dict:
        return store.ensure_dev_user(request_user_id(request))

    @app.get("/api/summary", response_model=AppSummary)
    def summary(store: AnkiWebStore = Depends(get_store)) -> dict:
        return store.summary()

    @app.get("/api/decks", response_model=list[DeckNode])
    def decks(store: AnkiWebStore = Depends(get_store)) -> list[dict]:
        return store.list_decks()

    @app.get("/api/review/items", response_model=list[ReviewItem])
    def review_items(
        deck_id: int | str | None = None,
        limit: int = 100,
        store: AnkiWebStore = Depends(get_store),
    ) -> list[dict]:
        return store.review_items(deck_id=deck_id, limit=limit)

    @app.post("/api/review/rate", response_model=RateResponse)
    def rate_review_item(
        request: RateRequest,
        store: AnkiWebStore = Depends(get_store),
    ) -> dict:
        return store.rate(request)

    @app.post("/api/review/undo", response_model=ReviewHistoryResponse)
    def undo_review_rating(store: AnkiWebStore = Depends(get_store)) -> dict:
        return store.undo_review_rating()

    @app.post("/api/review/redo", response_model=ReviewHistoryResponse)
    def redo_review_rating(store: AnkiWebStore = Depends(get_store)) -> dict:
        return store.redo_review_rating()

    @app.get("/api/media")
    def media(path: str) -> FileResponse:
        resolved = resolve_asset_path(path)
        if not resolved or not os.path.exists(resolved) or not os.path.isfile(resolved):
            raise HTTPException(status_code=404, detail="Media file not found")
        media_type = mimetypes.guess_type(resolved)[0] or "application/octet-stream"
        return FileResponse(resolved, media_type=media_type, filename=os.path.basename(resolved))

    @app.post("/api/media/reveal", response_model=RevealPathResponse)
    def reveal_media(request: PathRequest) -> dict:
        resolved = resolve_asset_path(request.path)
        if not resolved or not os.path.exists(resolved) or not os.path.isfile(resolved):
            raise HTTPException(status_code=404, detail="Media file not found")
        try:
            reveal_file_in_folder(resolved)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"opened": True, "path": resolved, "message": "Opened containing folder"}

    @app.get("/api/sync/pull", response_model=SyncPullResponse)
    def sync_pull(
        since_revision: int = 0,
        store: CommercialWebStore = Depends(get_commercial_store),
        user: dict = Depends(get_current_user),
    ) -> dict:
        return store.pull_changes(user["user_id"], since_revision)

    @app.post("/api/sync/push", response_model=SyncPushResponse)
    def sync_push(
        request: SyncPushRequest,
        store: CommercialWebStore = Depends(get_commercial_store),
        user: dict = Depends(get_current_user),
    ) -> dict:
        try:
            return store.push_changes(user["user_id"], request.changes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/metrics/client", response_model=ClientMetricResponse)
    def client_metric(
        request: ClientMetricRequest,
        store: CommercialWebStore = Depends(get_commercial_store),
        user: dict = Depends(get_current_user),
    ) -> dict:
        return store.record_client_metric(user["user_id"], request.event, request.payload)

    @app.get("/api/metrics/cost", response_model=CostSnapshotResponse)
    def cost_snapshot(
        store: CommercialWebStore = Depends(get_commercial_store),
        user: dict = Depends(get_current_user),
    ) -> dict:
        return store.cost_snapshot(user["user_id"])

    return app


app = create_app()
