import os
from datetime import datetime
from sm2_engine import sched_update, sm2_init, is_due_today
from PyQt5.QtWidgets import QListWidgetItem, QListWidget
from PyQt5.QtCore import QTimer
from PyQt5.QtCore import Qt

# Keep the role constants here if they are used in review_manager
QUEUE_ROLE = Qt.UserRole + 10
QUEUE_INDEX_ROLE = Qt.UserRole + 11
REVIEW_SAVE_MIN_INTERVAL = 8.0

from data_manager import store
from services import recovery_manager

# SM-2 fields snapshotted for undo/redo — defined once at module level
_SM2_KEYS = (
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
)


def _sm2_snapshot(obj):
    return {k: obj.get(k) for k in _SM2_KEYS}


def _restore_sm2_snapshot(obj, state):
    for key, value in (state or {}).items():
        if value is None:
            obj.pop(key, None)
        else:
            obj[key] = value


def _sibling_snapshots_for_item(card, box_idx, sm2_obj):
    snapshots = []
    if isinstance(box_idx, tuple) and box_idx[0] == "group":
        gid = box_idx[1]
        for box in card.get("boxes", []):
            if box.get("group_id") == gid and box is not sm2_obj:
                snapshots.append((box, _sm2_snapshot(box)))
    return snapshots


