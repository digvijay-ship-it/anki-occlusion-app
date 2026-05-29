from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import data_manager
from sm2_engine import _fmt_due_interval, is_due_today, sched_update


WEB_DATA_FILE_ENV = "ANKI_OCCLUSION_WEB_DATA"
HISTORY_LIMIT = 50


class _ReviewDataHistory:
    def __init__(self):
        self._undo = deque(maxlen=HISTORY_LIMIT)
        self._redo = deque(maxlen=HISTORY_LIMIT)
        self._lock = threading.Lock()

    @staticmethod
    def _snapshot(data: dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _restore(snapshot: str) -> dict[str, Any]:
        return json.loads(snapshot)

    def push_rating_snapshot(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._undo.append(self._snapshot(data))
            self._redo.clear()

    def undo(self, current_data: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            if not self._undo:
                return None
            self._redo.append(self._snapshot(current_data))
            return self._restore(self._undo.pop())

    def redo(self, current_data: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            if not self._redo:
                return None
            self._undo.append(self._snapshot(current_data))
            return self._restore(self._redo.pop())

    def status(self) -> dict[str, bool]:
        with self._lock:
            return {"can_undo": bool(self._undo), "can_redo": bool(self._redo)}


_HISTORY_LOCK = threading.Lock()
_HISTORY_BY_PATH: dict[str, _ReviewDataHistory] = {}


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

    def _history(self) -> _ReviewDataHistory:
        key = os.path.normcase(os.path.abspath(os.fspath(self.data_path)))
        with _HISTORY_LOCK:
            history = _HISTORY_BY_PATH.get(key)
            if history is None:
                history = _ReviewDataHistory()
                _HISTORY_BY_PATH[key] = history
            return history

    def review_history_status(self) -> dict[str, bool]:
        return self._history().status()

    def list_decks(self) -> list[dict[str, Any]]:
        return [deck_summary(deck) for deck in self.load().get("decks", [])]

    def summary(self) -> dict[str, Any]:
        data = self.load()
        totals = empty_totals()
        for deck in data.get("decks", []):
            merge_totals(totals, deck_totals(deck))
        totals["source"] = str(self.data_path)
        return totals

    def review_items(
        self, deck_id: int | str | None = None, limit: int | None = 100
    ) -> list[dict[str, Any]]:
        data = self.load()
        items: list[dict[str, Any]] = []
        max_items = None if limit is None else max(1, int(limit))
        for deck in iter_decks(data.get("decks", [])):
            if deck_id is not None and str(deck.get("_id", "")) != str(deck_id):
                continue
            items.extend(due_items_for_deck(deck))
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]
        return items

    def rate(self, request: Any) -> dict[str, Any]:
        data = self.load()
        card, targets = find_review_targets(
            data,
            card_id=request.card_id,
            deck_id=request.deck_id,
            box_id=request.box_id,
            box_index=request.box_index,
            group_id=getattr(request, "group_id", None),
        )
        if not targets:
            return {
                "updated": False,
                "target": {},
                **self.review_history_status(),
            }

        self._history().push_rating_snapshot(data)
        now = datetime.now().isoformat(timespec="seconds")
        for target in targets:
            sched_update(target, request.quality)
            target["reviewed_at"] = now
            target["last_quality"] = request.quality
        if card is not None:
            card["last_reviewed_at"] = now
            if targets[0] is card:
                card["reviewed_at"] = now
                card["reviews"] = targets[0].get("reviews", 0)
        self.save(data)
        return {
            "updated": True,
            "target": copy.deepcopy(targets[0]),
            **self.review_history_status(),
        }

    def undo_review_rating(self) -> dict[str, Any]:
        data = self.load()
        restored = self._history().undo(data)
        if restored is None:
            return {
                "updated": False,
                "message": "Nothing to undo",
                **self.review_history_status(),
            }
        self.save(restored)
        return {
            "updated": True,
            "message": "Review rating undone",
            **self.review_history_status(),
        }

    def redo_review_rating(self) -> dict[str, Any]:
        data = self.load()
        restored = self._history().redo(data)
        if restored is None:
            return {
                "updated": False,
                "message": "Nothing to redo",
                **self.review_history_status(),
            }
        self.save(restored)
        return {
            "updated": True,
            "message": "Review rating redone",
            **self.review_history_status(),
        }


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


def schedule_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "sched_state": item_state(item),
        "sched_step": int(item.get("sched_step") or 0),
        "sm2_interval": int(item.get("sm2_interval") or 1),
        "sm2_ease": float(item.get("sm2_ease") or 2.5),
        "sm2_due": item.get("sm2_due"),
        "sm2_last_quality": int(item.get("sm2_last_quality", item.get("last_quality", -1)) or -1),
        "sm2_repetitions": int(item.get("sm2_repetitions") or 0),
        "reviews": int(item.get("reviews") or 0),
    }


def rating_previews(item: dict[str, Any]) -> dict[str, str]:
    try:
        return {str(quality): label for quality, label in _fmt_due_interval(copy.deepcopy(item)).items()}
    except Exception:
        return {}


def count_due_for_card(card: dict[str, Any]) -> int:
    return len([entry for entry in review_entries_for_card(card) if entry["due"]])


def deck_totals(deck: dict[str, Any]) -> dict[str, int]:
    totals = empty_totals()
    totals["deck_count"] = 1
    cards = deck.get("cards", []) or []
    totals["card_count"] += len(cards)
    for card in cards:
        entries = review_entries_for_card(card)
        boxes = card.get("boxes", []) or []
        totals["occlusion_count"] += len(boxes)
        for entry in entries:
            target = entry["target"]
            if entry["due"]:
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
        for entry in review_entries_for_card(card):
            if entry["due"]:
                items.append(
                    review_item(
                        deck,
                        card,
                        None if entry["box_index"] is None else entry["target"],
                        entry["box_index"],
                        group_id=entry["group_id"],
                        target_box_indexes=entry["target_box_indexes"],
                    )
                )
    return items


def review_entries_for_card(card: dict[str, Any]) -> list[dict[str, Any]]:
    boxes = card.get("boxes", []) or []
    if not boxes:
        return [
            {
                "target": card,
                "box_index": None,
                "group_id": "",
                "target_box_indexes": [],
                "due": due_check(card),
            }
        ]

    entries: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    for idx, box in enumerate(boxes):
        group_id = str(box.get("group_id") or "")
        if group_id:
            if group_id in seen_groups:
                continue
            seen_groups.add(group_id)
            group_members = [
                (member_idx, member)
                for member_idx, member in enumerate(boxes)
                if str(member.get("group_id") or "") == group_id
            ]
            primary_idx, primary = next(
                (
                    (member_idx, member)
                    for member_idx, member in group_members
                    if due_check(member)
                ),
                group_members[0],
            )
            entries.append(
                {
                    "target": primary,
                    "box_index": primary_idx,
                    "group_id": group_id,
                    "target_box_indexes": [member_idx for member_idx, _ in group_members],
                    "due": any(due_check(member) for _, member in group_members),
                }
            )
            continue
        entries.append(
            {
                "target": box,
                "box_index": idx,
                "group_id": "",
                "target_box_indexes": [idx],
                "due": due_check(box),
            }
        )
    return entries


def box_payload(box: dict[str, Any], box_index: int) -> dict[str, Any]:
    return {
        "box_index": box_index,
        "box_id": str(box.get("box_id") or ""),
        "label": str(box.get("label") or ""),
        "rect": list(box.get("rect") or []),
        "shape": str(box.get("shape") or "rect"),
        "angle": float(box.get("angle") or 0.0),
        "group_id": str(box.get("group_id") or ""),
        "page_num": int(box.get("page_num") or 0),
        **schedule_payload(box),
        "rating_previews": rating_previews(box),
    }


def review_item(
    deck: dict[str, Any],
    card: dict[str, Any],
    box: dict[str, Any] | None,
    box_index: int | None,
    *,
    group_id: str = "",
    target_box_indexes: list[int] | None = None,
) -> dict[str, Any]:
    target = box or card
    boxes = card.get("boxes", []) or []
    target_box_indexes = target_box_indexes or ([] if box_index is None else [box_index])
    target_box_ids = [
        str(boxes[idx].get("box_id") or "")
        for idx in target_box_indexes
        if 0 <= int(idx) < len(boxes) and boxes[idx].get("box_id")
    ]
    return {
        "deck_id": deck.get("_id", ""),
        "deck_name": deck.get("name", "Untitled"),
        "card_id": card_id(card),
        "card_title": card.get("title") or "Untitled",
        "box_id": None if box is None else str(box.get("box_id") or ""),
        "box_index": box_index,
        "label": "" if box is None else str(box.get("label") or ""),
        **schedule_payload(target),
        "rating_previews": rating_previews(target),
        "page_num": int(target.get("page_num") or 0),
        "rect": list(target.get("rect") or []),
        "shape": str(target.get("shape") or "rect"),
        "angle": float(target.get("angle") or 0.0),
        "group_id": str(group_id or target.get("group_id") or ""),
        "target_kind": "group" if group_id else "box" if box is not None else "card",
        "target_box_ids": target_box_ids,
        "target_box_indexes": target_box_indexes,
        "boxes": [box_payload(item, idx) for idx, item in enumerate(boxes)],
        "pdf_box_render_zoom": float(card.get("_pdf_box_render_zoom") or 1.5),
        "pdf_path": card.get("pdf_path"),
        "image_path": card.get("image_path"),
    }


def find_review_targets(
    data: dict[str, Any],
    card_id: str,
    deck_id: int | str | None = None,
    box_id: str | None = None,
    box_index: int | None = None,
    group_id: str | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    for deck in iter_decks(data.get("decks", []) or []):
        if deck_id is not None and str(deck.get("_id", "")) != str(deck_id):
            continue
        for card in deck.get("cards", []) or []:
            if card_id != card_id_of(card):
                continue
            boxes = card.get("boxes", []) or []
            if boxes:
                if group_id:
                    group_targets = [
                        box
                        for box in boxes
                        if str(box.get("group_id") or "") == str(group_id)
                    ]
                    return card, group_targets
                if box_id:
                    for box in boxes:
                        if str(box.get("box_id") or "") == str(box_id):
                            sibling_group = str(box.get("group_id") or "")
                            if sibling_group:
                                return card, [
                                    item
                                    for item in boxes
                                    if str(item.get("group_id") or "") == sibling_group
                                ]
                            return card, [box]
                if box_index is not None and 0 <= int(box_index) < len(boxes):
                    box = boxes[int(box_index)]
                    sibling_group = str(box.get("group_id") or "")
                    if sibling_group:
                        return card, [
                            item
                            for item in boxes
                            if str(item.get("group_id") or "") == sibling_group
                        ]
                    return card, [box]
                return card, []
            return card, [card]
    return None, []


def find_review_target(
    data: dict[str, Any],
    card_id: str,
    deck_id: int | str | None = None,
    box_id: str | None = None,
    box_index: int | None = None,
) -> dict[str, Any] | None:
    _card, targets = find_review_targets(
        data,
        card_id=card_id,
        deck_id=deck_id,
        box_id=box_id,
        box_index=box_index,
    )
    return targets[0] if targets else None


def card_id_of(card: dict[str, Any]) -> str:
    return card_id(card)
