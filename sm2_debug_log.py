# ═══════════════════════════════════════════════════════════════════════════════
#  SM-2 DEBUG LOGGER  —  v1
#
#  PURPOSE
#  ───────
#  Diagnose the "card came back on same date as new" bug.
#  Logs 5 checkpoints in a human-readable file next to the data JSON:
#
#    ~/anki_occlusion_debug.log
#
#  CHECKPOINT TAGS
#  ───────────────
#    [SESSION]   App start — separator + timestamp so you can find each run
#    [LOAD]      After reading JSON — every box's full SM-2 state from disk
#    [SAVE]      Before writing to disk — every box's SM-2 state going out
#    [RATE]      In _rate() — state BEFORE and AFTER sched_update()
#    [DUE]       In _build_items() — every box tested + True/False + reason
#    [QUEUE]     In _build_items() — final sorted queue after building
#
#  HOW TO DIAGNOSE
#  ───────────────
#  When the bug recurs, search the log for the affected card's box_id:
#
#    Bug in RATE  → [RATE][BEFORE] correct, [RATE][AFTER] wrong state
#    Bug in SAVE  → [RATE][AFTER] correct but [SAVE] shows old state
#    Bug in LOAD  → [SAVE] correct but next [LOAD] shows different values
#    Bug in DUE   → [LOAD] correct but [DUE] wrongly returns True
#    Bug in QUEUE → [DUE] was False but box still appears in [QUEUE]
#
#  USAGE
#  ─────
#  1. Drop this file next to anki_occlusion_v19.py
#  2. In data_manager.py,   add:  from sm2_debug_log import log_load, log_save
#  3. In anki_occlusion_v19.py,   add:  from sm2_debug_log import log_rate, log_due, log_queue, log_session
#  4. Call each function at the matching point (see INTEGRATION below)
#  5. Run the app, reproduce the bug, then open ~/anki_occlusion_debug.log
#
#  INTEGRATION POINTS  (exact lines — search for these strings)
#  ─────────────────────────────────────────────────────────────
#
#  ① data_manager.py — DirtyStore.load()  after  self._data = json.load(f)
#       from sm2_debug_log import log_load, log_save
#       log_load(self._data)
#
#  ② data_manager.py — DirtyStore._write_to_disk()  before  os.replace(tmp, DATA_FILE)
#       from sm2_debug_log import log_save
#       log_save(data)
#
#  ③ anki_occlusion_v19.py — ReviewScreen.__init__  at top of function  (before the for-card loop)
#       from sm2_debug_log import log_session
#       log_session()
#
#  ④ anki_occlusion_v19.py — ReviewScreen.__init__  inside the  is_due_today(box)  checks
#       from sm2_debug_log import log_due
#       # replace:   if is_due_today(box):
#       # with:
#       _due_result = is_due_today(box)
#       log_due(box, card, _due_result)
#       if _due_result:
#
#  ⑤ anki_occlusion_v19.py — ReviewScreen.__init__  after  self._items.sort(...)
#       from sm2_debug_log import log_queue
#       log_queue(self._items)
#
#  ⑥ anki_occlusion_v19.py — ReviewScreen._rate()  before  sched_update(sm2_obj, quality)
#       from sm2_debug_log import log_rate
#       log_rate("BEFORE", sm2_obj, quality, card)
#       sched_update(sm2_obj, quality)
#       log_rate("AFTER",  sm2_obj, quality, card)
#
# ═══════════════════════════════════════════════════════════════════════════════

import os
import threading
from datetime import datetime
from typing import Dict, Any, Iterator, Tuple, List

# ── Log file location — sits next to the data JSON ───────────────────────────
LOG_FILE = os.path.join(os.path.expanduser("~"), "anki_occlusion_debug.log")

# ── Thread-safe write lock ────────────────────────────────────────────────────
_lock = threading.Lock()

# ── Master on/off switch — set to False to silence all logging ───────────────
ENABLED = False

# ── How many boxes to log per LOAD/SAVE call (0 = all) ───────────────────────
MAX_BOXES_PER_DUMP = 0


# ─────────────────────────────────────────────────────────────────────────────
#  INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _ts() -> str:
    """
    Get the current timestamp formatted as a string.

    Returns:
        str: Current timestamp string for log lines.
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _write(line: str) -> None:
    """
    Append one line to the log file in a thread-safe manner.

    Args:
        line (str): The text line to write.
    """
    if not ENABLED:
        return
    with _lock:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            print(f"[sm2_debug_log] ⚠ Could not write log: {e}")


def _sm2_fields(obj: Dict[str, Any]) -> str:
    """
    Format the key SM-2 fields of a box/card dictionary into a compact string.

    Args:
        obj (dict): The SM-2 object (box or card) containing scheduling fields.

    Returns:
        str: Formatted string representing the SM-2 state.
    """
    if not obj:
        return "(empty)"
    return (
        f"state={obj.get('sched_state', '?'):8s} "
        f"step={obj.get('sched_step', '?')} "
        f"iv={obj.get('sm2_interval', '?'):>4} "
        f"ef={obj.get('sm2_ease', '?'):.2f} "
        f"due={str(obj.get('sm2_due', '?'))[:19]} "
        f"reps={obj.get('sm2_repetitions', '?')} "
        f"last_q={obj.get('sm2_last_quality', '?')} "
        f"reviews={obj.get('reviews', '?')}"
    )


def _box_id(box: Dict[str, Any]) -> str:
    """
    Return a stable short identifier for a box.

    Args:
        box (dict): The dictionary containing box data.

    Returns:
        str: A short stable identifier.
    """
    bid = box.get("box_id", "")
    gid = box.get("group_id", "")
    if bid:
        return f"box:{bid[:12]}"
    if gid:
        return f"grp:{gid[:12]}"
    return "box:???"


def _card_name(card: Dict[str, Any]) -> str:
    """
    Return a short human-readable name for a card.

    Args:
        card (dict): The card data dictionary.

    Returns:
        str: Short name for the card.
    """
    name = card.get("name", card.get("title", ""))
    if name:
        return name[:40]
    cid = card.get("_id", card.get("id", "?"))
    return f"card:{cid}"


def _walk_all_boxes(data: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    Yield (card, box) tuples for every box in the loaded tree.

    Args:
        data (dict): The root data structure containing decks.

    Yields:
        Tuple[dict, dict]: A tuple where the first element is the card and the second is the box
                           or the card itself if no boxes exist.
    """
    def _recurse_decks(decks: List[Dict[str, Any]]) -> Iterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
        for deck in decks:
            for card in deck.get("cards", []):
                boxes = card.get("boxes", [])
                if boxes:
                    for box in boxes:
                        yield card, box
                else:
                    yield card, card       # no-box card — card is own SM-2 object
            yield from _recurse_decks(deck.get("children", []))

    yield from _recurse_decks(data.get("decks", []))