class ReviewSessionManager:
    def __init__(self, rs):
        self.rs = rs
        self._items = []
        self._idx = 0
        self._done = 0
        self._queued_ids = set()
        self._deleted_ids = set()
        self._queue_needs_full_rebuild = True
        self._queue_last_idx = None
        self._queue_last_peek_idx = None
        from collections import deque

        self._review_undo_stack = deque(maxlen=50)
        self._review_redo_stack = deque(maxlen=50)

    def _rate(self, quality):
        card, box_idx, sm2_obj = self._items[self._idx]

        # ── Save snapshot BEFORE rating so Ctrl+Z can restore it ─────────────
        # Snapshot all sm2 objects affected by this rating
        sibling_snapshots = _sibling_snapshots_for_item(card, box_idx, sm2_obj)

        snapshot = {
            "idx": self._idx,
            "done": self._done,
            "items_order": list(self._items),  # shallow copy of order
            "card": card,
            "box_idx": box_idx,
            "quality": quality,
            "sm2_obj": sm2_obj,
            "sm2_state": _sm2_snapshot(sm2_obj),
            "sibling_snapshots": sibling_snapshots,
            "card_reviewed_at": card.get("last_reviewed_at"),
            "recovery_event": None,
        }
        self._review_undo_stack.append(snapshot)
        # New rating clears redo stack
        self._review_redo_stack.clear()

        sched_update(sm2_obj, quality)
        from perf_utils import invalidate_deck_stats

        invalidate_deck_stats()

        # ── Persist review timestamp in metadata ──────────────────────────────
        # Stamped on every rating so "when was this last reviewed?" is always
        # answerable even if the app is force-closed before the next autosave.
        _now = datetime.now().isoformat(timespec="seconds")
        sm2_obj["reviewed_at"] = _now
        sm2_obj["last_quality"] = (
            quality  # convenience alias (sm2_last_quality is SM-2 internal)
        )

        # [FIX] For grouped boxes, apply same SM-2 update to ALL boxes in the group
        # so they all get the same due date and state. Without this, only the first
        # box of the group gets updated — the rest stay "new" and reappear next session.
        if isinstance(box_idx, tuple) and box_idx[0] == "group":
            gid = box_idx[1]
            for box in card.get("boxes", []):
                if box.get("group_id") == gid and box is not sm2_obj:
                    sched_update(box, quality)
                    # Propagate timestamp to every sibling so metadata is consistent
                    box["reviewed_at"] = _now
                    box["last_quality"] = quality

        if box_idx is None:
            card["reviews"] = sm2_obj.get("reviews", 0)
            card["reviewed_at"] = _now  # card-level convenience field for no-box cards

        # Always stamp the parent card with the latest review time
        card["last_reviewed_at"] = _now
        # Persist a tiny recovery event immediately, then debounce the heavy
        # full-data JSON save/backup so review flow and next-PDF loading stay
        # responsive. A forced app kill can replay the recovery event.
        try:
            event = recovery_manager.build_review_event(
                getattr(self.rs, "_data", None), card, box_idx, quality, _now
            )
            snapshot["recovery_event"] = recovery_manager.record_review_event(event)
        except Exception as ex:
            print(f"[Recovery] review checkpoint failed: {ex}")
        store.mark_dirty()
        self.rs._review_data_dirty = True
        # store.save_soon(min_interval=REVIEW_SAVE_MIN_INTERVAL, delay_from_now=True)

        state = sm2_obj.get("sched_state", "review")

        if state in ("learning", "relearn"):
            # Pull delayed learning cards behind untouched review cards. They
            # still stay due-sorted against other learning/relearn cards.
            item = self._items.pop(self._idx)
            self._insert_delayed_learning_item(item)
            self._queue_needs_full_rebuild = True
        else:
            self._done += 1
            self._idx += 1

        # ── NEW: after every rating, bubble any expired learning cards to front ──
        self._promote_expired_learning(self._idx)

        self.rs._load_item()

    def _insert_delayed_learning_item(self, item):
        due_str = item[2].get("sm2_due", "")
        insert_at = len(self._items)
        for j in range(self._idx, len(self._items)):
            other_due = self._items[j][2].get("sm2_due", "")
            if other_due >= due_str:
                insert_at = j
                break
        if self._idx < len(self._items):
            insert_at = max(insert_at, self._idx + 1)
        self._items.insert(insert_at, item)

    def _review_undo(self):
        """
        Undo last rating — restore card to pre-rating SM-2 state.
        Does NOT hard-reset the card — only reverses the last sched_update() call.
        """
        if not self._review_undo_stack:
            self.rs._undo_handled = False
            self.rs.undo_requested_when_empty.emit()
            if self.rs is None:
                return
            if not getattr(self.rs, "_undo_handled", False):
                self.rs.canvas._show_toast("⚠ Nothing to undo")
            return

        snap = self._review_undo_stack.pop()

        # Save current state to redo stack before restoring
        card = snap.get("card")
        box_idx = snap.get("box_idx")
        sm2_obj = snap.get("sm2_obj")

        if sm2_obj is not None:
            redo_snap = {
                "idx": self._idx,
                "done": self._done,
                "items_order": list(self._items),
                "card": card,
                "box_idx": box_idx,
                "quality": snap.get("quality"),
                "sm2_obj": sm2_obj,
                "sm2_state": {k: sm2_obj.get(k) for k in _SM2_KEYS},
                "sibling_snapshots": _sibling_snapshots_for_item(
                    card or {}, box_idx, sm2_obj
                ),
                "card_reviewed_at": card.get("last_reviewed_at") if card else None,
                "recovery_event": None,
            }
            self._review_redo_stack.append(redo_snap)

        # Restore items order (undo any reinsert from learning/relearn)
        self._items = list(snap["items_order"])
        self._queue_needs_full_rebuild = True
        self._idx = snap["idx"]
        self._done = snap["done"]

        # Restore SM-2 state of main box
        sm2_obj = snap["sm2_obj"]
        _restore_sm2_snapshot(sm2_obj, snap["sm2_state"])

        # Restore sibling boxes (grouped cards)
        for box, state in snap["sibling_snapshots"]:
            _restore_sm2_snapshot(box, state)

        # Restore card-level reviewed_at
        card = self._items[self._idx][0] if self._idx < len(self._items) else None
        if card is not None:
            if snap["card_reviewed_at"] is None:
                card.pop("last_reviewed_at", None)
            else:
                card["last_reviewed_at"] = snap["card_reviewed_at"]

        try:
            recovery_manager.discard_review_event(snap.get("recovery_event"))
        except Exception as ex:
            print(f"[Recovery] review checkpoint discard failed: {ex}")
        store.mark_dirty()
        self.rs._review_data_dirty = True
        store.save_force(async_save=True)

        self.rs.canvas._show_toast(f"↩ Undo — back to card {self._idx + 1}")
        self.rs._load_item()

    def _review_redo(self):
        """
        Redo — re-apply the rating that was undone.
        """
        if not self._review_redo_stack:
            self.rs.canvas._show_toast("⚠ Nothing to redo")
            return

        snap = self._review_redo_stack.pop()
        card = snap.get("card")
        box_idx = snap.get("box_idx")
        sm2_obj = snap["sm2_obj"]

        # Save current state back to undo stack
        undo_snap = {
            "idx": self._idx,
            "done": self._done,
            "items_order": list(self._items),
            "card": card,
            "box_idx": box_idx,
            "quality": snap.get("quality"),
            "sm2_obj": sm2_obj,
            "sm2_state": _sm2_snapshot(sm2_obj),
            "sibling_snapshots": _sibling_snapshots_for_item(
                card or {}, box_idx, sm2_obj
            ),
            "card_reviewed_at": card.get("last_reviewed_at") if card else None,
            "recovery_event": None,
        }
        self._review_undo_stack.append(undo_snap)

        self._items = list(snap["items_order"])
        self._queue_needs_full_rebuild = True
        self._idx = snap["idx"]
        self._done = snap["done"]

        _restore_sm2_snapshot(sm2_obj, snap["sm2_state"])
        for box, state in snap.get("sibling_snapshots", []):
            _restore_sm2_snapshot(box, state)

        card = self._items[self._idx][0] if self._idx < len(self._items) else None
        if card is not None:
            if snap["card_reviewed_at"] is None:
                card.pop("last_reviewed_at", None)
            else:
                card["last_reviewed_at"] = snap["card_reviewed_at"]

        try:
            timestamp = datetime.now().isoformat(timespec="seconds")
            event = recovery_manager.build_review_event(
                getattr(self.rs, "_data", None),
                card,
                box_idx,
                snap.get("quality"),
                timestamp,
            )
            undo_snap["recovery_event"] = recovery_manager.record_review_event(event)
        except Exception as ex:
            print(f"[Recovery] review redo checkpoint failed: {ex}")
        store.mark_dirty()
        self.rs._review_data_dirty = True
        # store.save_soon(min_interval=REVIEW_SAVE_MIN_INTERVAL, delay_from_now=True)

        self.rs.canvas._show_toast(f"↪ Redo — card {self._idx + 1}")
        self.rs._load_item()

    def skip_session(self):
        """Skip current card for the current review session only."""
        if not (0 <= self._idx < len(self._items)):
            return

        card, box_idx, sm2_obj = self._items[self._idx]
        sibling_snapshots = _sibling_snapshots_for_item(card, box_idx, sm2_obj)

        snapshot = {
            "idx": self._idx,
            "done": self._done,
            "items_order": list(self._items),
            "card": card,
            "box_idx": box_idx,
            "quality": None,  # no quality for skip
            "sm2_obj": sm2_obj,
            "sm2_state": _sm2_snapshot(sm2_obj),
            "sibling_snapshots": sibling_snapshots,
            "card_reviewed_at": card.get("last_reviewed_at"),
            "recovery_event": None,
        }
        self._review_undo_stack.append(snapshot)
        self._review_redo_stack.clear()

        # Pop from session queue
        self._items.pop(self._idx)
        self._queue_needs_full_rebuild = True

        self.rs.canvas._show_toast("Card skipped for this session")
        self.rs._load_item()

    def super_skip(self):
        """Skip current card for today (reschedule to tomorrow)."""
        if not (0 <= self._idx < len(self._items)):
            return

        card, box_idx, sm2_obj = self._items[self._idx]
        sibling_snapshots = _sibling_snapshots_for_item(card, box_idx, sm2_obj)

        snapshot = {
            "idx": self._idx,
            "done": self._done,
            "items_order": list(self._items),
            "card": card,
            "box_idx": box_idx,
            "quality": None,
            "sm2_obj": sm2_obj,
            "sm2_state": _sm2_snapshot(sm2_obj),
            "sibling_snapshots": sibling_snapshots,
            "card_reviewed_at": card.get("last_reviewed_at"),
            "recovery_event": None,
        }
        self._review_undo_stack.append(snapshot)
        self._review_redo_stack.clear()

        # Reschedule to tomorrow (00:00:00)
        from datetime import date, timedelta, datetime
        due_date = date.today() + timedelta(days=1)
        due_str = datetime.combine(due_date, datetime.min.time()).isoformat(timespec="seconds")

        sm2_obj["sm2_due"] = due_str
        # If grouped, reschedule sibling boxes too
        if isinstance(box_idx, tuple) and box_idx[0] == "group":
            gid = box_idx[1]
            for box in card.get("boxes", []):
                if box.get("group_id") == gid and box is not sm2_obj:
                    box["sm2_due"] = due_str

        # Mark database as dirty so the new due date is saved
        store.mark_dirty()
        self.rs._review_data_dirty = True
        # store.save_soon(min_interval=REVIEW_SAVE_MIN_INTERVAL, delay_from_now=True)

        # Pop from session queue
        self._items.pop(self._idx)
        self._queue_needs_full_rebuild = True

        self.rs.canvas._show_toast("Card skipped until tomorrow")
        self.rs._load_item()

    def _promote_expired_learning(self, insert_pos):
        from datetime import datetime as _dt

        now_str = _dt.now().isoformat(timespec="seconds")

        to_promote = [
            j
            for j in range(insert_pos, len(self._items))
            if self._items[j][2].get("sched_state") in ("learning", "relearn")
            and self._items[j][2].get("sm2_due", "") <= now_str
        ]

        for offset, j in enumerate(to_promote):
            real_j = j - offset
            item = self._items.pop(real_j)
            self._items.insert(insert_pos + offset, item)
        if to_promote:
            self._queue_needs_full_rebuild = True

    def _queue_state_for_index(self, index, peek_idx=None):
        if peek_idx is not None and index == peek_idx:
            return "peek"
        if index < self._idx:
            return "done"
        if index == self._idx:
            return "current"
        sched = self._items[index][2].get("sched_state", "new")
        return "relearn" if sched in ("learning", "relearn") else "pending"

    def _sync_queue_state(self, peek_idx=None):
        """
        Fast path for normal card advances.

        The labels and row order are unchanged, so update only rows whose visual
        state can change instead of rebuilding every QListWidgetItem.
        """
        queue = getattr(self.rs, "_queue_list", None)
        if (
            queue is None
            or self._queue_needs_full_rebuild
            or queue.count() != len(self._items)
        ):
            self._rebuild_queue(peek_idx)
            return

        if peek_idx is None:
            peek_idx = getattr(self.rs, "__dict__", {}).get("_peek_idx")

        if hasattr(self.rs, "_update_queue_label"):
            active_count = sum(1 for _, _, sm2 in self._items if is_due_today(sm2))
            self.rs._update_queue_label(active_count)

        rows = {
            self._idx,
            self._queue_last_idx,
            peek_idx,
            self._queue_last_peek_idx,
        }
        if self._queue_last_idx is not None:
            start = min(int(self._queue_last_idx), int(self._idx))
            end = max(int(self._queue_last_idx), int(self._idx))
            rows.update(range(start, end + 1))
        for row in rows:
            if row is None or not (0 <= int(row) < queue.count()):
                continue
            item = queue.item(int(row))
            if item is not None:
                item.setData(QUEUE_ROLE, self._queue_state_for_index(int(row), peek_idx))

        if 0 <= self._idx < queue.count():
            queue.scrollToItem(queue.item(self._idx), QListWidget.PositionAtCenter)

        self._queue_last_idx = self._idx
        self._queue_last_peek_idx = peek_idx

    def _rebuild_queue(self, peek_idx=None):
        """Rebuild the right-side queue list — reflects current order + states."""
        self.rs._queue_list.clear()
        if hasattr(self.rs, "_update_queue_label"):
            active_count = sum(1 for _, _, sm2 in self._items if is_due_today(sm2))
            self.rs._update_queue_label(active_count)
        if peek_idx is None:
            peek_idx = getattr(self, "_peek_idx", None)
        for i, (card, box_idx, sm2_obj) in enumerate(self._items):
            # ── Page number ───────────────────────────────────────────────────
            # Derive from box Y-center vs canvas _page_tops if available
            page_str = ""
            boxes = card.get("boxes", [])
            if isinstance(box_idx, tuple) and box_idx[0] == "group":
                gid = box_idx[1]
                box_data = next((b for b in boxes if b.get("group_id") == gid), None)
            elif isinstance(box_idx, int) and 0 <= box_idx < len(boxes):
                box_data = boxes[box_idx]
            else:
                box_data = None

            if box_data:
                r = box_data.get("rect")
                if r and self.rs.canvas._page_tops:
                    cy = r[1] + r[3] / 2  # image-space Y center
                    page = 0
                    for pi, top in enumerate(self.rs.canvas._page_tops):
                        if cy >= top:
                            page = pi
                        else:
                            break
                    page_str = f"p.{page + 1} · "

            # ── Box label ─────────────────────────────────────────────────────
            if card.get("card_type") == "text":
                label = f"📝 {card.get('title', 'Text')}"
            elif isinstance(box_idx, tuple) and box_idx[0] == "group":
                gid = box_idx[1]
                # Find box number of first box in group
                grp_num = next(
                    (j + 1 for j, b in enumerate(boxes) if b.get("group_id") == gid),
                    "?",
                )
                label = f"{page_str}#{grp_num} [grp]"
            elif box_idx is None:
                label = f"{page_str}card"
            else:
                label = f"{page_str}#{box_idx + 1}"

            item = QListWidgetItem(label)
            item.setData(QUEUE_INDEX_ROLE, i)
            if peek_idx is not None and i == peek_idx:
                state = "peek"
            elif i < self._idx:
                state = "done"
            elif i == self._idx:
                state = "current"
            else:
                sched = sm2_obj.get("sched_state", "new")
                state = "relearn" if sched in ("learning", "relearn") else "pending"
            item.setData(QUEUE_ROLE, state)
            self.rs._queue_list.addItem(item)
        # Scroll to current card
        if 0 <= self._idx < self.rs._queue_list.count():
            self.rs._queue_list.scrollToItem(
                self.rs._queue_list.item(self._idx), QListWidget.PositionAtCenter
            )
        self._queue_needs_full_rebuild = False
        self._queue_last_idx = self._idx
        self._queue_last_peek_idx = peek_idx

    def _check_learning_due(self):
        """Every 1s check karein kya koi learning card due ho gaya."""
        self.rs._wait_bar.hide()
        pending = [
            (i, sm2_obj)
            for i, (_, _, sm2_obj) in enumerate(self._items)
            if sm2_obj.get("sched_state") in ("learning", "relearn")
        ]
        if not pending:
            self.rs.finished.emit()
            return
        from datetime import datetime as _dt

        now_str = _dt.now().isoformat(timespec="seconds")
        due_now = [(i, obj) for i, obj in pending if obj.get("sm2_due", "") <= now_str]
        if due_now:
            earliest_idx = min(due_now, key=lambda x: x[1].get("sm2_due", ""))[0]
            self._idx = earliest_idx
            self.rs._wait_bar.hide()
            self.rs._show_overlay(self.rs._reveal_bar)
            self.rs._load_item()
        else:
            self.rs._finish()  # re-evaluate wait time
