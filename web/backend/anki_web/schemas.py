from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool = True
    app: str = "anki-occlusion-web"


class DeckNode(BaseModel):
    id: int | str
    name: str
    direct_cards: int = 0
    total_cards: int = 0
    due_items: int = 0
    children: list["DeckNode"] = Field(default_factory=list)


class AppSummary(BaseModel):
    deck_count: int = 0
    card_count: int = 0
    occlusion_count: int = 0
    due_items: int = 0
    learning_items: int = 0
    review_items: int = 0
    source: str


class ReviewItem(BaseModel):
    deck_id: int | str
    deck_name: str
    card_id: str
    card_title: str
    box_id: str | None = None
    box_index: int | None = None
    label: str = ""
    sched_state: str = "new"
    sched_step: int = 0
    sm2_interval: int = 1
    sm2_ease: float = 2.5
    sm2_due: str | None = None
    sm2_last_quality: int = -1
    sm2_repetitions: int = 0
    reviews: int = 0
    rating_previews: dict[str, str] = Field(default_factory=dict)
    page_num: int = 0
    rect: list[float] = Field(default_factory=list)
    shape: str = "rect"
    angle: float = 0.0
    group_id: str = ""
    target_kind: str = "card"
    target_box_ids: list[str] = Field(default_factory=list)
    target_box_indexes: list[int] = Field(default_factory=list)
    boxes: list[dict[str, Any]] = Field(default_factory=list)
    pdf_box_render_zoom: float = 1.5
    pdf_path: str | None = None
    image_path: str | None = None


class RateRequest(BaseModel):
    card_id: str
    quality: int = Field(ge=1, le=6)
    deck_id: int | str | None = None
    box_id: str | None = None
    box_index: int | None = None
    group_id: str | None = None


class RateResponse(BaseModel):
    updated: bool
    target: dict[str, Any]
    can_undo: bool = False
    can_redo: bool = False


class ReviewHistoryResponse(BaseModel):
    updated: bool
    can_undo: bool = False
    can_redo: bool = False
    message: str = ""


class PathRequest(BaseModel):
    path: str


class RevealPathResponse(BaseModel):
    opened: bool
    path: str = ""
    message: str = ""


class CurrentUserResponse(BaseModel):
    user_id: str
    email: str
    plan: str
    entitled: bool


class SyncChange(BaseModel):
    collection: str
    item_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    deleted: bool = False
    revision: int | None = None


class SyncPullResponse(BaseModel):
    revision: int = 0
    changes: list[SyncChange] = Field(default_factory=list)


class SyncPushRequest(BaseModel):
    base_revision: int = 0
    changes: list[SyncChange] = Field(default_factory=list)


class SyncPushResponse(BaseModel):
    accepted: int = 0
    revision: int = 0
    conflicts: list[SyncChange] = Field(default_factory=list)


class ClientMetricRequest(BaseModel):
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ClientMetricResponse(BaseModel):
    recorded: bool


class CostSnapshotResponse(BaseModel):
    request_count: int = 0
    request_bytes: int = 0
    response_bytes: int = 0
    avg_duration_ms: float = 0.0
    db_reads: int = 0
    db_writes: int = 0
    sync_changes: int = 0
    storage_bytes: int = 0
    slow_routes: list[dict[str, Any]] = Field(default_factory=list)
