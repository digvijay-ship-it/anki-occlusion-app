import os
import threading
import json
import time
from contextlib import contextmanager
from datetime import date

from sm2_engine import is_due_today, sm2_init

fitz = None
_FITZ_IMPORT_ATTEMPTED = False


_pdf_page_count_cache = {}
_pdf_page_count_lock = threading.Lock()

# ── Deck Stats Memoization ────────────────────────────────────────────────────
_DECK_STATS_CACHE = {}
_CACHE_DATE = None
_CACHE_FINGERPRINT = None
_CACHE_REF = None
_STATS_LOCK = threading.Lock()
_PERF_LOG_LOCK = threading.Lock()

PERF_DEBUG_ENV = "ANKI_PERF_DEBUG"
PERF_LOG_PATH_ENV = "ANKI_PERF_LOG_PATH"
PERF_BREAKPOINT_ENV = "ANKI_PERF_BREAKPOINT"


def _env_truthy(name):
    raw = os.environ.get(name, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def perf_debug_enabled():
    return _env_truthy(PERF_DEBUG_ENV) or bool(
        os.environ.get(PERF_LOG_PATH_ENV, "").strip()
    )


def perf_log_path():
    raw = os.environ.get(PERF_LOG_PATH_ENV, "").strip()
    if raw:
        return os.path.abspath(os.path.expanduser(raw))
    return os.path.join(os.path.expanduser("~"), "anki_occlusion_perf.jsonl")


def _perf_safe_value(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_perf_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _perf_safe_value(v) for k, v in value.items()}
    return str(value)


def _perf_breakpoint_requested(event):
    raw = os.environ.get(PERF_BREAKPOINT_ENV, "").strip()
    if not raw:
        return False
    lowered = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return bool(
        lowered
        & {
            "1",
            "true",
            "yes",
            "on",
            "all",
            str(event).strip().lower(),
        }
    )


def maybe_perf_breakpoint(event):
    if _perf_breakpoint_requested(event):
        breakpoint()


def perf_log(event, **fields):
    if not perf_debug_enabled():
        return None

    record = {
        "ts": time.time(),
        "event": str(event),
        **{str(key): _perf_safe_value(value) for key, value in fields.items()},
    }
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    path = perf_log_path()
    with _PERF_LOG_LOCK:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    print(f"[PROFILE][perf] {line}")
    maybe_perf_breakpoint(event)
    return record


@contextmanager
def perf_timer(event, **fields):
    if not perf_debug_enabled():
        yield None
        return

    start = time.perf_counter()
    try:
        yield None
    finally:
        perf_log(
            event,
            elapsed_ms=round((time.perf_counter() - start) * 1000.0, 3),
            **fields,
        )


def invalidate_deck_stats():
    """Clear the memoized deck statistics. Call this when data changes."""
    global _DECK_STATS_CACHE, _CACHE_DATE, _CACHE_FINGERPRINT, _CACHE_REF
    with _STATS_LOCK:
        _DECK_STATS_CACHE = {}
        _CACHE_DATE = None
        _CACHE_FINGERPRINT = None
        _CACHE_REF = None


def _deck_stats_fingerprint(decks):
    parts = []

    def _walk(items):
        for deck in items or []:
            if not isinstance(deck, dict):
                continue
            cards = deck.get("cards", []) or []
            children = deck.get("children", []) or []
            parts.append(("deck", deck.get("_id"), len(cards), len(children)))
            for card in cards:
                if not isinstance(card, dict):
                    continue
                boxes = card.get("boxes", []) or []
                parts.append(
                    (
                        "card",
                        card.get("_id"),
                        card.get("sched_state"),
                        card.get("sm2_due"),
                        card.get("reviews"),
                        len(boxes),
                    )
                )
                for box in boxes:
                    if not isinstance(box, dict):
                        continue
                    parts.append(
                        (
                            "box",
                            box.get("box_id"),
                            box.get("group_id"),
                            box.get("sched_state"),
                            box.get("sm2_due"),
                            box.get("reviews"),
                        )
                    )
            _walk(children)

    _walk(decks)
    return tuple(parts)


def card_has_due_today(card):
    boxes = card.get("boxes", [])
    if not boxes:
        return is_due_today(card)

    seen_groups = set()
    for box in boxes:
        gid = box.get("group_id", "")
        if gid:
            if gid in seen_groups:
                continue
            seen_groups.add(gid)
        if is_due_today(box):
            return True
    return False


def count_due_units_in_card(card):
    boxes = card.get("boxes", [])
    if not boxes:
        return 1 if is_due_today(card) else 0

    seen_groups = set()
    due_units = 0
    for box in boxes:
        gid = box.get("group_id", "")
        if gid:
            if gid in seen_groups:
                continue
            seen_groups.add(gid)
        if is_due_today(box):
            due_units += 1
    return due_units


def build_deck_rollups(decks):
    global _DECK_STATS_CACHE, _CACHE_DATE, _CACHE_FINGERPRINT, _CACHE_REF

    today = date.today()
    from data_manager import store
    is_store_decks = (decks is store.get().get("decks"))
    if is_store_decks:
        current_ref = store.revision
    else:
        current_ref = _deck_stats_fingerprint(decks)

    # Single lock scope: check cache, compute if stale, store — no double-entry gap
    with _STATS_LOCK:
        if (
            _CACHE_DATE == today
            and _CACHE_REF == current_ref
            and _DECK_STATS_CACHE
        ):
            return _DECK_STATS_CACHE

        total_cards = {}
        due_cards = {}
        due_units = {}

        def _walk(deck):
            deck_id = deck.get("_id")
            card_count = len(deck.get("cards", []))
            due_card_count = 0
            due_unit_count = 0

            for card in deck.get("cards", []):
                if card_has_due_today(card):
                    due_card_count += 1
                due_unit_count += count_due_units_in_card(card)

            for child in deck.get("children", []):
                child_cards, child_due_cards, child_due_units = _walk(child)
                card_count += child_cards
                due_card_count += child_due_cards
                due_unit_count += child_due_units

            if deck_id is not None:
                total_cards[deck_id] = card_count
                due_cards[deck_id] = due_card_count
                due_units[deck_id] = due_unit_count

            return card_count, due_card_count, due_unit_count

        for deck in decks:
            _walk(deck)

        _DECK_STATS_CACHE = {
            "total_cards": total_cards,
            "due_cards": due_cards,
            "due_units": due_units,
        }
        _CACHE_DATE = today
        _CACHE_FINGERPRINT = current_ref if not is_store_decks else None
        _CACHE_REF = current_ref
        return _DECK_STATS_CACHE


def get_pdf_page_count(path):
    global fitz, _FITZ_IMPORT_ATTEMPTED
    if not _FITZ_IMPORT_ATTEMPTED:
        _FITZ_IMPORT_ATTEMPTED = True
        try:
            import fitz as _fitz

            fitz = _fitz
        except ImportError:  # pragma: no cover - optional dependency
            fitz = None

    if not path or fitz is None or not os.path.exists(path):
        return 0

    abs_path = os.path.abspath(path)
    try:
        stat = os.stat(abs_path)
        cache_key = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return 0

    with _pdf_page_count_lock:
        cached = _pdf_page_count_cache.get(abs_path)
        if cached and cached[:2] == cache_key:
            return cached[2]

    try:
        doc = fitz.open(abs_path)
        try:
            page_count = len(doc)
        finally:
            doc.close()
    except Exception:
        page_count = 0

    with _pdf_page_count_lock:
        _pdf_page_count_cache[abs_path] = (cache_key[0], cache_key[1], page_count)

    return page_count