# ─────────────────────────────────────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def log_session() -> None:
    """
    Log the start of a new review session.
    Writes a separator line so each app run is easy to find in the log.
    """
    sep = "=" * 80
    _write(f"\n{sep}")
    _write(f"[SESSION] {_ts()}  — new review session started")
    _write(sep)


def log_load(data: Dict[str, Any]) -> None:
    """
    Log the SM-2 state of all boxes after loading data from disk.

    Args:
        data (dict): The entire loaded application data dictionary.
    """
    _write(f"\n[LOAD] {_ts()} — data loaded from disk")
    count = 0
    for card, box in _walk_all_boxes(data):
        if MAX_BOXES_PER_DUMP and count >= MAX_BOXES_PER_DUMP:
            _write(f"[LOAD]   ... (truncated after {MAX_BOXES_PER_DUMP} boxes)")
            break
        bid    = _box_id(box)
        cname  = _card_name(card)
        fields = _sm2_fields(box)
        _write(f"[LOAD]   {bid}  card='{cname}'  {fields}")
        count += 1
    _write(f"[LOAD]   total boxes logged: {count}")


def log_save(data: Dict[str, Any]) -> None:
    """
    Log the SM-2 state of all boxes before writing data to disk.

    Args:
        data (dict): The entire application data dictionary about to be saved.
    """
    _write(f"\n[SAVE] {_ts()} — writing data to disk")
    count = 0
    for card, box in _walk_all_boxes(data):
        if MAX_BOXES_PER_DUMP and count >= MAX_BOXES_PER_DUMP:
            _write(f"[SAVE]   ... (truncated after {MAX_BOXES_PER_DUMP} boxes)")
            break
        bid    = _box_id(box)
        cname  = _card_name(card)
        fields = _sm2_fields(box)
        _write(f"[SAVE]   {bid}  card='{cname}'  {fields}")
        count += 1
    _write(f"[SAVE]   total boxes logged: {count}")


def log_rate(stage: str, sm2_obj: Dict[str, Any], quality: int, card: Dict[str, Any]) -> None:
    """
    Log the rate evaluation before or after updating the scheduling state.

    Args:
        stage (str): "BEFORE" or "AFTER".
        sm2_obj (dict): The scheduling object being updated.
        quality (int): The rating quality (1 to 5).
        card (dict): The parent card of the SM-2 object.
    """
    q_labels = {1: "Again", 2: "Hard(2)", 3: "Hard", 4: "Good", 5: "Easy"}
    q_str    = q_labels.get(quality, f"q={quality}")
    bid      = _box_id(sm2_obj)
    cname    = _card_name(card)
    fields   = _sm2_fields(sm2_obj)
    _write(f"[RATE][{stage:6s}] {_ts()}  {bid}  card='{cname}'  quality={q_str}  {fields}")


def log_due(box: Dict[str, Any], card: Dict[str, Any], result: bool) -> None:
    """
    Log the result of a due check for a given box.

    Args:
        box (dict): The box being checked.
        card (dict): The parent card.
        result (bool): True if the box is due, False otherwise.
    """
    bid    = _box_id(box)
    cname  = _card_name(card)
    fields = _sm2_fields(box)
    flag   = "✅ DUE " if result else "⏭ SKIP"
    _write(f"[DUE]  {flag}  {_ts()}  {bid}  card='{cname}'  {fields}")


def log_queue(items: List[Tuple[Dict[str, Any], Any, Dict[str, Any]]]) -> None:
    """
    Log the final queue of items to be reviewed.

    Args:
        items (list): A list of tuples (card, box_idx, sm2_obj) representing the queue.
    """
    _write(f"\n[QUEUE] {_ts()} — final review queue ({len(items)} items)")
    for i, (card, box_idx, sm2_obj) in enumerate(items):
        cname  = _card_name(card)
        if isinstance(box_idx, tuple) and box_idx[0] == "group":
            idx_str = f"grp:{box_idx[1][:12]}"
        elif box_idx is None:
            idx_str = "no-box"
        else:
            idx_str = f"idx:{box_idx}"
        fields = _sm2_fields(sm2_obj)
        _write(f"[QUEUE]  [{i:>3}]  {idx_str}  card='{cname}'  {fields}")
    _write("[QUEUE] end of queue")