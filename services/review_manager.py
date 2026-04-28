import os
from datetime import datetime
from sm2_engine import sched_update, sm2_init, is_due_today
from PyQt5.QtWidgets import QListWidgetItem, QListWidget
from PyQt5.QtCore import QTimer
from PyQt5.QtCore import Qt

# Keep the role constants here if they are used in review_manager
QUEUE_ROLE       = Qt.UserRole + 10
QUEUE_INDEX_ROLE = Qt.UserRole + 11

from data_manager import store

try:
    from sm2_debug_log import log_rate, log_session, log_due, log_queue
    _DEBUG_LOG = True
except ImportError:
    _DEBUG_LOG = False

class ReviewSessionManager:
    def __init__(self, rs):
        self.rs = rs
        self._items = []
        self._idx = 0
        self._done = 0
        self._queued_ids = set()
        self._deleted_ids = set()
        self._review_undo_stack = []
        self._review_redo_stack = []

    def _rate(self, quality):
        card, box_idx, sm2_obj = self._items[self._idx]

        # ── Save snapshot BEFORE rating so Ctrl+Z can restore it ─────────────
        _SM2_KEYS = ("sched_state", "sched_step", "sm2_interval", "sm2_ease",
                     "sm2_due", "sm2_last_quality", "sm2_repetitions", "reviews",
                     "reviewed_at", "last_quality")

        def _sm2_snapshot(obj):
            return {k: obj.get(k) for k in _SM2_KEYS}

        # Snapshot all sm2 objects affected by this rating
        sibling_snapshots = []
        if isinstance(box_idx, tuple) and box_idx[0] == "group":
            gid = box_idx[1]
            for box in card.get("boxes", []):
                if box.get("group_id") == gid and box is not sm2_obj:
                    sibling_snapshots.append((box, _sm2_snapshot(box)))

        snapshot = {
            "idx":               self._idx,
            "done":              self._done,
            "items_order":       list(self._items),   # shallow copy of order
            "sm2_obj":           sm2_obj,
            "sm2_state":         _sm2_snapshot(sm2_obj),
            "sibling_snapshots": sibling_snapshots,
            "card_reviewed_at":  card.get("last_reviewed_at"),
        }
        self._review_undo_stack.append(snapshot)
        if len(self._review_undo_stack) > 50:
            self._review_undo_stack.pop(0)
        # New rating clears redo stack
        self._review_redo_stack.clear()

        if _DEBUG_LOG:
            try: log_rate("BEFORE", sm2_obj, quality, card)
            except Exception: pass
        sched_update(sm2_obj, quality)
        if _DEBUG_LOG:
            try: log_rate("AFTER", sm2_obj, quality, card)
            except Exception: pass

        # ── Persist review timestamp in metadata ──────────────────────────────
        # Stamped on every rating so "when was this last reviewed?" is always
        # answerable even if the app is force-closed before the next autosave.
        _now = datetime.now().isoformat(timespec="seconds")
        sm2_obj["reviewed_at"]      = _now
        sm2_obj["last_quality"]     = quality   # convenience alias (sm2_last_quality is SM-2 internal)

        # [FIX] For grouped boxes, apply same SM-2 update to ALL boxes in the group
        # so they all get the same due date and state. Without this, only the first
        # box of the group gets updated — the rest stay "new" and reappear next session.
        if isinstance(box_idx, tuple) and box_idx[0] == "group":
            gid = box_idx[1]
            for box in card.get("boxes", []):
                if box.get("group_id") == gid and box is not sm2_obj:
                    sched_update(box, quality)
                    # Propagate timestamp to every sibling so metadata is consistent
                    box["reviewed_at"]  = _now
                    box["last_quality"] = quality

        if box_idx is None:
            card["reviews"]      = sm2_obj.get("reviews", 0)
            card["reviewed_at"]  = _now   # card-level convenience field for no-box cards

        # Always stamp the parent card with the latest review time
        card["last_reviewed_at"] = _now

        # ── Immediate, unconditional save after every rating ──────────────────
        # mark_dirty() then save_force() guarantees the rating survives a crash,
        # power loss, or force-close between the review and the 60s autosave tick.
        store.mark_dirty()
        store.save_force()   # crash-safe atomic write — replaces save_if_dirty() here

        state = sm2_obj.get("sched_state", "review")

        if state in ("learning", "relearn"):
            # Pull item out and re-insert by due time
            item = self._items.pop(self._idx)
            due_str = sm2_obj.get("sm2_due", "")
            insert_at = len(self._items)
            for j in range(self._idx, len(self._items)):
                other_due = self._items[j][2].get("sm2_due", "")
                if other_due >= due_str:
                    insert_at = j
                    break
            self._items.insert(insert_at, item)
        else:
            self._done += 1
            self._idx  += 1

        # ── NEW: after every rating, bubble any expired learning cards to front ──
        self._promote_expired_learning(self._idx)

        self.rs._load_item()

    def _review_undo(self):
        """
        Undo last rating — restore card to pre-rating SM-2 state.
        Does NOT hard-reset the card — only reverses the last sched_update() call.
        """
        if not self._review_undo_stack:
            self.rs.canvas._show_toast("⚠ Nothing to undo")
            return

        snap = self._review_undo_stack.pop()

        # Save current state to redo stack before restoring
        card, box_idx, sm2_obj = self._items[self._idx] if self._idx < len(self._items) \
            else self._items[-1] if self._items else (None, None, None)

        _SM2_KEYS = ("sched_state", "sched_step", "sm2_interval", "sm2_ease",
                     "sm2_due", "sm2_last_quality", "sm2_repetitions", "reviews",
                     "reviewed_at", "last_quality")

        if sm2_obj is not None:
            redo_snap = {
                "idx":               self._idx,
                "done":              self._done,
                "items_order":       list(self._items),
                "sm2_obj":           sm2_obj,
                "sm2_state":         {k: sm2_obj.get(k) for k in _SM2_KEYS},
                "sibling_snapshots": [],
                "card_reviewed_at":  card.get("last_reviewed_at") if card else None,
            }
            self._review_redo_stack.append(redo_snap)

        # Restore items order (undo any reinsert from learning/relearn)
        self._items = list(snap["items_order"])
        self._idx   = snap["idx"]
        self._done  = snap["done"]

        # Restore SM-2 state of main box
        sm2_obj = snap["sm2_obj"]
        for k, v in snap["sm2_state"].items():
            if v is None:
                sm2_obj.pop(k, None)
            else:
                sm2_obj[k] = v

        # Restore sibling boxes (grouped cards)
        for box, state in snap["sibling_snapshots"]:
            for k, v in state.items():
                if v is None:
                    box.pop(k, None)
                else:
                    box[k] = v

        # Restore card-level reviewed_at
        card = self._items[self._idx][0] if self._idx < len(self._items) else None
        if card is not None:
            if snap["card_reviewed_at"] is None:
                card.pop("last_reviewed_at", None)
            else:
                card["last_reviewed_at"] = snap["card_reviewed_at"]

        store.mark_dirty()
        store.save_force()

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

        # Save current state back to undo stack
        self._review_undo_stack.append({
            "idx":               self._idx,
            "done":              self._done,
            "items_order":       list(self._items),
            "sm2_obj":           snap["sm2_obj"],
            "sm2_state":         {k: snap["sm2_obj"].get(k) for k in
                                  ("sched_state","sched_step","sm2_interval","sm2_ease",
                                   "sm2_due","sm2_last_quality","sm2_repetitions","reviews",
                                   "reviewed_at","last_quality")},
            "sibling_snapshots": [],
            "card_reviewed_at":  self._items[self._idx][0].get("last_reviewed_at")
                                  if self._idx < len(self._items) else None,
        })

        self._items = list(snap["items_order"])
        self._idx   = snap["idx"]
        self._done  = snap["done"]

        sm2_obj = snap["sm2_obj"]
        for k, v in snap["sm2_state"].items():
            if v is None:
                sm2_obj.pop(k, None)
            else:
                sm2_obj[k] = v

        card = self._items[self._idx][0] if self._idx < len(self._items) else None
        if card is not None:
            if snap["card_reviewed_at"] is None:
                card.pop("last_reviewed_at", None)
            else:
                card["last_reviewed_at"] = snap["card_reviewed_at"]

        store.mark_dirty()
        store.save_force()

        self.rs.canvas._show_toast(f"↪ Redo — card {self._idx + 1}")
        self.rs._load_item()

    def _promote_expired_learning(self, insert_pos):
        from datetime import datetime as _dt
        now_str = _dt.now().isoformat(timespec="seconds")

        to_promote = [
            j for j in range(insert_pos, len(self._items))
            if self._items[j][2].get("sched_state") in ("learning", "relearn")
            and self._items[j][2].get("sm2_due", "") <= now_str
        ]

        for offset, j in enumerate(to_promote):
            real_j = j - offset
            item = self._items.pop(real_j)
            self._items.insert(insert_pos + offset, item)

    def _rebuild_queue(self, peek_idx=None):
        """Rebuild the right-side queue list — reflects current order + states."""
        self.rs._queue_list.clear()
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
            if isinstance(box_idx, tuple) and box_idx[0] == "group":
                gid = box_idx[1]
                # Find box number of first box in group
                grp_num = next(
                    (j + 1 for j, b in enumerate(boxes) if b.get("group_id") == gid),
                    "?"
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
                self.rs._queue_list.item(self._idx),
                QListWidget.PositionAtCenter
            )

    def _check_learning_due(self):
        """Every 1s check karein kya koi learning card due ho gaya."""
        self.rs._wait_bar.hide()
        pending = [
            (i, sm2_obj) for i, (_, _, sm2_obj) in enumerate(self._items)
            if sm2_obj.get("sched_state") in ("learning", "relearn")
        ]
        if not pending:
            self.rs.finished.emit()
            return
        from datetime import datetime as _dt
        now_str = _dt.now().isoformat(timespec="seconds")
        due_now = [
            (i, obj) for i, obj in pending
            if obj.get("sm2_due", "") <= now_str
        ]
        if due_now:
            earliest_idx = min(due_now, key=lambda x: x[1].get("sm2_due", ""))[0]
            self._idx = earliest_idx
            self.rs._wait_bar.hide()
            self.rs._show_overlay(self.rs._reveal_bar)
            self.rs._load_item()
        else:
            self.rs._finish()   # re-evaluate wait time

