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
    sm2_due: str | None = None


class RateRequest(BaseModel):
    card_id: str
    quality: int = Field(ge=1, le=6)
    deck_id: int | str | None = None
    box_id: str | None = None
    box_index: int | None = None


class RateResponse(BaseModel):
    updated: bool
    target: dict[str, Any]

