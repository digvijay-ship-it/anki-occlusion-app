from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import data_manager
from sm2_engine import is_due_today, sm2_update


WEB_DATA_FILE_ENV = "ANKI_OCCLUSION_WEB_DATA"


def default_data_path() -> Path:
    return Path(os.environ.get(WEB_DATA_FILE_ENV) or data_manager.DATA_FILE)


class AnkiWebStore:
    def __init__(self, data_path: str | os.PathLike[str] | None = None):
        self.data_path = Path(data_path) if data_path is not None else default_data_path()

    def load(self) -> dict[str, Any]:
        if not self.data_path.exists():
            return {"decks": []}
        with self.data_path.open("r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {"decks": []}
        data.setdefault("decks", [])
        return data

    def save(self, data: dict[str, Any]) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.data_path.parent), suffix=".tmp", prefix=".anki-web-"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.data_path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def list_decks(self) -> list[dict[str, Any]]:
        return [deck_summary(deck) for deck in self.load().get("decks", [])]

    def summary(self) -> dict[str, Any]:
        data = self.load()
        totals = empty_totals()
        for deck in data.get("decks", []):
            merge_totals(totals, deck_totals(deck))
        totals["source"] = str(self.data_path)
        return totals

    def review_items(self, deck_id: int | str | None = None) -> list[dict[str, Any]]:
        data = self.load()
        items: list[dict[str, Any]] = []
        for deck in iter_decks(data.get("decks", [])):
            if deck_id is not None and str(deck.get("_id", "")) != str(deck_id):
                continue
            items.extend(due_items_for_deck(deck))
        return items

    def rate(self, request: Any) -> dict[str, Any]:
        data = self.load()
        target = find_review_target(
            data,
            card_id=request.card_id,
            deck_id=request.deck_id,
            box_id=request.box_id,
            box_index=request.box_index,
        )
        if target is None:
            return {"updated": False, "target": {}}

        sm2_update(target, request.quality)
        self.save(data)
        return {"updated": True, "target": copy.deepcopy(target)}


def empty_totals() -> dict[str, int]:
    return {
        "deck_count": 0,
        "card_count": 0,
        "occlusion_count": 0,
        "due_items": 0,
        "learning_items": 0,
        "review_items": 0,
    }


def merge_totals(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    for key, value in right.items():
        left[key] = left.get(key, 0) + int(value)
    return left


def iter_decks(decks: list[dict[str, Any]]):
    for deck in decks:
        if not isinstance(deck, dict):
            continue
        yield deck
        yield from iter_decks(child_decks(deck))


def child_decks(deck: dict[str, Any]) -> list[dict[str, Any]]:
    children = deck.get("children", []) or []
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, dict)]


def card_id(card: dict[str, Any]) -> str:
    return str(card.get("_id") or card.get("id") or card.get("title") or "")


def due_check(item: dict[str, Any]) -> bool:
    return is_due_today(copy.deepcopy(item))


def item_state(item: dict[str, Any]) -> str:
    return str(item.get("sched_state") or "new")


def count_due_for_card(card: dict[str, Any]) -> int:
    boxes = card.get("boxes", []) or []
    if boxes:
        return sum(1 for box in boxes if due_check(box))
    return 1 if due_check(card) else 0


def deck_totals(deck: dict[str, Any]) -> dict[str, int]:
    totals = empty_totals()
    totals["deck_count"] = 1
    cards = deck.get("cards", []) or []
    totals["card_count"] += len(cards)
    for card in cards:
        boxes = card.get("boxes", []) or []
        totals["occlusion_count"] += len(boxes)
        review_targets = boxes or [card]
        for target in review_targets:
            if due_check(target):
                totals["due_items"] += 1
            state = item_state(target)
            if state in {"learning", "relearn"}:
                totals["learning_items"] += 1
            elif state == "review":
                totals["review_items"] += 1
    for child in child_decks(deck):
        merge_totals(totals, deck_totals(child))
    return totals


def deck_summary(deck: dict[str, Any]) -> dict[str, Any]:
    children = [deck_summary(child) for child in child_decks(deck)]
    totals = deck_totals(deck)
    return {
        "id": deck.get("_id", ""),
        "name": deck.get("name", "Untitled"),
        "direct_cards": len(deck.get("cards", []) or []),
        "total_cards": totals["card_count"],
        "due_items": totals["due_items"],
        "children": children,
    }


def due_items_for_deck(deck: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for card in deck.get("cards", []) or []:
        boxes = card.get("boxes", []) or []
        if boxes:
            for idx, box in enumerate(boxes):
                if due_check(box):
                    items.append(review_item(deck, card, box, idx))
        elif due_check(card):
            items.append(review_item(deck, card, None, None))
    return items


def review_item(
    deck: dict[str, Any],
    card: dict[str, Any],
    box: dict[str, Any] | None,
    box_index: int | None,
) -> dict[str, Any]:
    target = box or card
    return {
        "deck_id": deck.get("_id", ""),
        "deck_name": deck.get("name", "Untitled"),
        "card_id": card_id(card),
        "card_title": card.get("title") or "Untitled",
        "box_id": None if box is None else str(box.get("box_id") or ""),
        "box_index": box_index,
        "label": "" if box is None else str(box.get("label") or ""),
        "sched_state": item_state(target),
        "sm2_due": target.get("sm2_due"),
    }


def find_review_target(
    data: dict[str, Any],
    card_id: str,
    deck_id: int | str | None = None,
    box_id: str | None = None,
    box_index: int | None = None,
) -> dict[str, Any] | None:
    for deck in iter_decks(data.get("decks", []) or []):
        if deck_id is not None and str(deck.get("_id", "")) != str(deck_id):
            continue
        for card in deck.get("cards", []) or []:
            if card_id != card_id_of(card):
                continue
            boxes = card.get("boxes", []) or []
            if boxes:
                if box_id:
                    for box in boxes:
                        if str(box.get("box_id") or "") == str(box_id):
                            return box
                if box_index is not None and 0 <= int(box_index) < len(boxes):
                    return boxes[int(box_index)]
                return None
            return card
    return None


def card_id_of(card: dict[str, Any]) -> str:
    return card_id(card)
