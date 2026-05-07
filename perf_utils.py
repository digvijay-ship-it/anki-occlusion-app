import os
import threading

from sm2_engine import is_due_today, sm2_init

try:
    import fitz
except ImportError:  # pragma: no cover - optional dependency
    fitz = None


_pdf_page_count_cache = {}
_pdf_page_count_lock = threading.Lock()


def card_has_due_today(card):
    boxes = card.get("boxes", [])
    if not boxes:
        sm2_init(card)
        return is_due_today(card)

    seen_groups = set()
    for box in boxes:
        sm2_init(box)
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
        sm2_init(card)
        return 1 if is_due_today(card) else 0

    seen_groups = set()
    due_units = 0
    for box in boxes:
        sm2_init(box)
        gid = box.get("group_id", "")
        if gid:
            if gid in seen_groups:
                continue
            seen_groups.add(gid)
        if is_due_today(box):
            due_units += 1
    return due_units


def build_deck_rollups(decks):
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

    return {
        "total_cards": total_cards,
        "due_cards": due_cards,
        "due_units": due_units,
    }


def get_pdf_page_count(path):
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
