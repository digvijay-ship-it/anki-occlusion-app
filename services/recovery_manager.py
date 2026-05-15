import copy
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timedelta

from storage_paths import (
    current_recovery_applied_events_dir,
    current_recovery_drafts_dir,
    current_recovery_pending_events_dir,
    ensure_recovery_dirs,
)

RETENTION_DAYS = 30
SCHEMA_VERSION = 1

REVIEW_FIELD_KEYS = (
    "sched_state",
    "sched_step",
    "sm2_interval",
    "sm2_ease",
    "sm2_due",
    "sm2_last_quality",
    "sm2_repetitions",
    "reviews",
    "reviewed_at",
    "last_quality",
    "last_reviewed_at",
)


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _safe_stamp(value=None):
    raw = value or _now_iso()
    return str(raw).replace(":", "").replace("-", "").replace(".", "")


def new_draft_id():
    return uuid.uuid4().hex


def new_event_id():
    return uuid.uuid4().hex


def _atomic_write_json(path, payload):
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        with open(tmp, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if not isinstance(loaded, dict):
            raise ValueError("Recovery payload must be a JSON object.")
        _replace_file_with_retry(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _replace_file_with_retry(src, dst, attempts=8, delay=0.05):
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))


def _read_json(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("Recovery record must be a JSON object.")
    return data


def _json_files(folder):
    if not os.path.isdir(folder):
        return []
    return [
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if name.lower().endswith(".json")
    ]


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _record_time(path, record):
    for key in ("updated_at", "timestamp", "created_at"):
        parsed = _parse_dt(record.get(key))
        if parsed is not None:
            return parsed
    try:
        return datetime.fromtimestamp(os.path.getmtime(path))
    except Exception:
        return datetime.now()


def _is_old(path, record, days):
    return _record_time(path, record) < datetime.now() - timedelta(days=days)


def prune_old_records(days=RETENTION_DAYS):
    ensure_recovery_dirs()
    deleted = 0
    for folder in (
        current_recovery_drafts_dir(),
        current_recovery_pending_events_dir(),
        current_recovery_applied_events_dir(),
    ):
        for path in _json_files(folder):
            try:
                record = _read_json(path)
                if _is_old(path, record, days):
                    os.unlink(path)
                    deleted += 1
            except Exception:
                continue
    return deleted


def draft_path(draft_id):
    return os.path.join(current_recovery_drafts_dir(), f"draft_{draft_id}.json")


def save_editor_draft(payload):
    ensure_recovery_dirs()
    draft = copy.deepcopy(payload or {})
    draft_id = draft.get("draft_id") or new_draft_id()
    now = _now_iso()
    draft.update(
        {
            "schema_version": SCHEMA_VERSION,
            "record_type": "editor_draft",
            "draft_id": draft_id,
            "updated_at": now,
        }
    )
    draft.setdefault("created_at", now)
    _atomic_write_json(draft_path(draft_id), draft)
    return draft


def load_editor_drafts():
    ensure_recovery_dirs()
    drafts = []
    for path in _json_files(current_recovery_drafts_dir()):
        try:
            draft = _read_json(path)
            if draft.get("record_type") == "editor_draft":
                draft["_path"] = path
                drafts.append(draft)
        except Exception:
            continue
    drafts.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
    return drafts


def delete_editor_draft(draft_id):
    path = draft_path(draft_id)
    if os.path.exists(path):
        os.unlink(path)
        return True
    return False


def draft_to_card(draft):
    card = copy.deepcopy((draft or {}).get("card") or {})
    card.setdefault("title", "Recovered Draft")
    card.setdefault("tags", [])
    card.setdefault("notes", "")
    card.setdefault("boxes", [])
    return card


def _iter_decks(data, trail=None):
    trail = list(trail or [])
    for deck in (data or {}).get("decks", []) or []:
        if not isinstance(deck, dict):
            continue
        name = str(deck.get("name", "") or f"deck_{deck.get('_id', 'x')}")
        current = trail + [name]
        yield deck, current
        child_decks = deck.get("children", []) or deck.get("subdecks", []) or []
        yield from _iter_decks({"decks": child_decks}, current)


def _iter_cards(data):
    for deck, deck_path in _iter_decks(data):
        cards = deck.get("cards", []) or []
        for idx, card in enumerate(cards):
            if isinstance(card, dict):
                yield deck, deck_path, idx, card


def _same_card(candidate, card):
    if candidate is card:
        return True
    if not isinstance(candidate, dict) or not isinstance(card, dict):
        return False
    keys = ("created", "pdf_path", "image_path", "title")
    common = [key for key in keys if candidate.get(key) and card.get(key)]
    return bool(common) and all(candidate.get(key) == card.get(key) for key in common)


def find_deck_path(data, deck):
    if not isinstance(deck, dict):
        return []
    deck_id = deck.get("_id")
    for candidate, path in _iter_decks(data):
        if candidate is deck or (deck_id is not None and candidate.get("_id") == deck_id):
            return path
    return []


def find_card_locator(data, card, deck=None):
    if not isinstance(card, dict):
        return {}
    deck_filter_id = deck.get("_id") if isinstance(deck, dict) else None
    for candidate_deck, deck_path, idx, candidate in _iter_cards(data):
        if deck_filter_id is not None and candidate_deck.get("_id") != deck_filter_id:
            continue
        if _same_card(candidate, card):
            return {
                "deck_id": candidate_deck.get("_id"),
                "deck_path": deck_path,
                "card_index": idx,
                "title": candidate.get("title", ""),
                "created": candidate.get("created", ""),
                "pdf_path": candidate.get("pdf_path", ""),
                "image_path": candidate.get("image_path", ""),
            }
    return {
        "deck_id": deck_filter_id,
        "deck_path": find_deck_path(data, deck),
        "title": card.get("title", ""),
        "created": card.get("created", ""),
        "pdf_path": card.get("pdf_path", ""),
        "image_path": card.get("image_path", ""),
    }


def _find_deck_by_id(data, deck_id):
    if deck_id is None:
        return None
    for deck, _path in _iter_decks(data):
        if deck.get("_id") == deck_id:
            return deck
    return None


def _locator_score(card, locator):
    score = 0
    for key, weight in (
        ("created", 6),
        ("pdf_path", 5),
        ("image_path", 5),
        ("title", 2),
    ):
        value = locator.get(key)
        if value and card.get(key) == value:
            score += weight
        elif value:
            return -1
    return score


def find_card_by_locator(data, locator):
    locator = locator or {}
    candidates = []
    deck = _find_deck_by_id(data, locator.get("deck_id"))
    if deck is not None:
        cards = deck.get("cards", []) or []
        idx = locator.get("card_index")
        if isinstance(idx, int) and 0 <= idx < len(cards):
            card = cards[idx]
            if isinstance(card, dict) and _locator_score(card, locator) >= 0:
                return card, deck, idx, "ok"
        for idx, card in enumerate(cards):
            if isinstance(card, dict):
                score = _locator_score(card, locator)
                if score >= 0:
                    candidates.append((score, card, deck, idx))
    else:
        for candidate_deck, _deck_path, idx, card in _iter_cards(data):
            score = _locator_score(card, locator)
            if score >= 0:
                candidates.append((score, card, candidate_deck, idx))

    if not candidates:
        return None, None, None, "missing"
    candidates.sort(key=lambda row: row[0], reverse=True)
    best = candidates[0][0]
    best_rows = [row for row in candidates if row[0] == best]
    if len(best_rows) > 1:
        return None, None, None, "ambiguous"
    _score, card, deck, idx = best_rows[0]
    return card, deck, idx, "ok"


def _snapshot_fields(obj, keys=REVIEW_FIELD_KEYS):
    return {key: copy.deepcopy(obj[key]) for key in keys if key in obj}


def _box_locator(card, box, index):
    return {
        "box_id": box.get("box_id", ""),
        "group_id": box.get("group_id", ""),
        "box_index": index,
    }


def build_review_event(data, card, box_idx, quality, timestamp=None):
    timestamp = timestamp or _now_iso()
    card_locator = find_card_locator(data, card)
    updates = []

    if box_idx is None:
        updates.append(
            {
                "target": "card",
                "fields": _snapshot_fields(card),
            }
        )
    elif isinstance(box_idx, tuple) and box_idx[0] == "group":
        gid = box_idx[1]
        for idx, box in enumerate(card.get("boxes", []) or []):
            if box.get("group_id") == gid:
                updates.append(
                    {
                        "target": "box",
                        "box_locator": _box_locator(card, box, idx),
                        "fields": _snapshot_fields(box),
                    }
                )
    elif isinstance(box_idx, int):
        boxes = card.get("boxes", []) or []
        if 0 <= box_idx < len(boxes):
            box = boxes[box_idx]
            updates.append(
                {
                    "target": "box",
                    "box_locator": _box_locator(card, box, box_idx),
                    "fields": _snapshot_fields(box),
                }
            )

    updates.append(
        {
            "target": "card_meta",
            "fields": {
                key: copy.deepcopy(card[key])
                for key in ("last_reviewed_at", "reviewed_at", "reviews")
                if key in card
            },
        }
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "review_event",
        "event_id": new_event_id(),
        "timestamp": timestamp,
        "quality": quality,
        "card_locator": card_locator,
        "updates": updates,
    }


def review_event_path(event):
    event_id = event.get("event_id") or new_event_id()
    stamp = _safe_stamp(event.get("timestamp"))
    return os.path.join(current_recovery_pending_events_dir(), f"{stamp}_{event_id}.json")


def record_review_event(event):
    ensure_recovery_dirs()
    payload = copy.deepcopy(event or {})
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("record_type", "review_event")
    payload.setdefault("event_id", new_event_id())
    payload.setdefault("timestamp", _now_iso())
    _atomic_write_json(review_event_path(payload), payload)
    return payload


def load_pending_review_events():
    ensure_recovery_dirs()
    events = []
    for path in _json_files(current_recovery_pending_events_dir()):
        try:
            event = _read_json(path)
            if event.get("record_type") == "review_event":
                event["_path"] = path
                events.append(event)
        except Exception:
            continue
    events.sort(key=lambda event: event.get("timestamp", ""))
    return events


def _locate_box(card, locator):
    boxes = card.get("boxes", []) or []
    box_id = (locator or {}).get("box_id")
    if box_id:
        matches = [
            (idx, box)
            for idx, box in enumerate(boxes)
            if isinstance(box, dict) and box.get("box_id") == box_id
        ]
        if len(matches) == 1:
            return matches[0][1], "ok"
        if len(matches) > 1:
            return None, "ambiguous"
    idx = (locator or {}).get("box_index")
    if isinstance(idx, int) and 0 <= idx < len(boxes):
        return boxes[idx], "ok"
    gid = (locator or {}).get("group_id")
    if gid:
        matches = [box for box in boxes if isinstance(box, dict) and box.get("group_id") == gid]
        if len(matches) == 1:
            return matches[0], "ok"
        if len(matches) > 1:
            return None, "ambiguous"
    return None, "missing"


def _fields_match(obj, fields):
    return all(obj.get(key) == value for key, value in (fields or {}).items())


def review_event_status(data, event):
    card, _deck, _idx, status = find_card_by_locator(data, event.get("card_locator"))
    if status != "ok":
        return status

    all_match = True
    for update in event.get("updates", []) or []:
        target = update.get("target")
        fields = update.get("fields", {}) or {}
        if target in ("card", "card_meta"):
            obj = card
        elif target == "box":
            obj, box_status = _locate_box(card, update.get("box_locator"))
            if box_status != "ok":
                return box_status
        else:
            continue
        if not _fields_match(obj, fields):
            all_match = False
    return "already_applied" if all_match else "recoverable"


def apply_review_event(data, event):
    card, _deck, _idx, status = find_card_by_locator(data, event.get("card_locator"))
    if status != "ok":
        return status

    status = review_event_status(data, event)
    if status == "already_applied":
        return status
    if status != "recoverable":
        return status

    for update in event.get("updates", []) or []:
        target = update.get("target")
        fields = update.get("fields", {}) or {}
        if target in ("card", "card_meta"):
            obj = card
        elif target == "box":
            obj, box_status = _locate_box(card, update.get("box_locator"))
            if box_status != "ok":
                return box_status
        else:
            continue
        obj.update(copy.deepcopy(fields))
    return "applied"


def _mark_event_applied(event):
    source = event.get("_path")
    payload = copy.deepcopy(event)
    payload.pop("_path", None)
    payload["applied_at"] = _now_iso()
    target = os.path.join(
        current_recovery_applied_events_dir(),
        os.path.basename(source or review_event_path(payload)),
    )
    _atomic_write_json(target, payload)
    if source and os.path.exists(source):
        os.unlink(source)


def scan_recovery(data):
    prune_old_records()
    drafts = load_editor_drafts()
    pending_events = []
    moved_applied = 0
    for event in load_pending_review_events():
        status = review_event_status(data, event)
        if status == "already_applied":
            _mark_event_applied(event)
            moved_applied += 1
        else:
            item = copy.deepcopy(event)
            item["status"] = status
            pending_events.append(item)
    return {
        "drafts": drafts,
        "review_events": pending_events,
        "moved_applied": moved_applied,
    }


def apply_pending_review_events(data):
    applied = 0
    already_applied = 0
    blocked = []
    for event in load_pending_review_events():
        status = apply_review_event(data, event)
        if status == "applied":
            applied += 1
            _mark_event_applied(event)
        elif status == "already_applied":
            already_applied += 1
            _mark_event_applied(event)
        else:
            blocked.append({"event_id": event.get("event_id"), "status": status})
    prune_old_records()
    return {
        "applied": applied,
        "already_applied": already_applied,
        "blocked": blocked,
    }
