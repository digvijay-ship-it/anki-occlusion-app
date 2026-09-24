# -*- coding: utf-8 -*-
"""
services/study_flow_service.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Daily Study Flow & Session Tile Planner Service.

Provides:
- Chunking of daily deck study targets into bite-sized session tiles.
- Daily playlist sequencing, interleaving, re-ordering, and persistence.
- Dynamic card collection with inter-tile deduplication.
- Flow execution state tracking and routine templates.
"""

import uuid
import time
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple, Set

from data_manager import store
from perf_utils import card_has_due_today, count_new_units_in_card


class FlowTile:
    """Represents a discrete session chunk in the daily study flow."""

    def __init__(
        self,
        deck_id: Any,
        deck_name: str,
        deck_path: str = "",
        target_cards: int = 25,
        mode: str = "due",
        completed_cards: int = 0,
        status: str = "pending",
        tile_id: Optional[str] = None,
        created_at: Optional[float] = None,
        target_due: int = 0,
        target_new: int = 0,
    ):
        self.id = tile_id or uuid.uuid4().hex[:10]
        self.deck_id = deck_id
        self.deck_name = str(deck_name or "General Deck")
        self.deck_path = str(deck_path or self.deck_name)
        self.target_cards = max(1, int(target_cards))
        self.mode = str(mode or "due")  # "due", "new", "all"
        self.completed_cards = max(0, int(completed_cards))
        self.status = str(status or "pending")  # "pending", "active", "completed", "skipped"
        self.created_at = created_at or time.time()
        self.target_due = max(0, int(target_due))
        self.target_new = max(0, int(target_new))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "deck_id": self.deck_id,
            "deck_name": self.deck_name,
            "deck_path": self.deck_path,
            "target_cards": self.target_cards,
            "mode": self.mode,
            "completed_cards": self.completed_cards,
            "status": self.status,
            "created_at": self.created_at,
            "target_due": self.target_due,
            "target_new": self.target_new,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FlowTile":
        return cls(
            deck_id=data.get("deck_id"),
            deck_name=data.get("deck_name", ""),
            deck_path=data.get("deck_path", ""),
            target_cards=data.get("target_cards", 25),
            mode=data.get("mode", "due"),
            completed_cards=data.get("completed_cards", 0),
            status=data.get("status", "pending"),
            tile_id=data.get("id"),
            created_at=data.get("created_at"),
            target_due=data.get("target_due", 0),
            target_new=data.get("target_new", 0),
        )


class DailyStudyPlan:
    """Represents the daily sequence of session tiles for today."""

    def __init__(
        self,
        plan_date: Optional[str] = None,
        tiles: Optional[List[FlowTile]] = None,
        current_tile_idx: int = 0,
        is_active: bool = False,
        created_at: Optional[float] = None,
    ):
        self.date = plan_date or date.today().isoformat()
        self.tiles = list(tiles or [])
        self.current_tile_idx = max(0, int(current_tile_idx))
        self.is_active = bool(is_active)
        self.created_at = created_at or time.time()

    @property
    def total_target_cards(self) -> int:
        return sum(t.target_cards for t in self.tiles)

    @property
    def total_completed_cards(self) -> int:
        return sum(t.completed_cards for t in self.tiles)

    @property
    def completed_tiles_count(self) -> int:
        return sum(1 for t in self.tiles if t.status == "completed")

    @property
    def is_all_completed(self) -> bool:
        return len(self.tiles) > 0 and all(t.status == "completed" for t in self.tiles)

    def get_current_tile(self) -> Optional[FlowTile]:
        if 0 <= self.current_tile_idx < len(self.tiles):
            return self.tiles[self.current_tile_idx]
        return None

    def get_next_tile(self) -> Optional[FlowTile]:
        next_idx = self.current_tile_idx + 1
        if 0 <= next_idx < len(self.tiles):
            return self.tiles[next_idx]
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "tiles": [t.to_dict() for t in self.tiles],
            "current_tile_idx": self.current_tile_idx,
            "is_active": self.is_active,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DailyStudyPlan":
        raw_tiles = data.get("tiles", [])
        tiles = [FlowTile.from_dict(t) for t in raw_tiles if isinstance(t, dict)]
        return cls(
            plan_date=data.get("date"),
            tiles=tiles,
            current_tile_idx=data.get("current_tile_idx", 0),
            is_active=data.get("is_active", False),
            created_at=data.get("created_at"),
        )


class StudyFlowService:
    """Business logic for generating chunks, managing playlists, and resolving cards."""

    @staticmethod
    def generate_tiles(
        deck_id: Any,
        deck_name: str,
        deck_path: str = "",
        total_target: int = 100,
        chunk_size: int = 25,
        mode: str = "due",
        parts: Optional[int] = None,
        target_due: int = 0,
        target_new: int = 0,
        mix_style: str = "mixed",
    ) -> List[FlowTile]:
        """
        Split a subject's card target into bite-sized session tiles.
        Supports:
        - mode="due": Target due cards divided into sessions.
        - mode="new": Target new cards divided into sessions.
        - mode="all": Both due & new cards configured.
            - mix_style="mixed": Each session gets a balanced split of Due + New.
            - mix_style="separate": Separate dedicated New sessions and Due sessions.
        """
        if mode == "due" and target_due > 0:
            total = target_due
        elif mode == "new" and target_new > 0:
            total = target_new
        elif mode == "all" and (target_due > 0 or target_new > 0):
            total = max(1, target_due + target_new)
        else:
            total = max(1, int(total_target))

        num_parts = (
            max(1, int(parts))
            if parts is not None and int(parts) > 0
            else max(1, (total + max(5, int(chunk_size)) - 1) // max(5, int(chunk_size)))
        )

        # Mode "all" with both due and new specified:
        if mode == "all" and (target_due > 0 or target_new > 0):
            if mix_style == "separate" and target_due > 0 and target_new > 0 and num_parts >= 2:
                # Distribute parts proportionately between new and due
                new_parts = max(1, round(num_parts * (target_new / total)))
                new_parts = min(num_parts - 1, new_parts)
                due_parts = num_parts - new_parts

                tiles = []
                # 1. New tiles first
                base_n = target_new // new_parts
                rem_n = target_new % new_parts
                for i in range(new_parts):
                    c = base_n + (rem_n if i == new_parts - 1 else 0)
                    if c > 0:
                        tiles.append(
                            FlowTile(
                                deck_id=deck_id,
                                deck_name=deck_name,
                                deck_path=deck_path or deck_name,
                                target_cards=c,
                                mode="new",
                                target_due=0,
                                target_new=c,
                            )
                        )
                # 2. Due tiles
                base_d = target_due // due_parts
                rem_d = target_due % due_parts
                for i in range(due_parts):
                    c = base_d + (rem_d if i == due_parts - 1 else 0)
                    if c > 0:
                        tiles.append(
                            FlowTile(
                                deck_id=deck_id,
                                deck_name=deck_name,
                                deck_path=deck_path or deck_name,
                                target_cards=c,
                                mode="due",
                                target_due=c,
                                target_new=0,
                            )
                        )
                return tiles
            else:
                # Mixed style (or single session part)
                tiles = []
                base_d = target_due // num_parts
                rem_d = target_due % num_parts
                base_n = target_new // num_parts
                rem_n = target_new % num_parts

                for i in range(num_parts):
                    d_c = base_d + (rem_d if i == num_parts - 1 else 0)
                    n_c = base_n + (rem_n if i == num_parts - 1 else 0)
                    tot_c = d_c + n_c
                    if tot_c > 0:
                        tiles.append(
                            FlowTile(
                                deck_id=deck_id,
                                deck_name=deck_name,
                                deck_path=deck_path or deck_name,
                                target_cards=tot_c,
                                mode="all",
                                target_due=d_c,
                                target_new=n_c,
                            )
                        )
                return tiles

        # If parts was not explicitly provided, split by chunk_size
        if parts is None or int(parts) <= 0:
            chunk = max(5, int(chunk_size))
            tiles = []
            remaining = total
            while remaining > 0:
                current_chunk = min(remaining, chunk)
                t_due = current_chunk if mode == "due" else 0
                t_new = current_chunk if mode == "new" else 0
                tiles.append(
                    FlowTile(
                        deck_id=deck_id,
                        deck_name=deck_name,
                        deck_path=deck_path or deck_name,
                        target_cards=current_chunk,
                        mode=mode,
                        completed_cards=0,
                        status="pending",
                        target_due=t_due,
                        target_new=t_new,
                    )
                )
                remaining -= current_chunk
            return tiles

        # Standard single mode generation divided into parts
        actual_parts = min(total, num_parts)
        base_chunk = total // actual_parts
        remainder = total % actual_parts
        tiles = []
        for i in range(actual_parts):
            chunk = base_chunk + (remainder if i == actual_parts - 1 else 0)
            if chunk > 0:
                t_due = chunk if mode == "due" else 0
                t_new = chunk if mode == "new" else 0
                tiles.append(
                    FlowTile(
                        deck_id=deck_id,
                        deck_name=deck_name,
                        deck_path=deck_path or deck_name,
                        target_cards=chunk,
                        mode=mode,
                        completed_cards=0,
                        status="pending",
                        target_due=t_due,
                        target_new=t_new,
                    )
                )
        return tiles

    @staticmethod
    def get_or_create_today_plan() -> DailyStudyPlan:
        """Fetch today's active study plan or initialize a fresh one."""
        app_data = store.get()
        today_str = date.today().isoformat()
        raw_plan = app_data.get("study_flow_daily")

        if isinstance(raw_plan, dict) and raw_plan.get("date") == today_str:
            return DailyStudyPlan.from_dict(raw_plan)

        # Archive old plan to history if needed
        if isinstance(raw_plan, dict) and raw_plan.get("date") != today_str:
            history = app_data.setdefault("study_flow_history", [])
            history.append(raw_plan)
            # Keep history within reasonable bounds
            if len(history) > 60:
                app_data["study_flow_history"] = history[-60:]

        fresh_plan = DailyStudyPlan(plan_date=today_str)
        StudyFlowService.save_today_plan(fresh_plan)
        return fresh_plan

    @staticmethod
    def save_today_plan(plan: DailyStudyPlan) -> None:
        """Persist today's plan to SQLite settings."""
        app_data = store.get()
        app_data["study_flow_daily"] = plan.to_dict()
        store.mark_dirty()

    @staticmethod
    def add_tiles_to_today_plan(new_tiles: List[FlowTile]) -> DailyStudyPlan:
        """Append generated tiles to today's playlist."""
        plan = StudyFlowService.get_or_create_today_plan()
        plan.tiles.extend(new_tiles)
        StudyFlowService.save_today_plan(plan)
        return plan

    @staticmethod
    def remove_tile(tile_id: str) -> DailyStudyPlan:
        """Remove a tile from today's plan."""
        plan = StudyFlowService.get_or_create_today_plan()
        plan.tiles = [t for t in plan.tiles if t.id != tile_id]
        if plan.current_tile_idx >= len(plan.tiles):
            plan.current_tile_idx = max(0, len(plan.tiles) - 1)
        StudyFlowService.save_today_plan(plan)
        return plan

    @staticmethod
    def reorder_tiles(from_idx: int, to_idx: int) -> DailyStudyPlan:
        """Reorder tiles in today's playlist."""
        plan = StudyFlowService.get_or_create_today_plan()
        if 0 <= from_idx < len(plan.tiles) and 0 <= to_idx < len(plan.tiles):
            tile = plan.tiles.pop(from_idx)
            plan.tiles.insert(to_idx, tile)
            StudyFlowService.save_today_plan(plan)
        return plan

    @staticmethod
    def clear_today_plan() -> DailyStudyPlan:
        """Reset today's study plan."""
        fresh = DailyStudyPlan(plan_date=date.today().isoformat())
        StudyFlowService.save_today_plan(fresh)
        return fresh

    @staticmethod
    def reformat_plan_flow(
        plan: DailyStudyPlan,
        mode: str = "mixed",
        interleave: bool = True,
    ) -> DailyStudyPlan:
        """
        Reformat active (uncompleted) tiles in today's playlist according to flow strategy:
        - mode="due_first": Expands mixed tiles into Due chunk and New chunk.
          If interleave=True: Interleaves Due chunks across all subjects (Round-Robin),
          followed by New chunks interleaved across all subjects.
          If interleave=False: Keeps subjects in blocks (Subject 1 Due+New, Subject 2 Due+New...).
        - mode="new_first": Expands mixed tiles into New chunk and Due chunk.
          If interleave=True: Interleaves New chunks across all subjects, then Due chunks.
          If interleave=False: Keeps subjects in blocks with New chunks first.
        - mode="mixed": Merges separate Due and New chunks for the same deck back into
          balanced mixed chunks (mode="all"). If interleave=True, interleaves these mixed
          chunks across subjects in round-robin sequence.
        Completed tiles are preserved untouched at the head of the playlist.
        """
        completed = [t for t in plan.tiles if t.status == "completed"]
        active = [t for t in plan.tiles if t.status != "completed"]

        if not active:
            return plan

        def _get_root_subject(tile: FlowTile) -> str:
            raw = tile.deck_path or tile.deck_name or "General"
            return raw.split("/")[0].strip() or "General"

        if mode in ("due_first", "new_first"):
            expanded = []
            for t in active:
                if t.target_due > 0 and t.target_new > 0:
                    t_due = FlowTile(
                        deck_id=t.deck_id,
                        deck_name=t.deck_name,
                        deck_path=t.deck_path,
                        target_cards=t.target_due,
                        mode="due",
                        target_due=t.target_due,
                        target_new=0,
                        created_at=t.created_at,
                    )
                    t_new = FlowTile(
                        deck_id=t.deck_id,
                        deck_name=t.deck_name,
                        deck_path=t.deck_path,
                        target_cards=t.target_new,
                        mode="new",
                        target_due=0,
                        target_new=t.target_new,
                        created_at=t.created_at,
                    )
                    expanded.extend([t_due, t_new])
                else:
                    expanded.append(t)
        else:  # mode == "mixed"
            deck_order = []
            deck_due: Dict[Any, List[FlowTile]] = {}
            deck_new: Dict[Any, List[FlowTile]] = {}
            deck_already_mixed: Dict[Any, List[FlowTile]] = {}
            deck_other: Dict[Any, List[FlowTile]] = {}

            for t in active:
                key = (t.deck_id, t.deck_path)
                if key not in deck_order:
                    deck_order.append(key)
                if t.target_due > 0 and t.target_new > 0:
                    deck_already_mixed.setdefault(key, []).append(t)
                elif t.mode == "due" or (t.target_due > 0 and t.target_new == 0):
                    deck_due.setdefault(key, []).append(t)
                elif t.mode == "new" or (t.target_new > 0 and t.target_due == 0):
                    deck_new.setdefault(key, []).append(t)
                else:
                    deck_other.setdefault(key, []).append(t)

            merged_active = []
            for key in deck_order:
                for m in deck_already_mixed.get(key, []):
                    merged_active.append(m)

                dues = list(deck_due.get(key, []))
                news = list(deck_new.get(key, []))

                while dues and news:
                    d_t = dues.pop(0)
                    n_t = news.pop(0)
                    tot = d_t.target_cards + n_t.target_cards
                    d_cnt = d_t.target_due or d_t.target_cards
                    n_cnt = n_t.target_new or n_t.target_cards
                    merged_tile = FlowTile(
                        deck_id=d_t.deck_id,
                        deck_name=d_t.deck_name,
                        deck_path=d_t.deck_path,
                        target_cards=tot,
                        mode="all",
                        target_due=d_cnt,
                        target_new=n_cnt,
                        created_at=min(d_t.created_at, n_t.created_at),
                    )
                    merged_active.append(merged_tile)

                for d_rem in dues:
                    merged_active.append(d_rem)
                for n_rem in news:
                    merged_active.append(n_rem)
                for o_rem in deck_other.get(key, []):
                    merged_active.append(o_rem)

            expanded = merged_active

        # Extract unique root subjects in original order
        subjects_order = []
        for t in expanded:
            s = _get_root_subject(t)
            if s not in subjects_order:
                subjects_order.append(s)

        if interleave:
            if mode in ("due_first", "new_first"):
                subj_due = {s: [] for s in subjects_order}
                subj_new = {s: [] for s in subjects_order}
                subj_other = {s: [] for s in subjects_order}
                for t in expanded:
                    s = _get_root_subject(t)
                    if t.mode == "due" or (t.target_due > 0 and t.target_new == 0):
                        subj_due[s].append(t)
                    elif t.mode == "new" or (t.target_new > 0 and t.target_due == 0):
                        subj_new[s].append(t)
                    else:
                        subj_other[s].append(t)

                # Primary queue carries priority card type + any practice/other tiles for that subject
                # so subjects with practice tiles (e.g. Math) are not stranded at the end!
                if mode == "due_first":
                    primary_tiles = {s: (subj_due[s] + subj_other[s]) for s in subjects_order}
                    secondary_tiles = {s: subj_new[s] for s in subjects_order}
                else:  # "new_first"
                    primary_tiles = {s: (subj_new[s] + subj_other[s]) for s in subjects_order}
                    secondary_tiles = {s: subj_due[s] for s in subjects_order}

                primary_rr = []
                max_p = max((len(primary_tiles[s]) for s in subjects_order), default=0)
                for i in range(max_p):
                    for s in subjects_order:
                        if i < len(primary_tiles[s]):
                            primary_rr.append(primary_tiles[s][i])

                secondary_rr = []
                max_s = max((len(secondary_tiles[s]) for s in subjects_order), default=0)
                for i in range(max_s):
                    for s in subjects_order:
                        if i < len(secondary_tiles[s]):
                            secondary_rr.append(secondary_tiles[s][i])

                reordered = primary_rr + secondary_rr
            else:  # mode == "mixed"
                subj_tiles = {s: [] for s in subjects_order}
                for t in expanded:
                    s = _get_root_subject(t)
                    subj_tiles[s].append(t)

                mixed_rr = []
                max_m = max((len(subj_tiles[s]) for s in subjects_order), default=0)
                for i in range(max_m):
                    for s in subjects_order:
                        if i < len(subj_tiles[s]):
                            mixed_rr.append(subj_tiles[s][i])
                reordered = mixed_rr
        else:
            # Grouped by subject blocks
            reordered = []
            for s in subjects_order:
                d_list = [t for t in expanded if _get_root_subject(t) == s and (t.mode == "due" or (t.target_due > 0 and t.target_new == 0))]
                n_list = [t for t in expanded if _get_root_subject(t) == s and (t.mode == "new" or (t.target_new > 0 and t.target_due == 0))]
                o_list = [t for t in expanded if _get_root_subject(t) == s and t not in d_list and t not in n_list]
                if mode == "due_first":
                    reordered.extend(d_list + o_list + n_list)
                elif mode == "new_first":
                    reordered.extend(n_list + o_list + d_list)
                else:
                    reordered.extend([t for t in expanded if _get_root_subject(t) == s])

        plan.tiles = completed + reordered
        if plan.current_tile_idx >= len(plan.tiles):
            plan.current_tile_idx = max(0, len(plan.tiles) - 1)

        StudyFlowService.save_today_plan(plan)
        return plan

    @staticmethod
    def interleave_plan_tiles(plan: DailyStudyPlan) -> DailyStudyPlan:
        """Convenience wrapper: reformat plan to mixed flow with interleave enabled."""
        return StudyFlowService.reformat_plan_flow(plan, mode="mixed", interleave=True)

    @staticmethod
    def find_deck_by_id(decks: List[Dict[str, Any]], deck_id: Any) -> Optional[Dict[str, Any]]:
        """Recursively locate a deck by its _id or id."""
        for d in decks or []:
            if not isinstance(d, dict):
                continue
            did = d.get("_id") or d.get("id")
            if str(did) == str(deck_id):
                return d
            children = d.get("children", []) or d.get("subdecks", [])
            found = StudyFlowService.find_deck_by_id(children, deck_id)
            if found:
                return found
        return None

    @staticmethod
    def collect_all_deck_cards(deck: Dict[str, Any], recursive: bool = True) -> List[Dict[str, Any]]:
        """Collect cards from a deck and optionally all its descendant subdecks."""
        cards = list(deck.get("cards", []) or [])
        if recursive:
            for child in deck.get("children", []) or deck.get("subdecks", []) or []:
                if isinstance(child, dict):
                    cards.extend(StudyFlowService.collect_all_deck_cards(child, recursive=True))
        return cards

    @staticmethod
    def get_cards_for_tile(
        tile: FlowTile,
        data: Optional[Dict[str, Any]] = None,
        excluded_card_ids: Optional[Set[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Dynamically gather up to `tile.target_cards` cards for this tile,
        skipping any cards in `excluded_card_ids` to guarantee zero cross-tile duplicate reviews today.
        """
        if data is None:
            data = store.get()
        if excluded_card_ids is None:
            excluded_card_ids = set()

        decks = data.get("decks", [])
        deck = StudyFlowService.find_deck_by_id(decks, tile.deck_id)
        if not deck:
            return []

        all_cards = StudyFlowService.collect_all_deck_cards(deck, recursive=True)
        valid_cards = []

        if tile.mode == "all" and (tile.target_due > 0 or tile.target_new > 0):
            due_candidates = []
            new_candidates = []
            other_candidates = []
            for c in all_cards:
                if not isinstance(c, dict):
                    continue
                cid = c.get("_id") or c.get("id")
                if cid in excluded_card_ids:
                    continue
                if c.get("is_formula", False) or c.get("is_paused", False) or c.get("suspended", False):
                    continue

                if card_has_due_today(c, exclude_new=True):
                    due_candidates.append(c)
                elif count_new_units_in_card(c) > 0:
                    new_candidates.append(c)
                else:
                    other_candidates.append(c)

            req_due = tile.target_due if tile.target_due > 0 else (tile.target_cards // 2)
            req_new = tile.target_new if tile.target_new > 0 else (tile.target_cards - req_due)

            picked_due = due_candidates[:req_due]
            picked_new = new_candidates[:req_new]

            # Interleave them for balanced study: 1 due, 1 new, 1 due, 1 new...
            selected = []
            d_i, n_i = 0, 0
            while d_i < len(picked_due) or n_i < len(picked_new):
                if d_i < len(picked_due):
                    selected.append(picked_due[d_i])
                    d_i += 1
                if n_i < len(picked_new):
                    selected.append(picked_new[n_i])
                    n_i += 1

            # Fill up to target_cards if either candidate list ran short
            if len(selected) < tile.target_cards:
                sel_ids = {c.get("_id") or c.get("id") for c in selected}
                extras = [
                    c for c in (due_candidates + new_candidates + other_candidates)
                    if (c.get("_id") or c.get("id")) not in sel_ids
                ]
                selected.extend(extras[: tile.target_cards - len(selected)])

            for c in selected:
                cid = c.get("_id") or c.get("id")
                if cid is not None:
                    excluded_card_ids.add(cid)
            return selected

        for c in all_cards:
            if not isinstance(c, dict):
                continue
            cid = c.get("_id") or c.get("id")
            if cid in excluded_card_ids:
                continue
            if c.get("is_formula", False) or c.get("is_paused", False) or c.get("suspended", False):
                continue

            if tile.mode == "new":
                if count_new_units_in_card(c) > 0:
                    valid_cards.append(c)
            elif tile.mode == "all":
                valid_cards.append(c)
            else:  # "due" (default)
                if card_has_due_today(c, exclude_new=False):
                    valid_cards.append(c)

        # If not enough cards in due mode, we gracefully provide all valid due cards found
        selected = valid_cards[: tile.target_cards]

        # Record selected IDs in exclusion set
        for c in selected:
            cid = c.get("_id") or c.get("id")
            if cid is not None:
                excluded_card_ids.add(cid)

        return selected

    @staticmethod
    def advance_tile_progress(
        tile_id: str,
        reviewed_count: int,
    ) -> Tuple[bool, Optional[FlowTile], Optional[FlowTile]]:
        """
        Mark a tile completed and advance current_tile_idx.
        Returns: (is_plan_all_completed, completed_tile, next_tile)
        """
        plan = StudyFlowService.get_or_create_today_plan()
        completed_tile = None

        for idx, t in enumerate(plan.tiles):
            if t.id == tile_id:
                t.completed_cards = max(t.completed_cards, reviewed_count)
                t.status = "completed"
                completed_tile = t
                if plan.current_tile_idx <= idx:
                    plan.current_tile_idx = idx + 1
                break

        is_all_done = plan.is_all_completed
        next_tile = plan.get_current_tile()
        StudyFlowService.save_today_plan(plan)
        return is_all_done, completed_tile, next_tile

    @staticmethod
    def save_routine_preset(name: str, tiles: List[FlowTile]) -> bool:
        """Save a list of tile configurations as a reusable daily routine preset."""
        clean_name = name.strip()
        if not clean_name or not tiles:
            return False
        app_data = store.get()
        routines = app_data.setdefault("study_flow_routines", {})
        routines[clean_name] = [
            {
                "deck_id": t.deck_id,
                "deck_name": t.deck_name,
                "deck_path": t.deck_path,
                "target_cards": t.target_cards,
                "mode": t.mode,
            }
            for t in tiles
        ]
        store.mark_dirty()
        return True

    @staticmethod
    def load_routine_presets() -> Dict[str, List[Dict[str, Any]]]:
        """Return all saved routine templates."""
        return store.get().get("study_flow_routines", {})

    @staticmethod
    def delete_routine_preset(name: str) -> bool:
        """Delete a saved routine template."""
        app_data = store.get()
        routines = app_data.get("study_flow_routines", {})
        if name in routines:
            del routines[name]
            store.mark_dirty()
            return True
        return False

    @staticmethod
    def apply_routine_preset(name: str) -> Optional[DailyStudyPlan]:
        """Generate a fresh today's plan from a saved routine template."""
        routines = StudyFlowService.load_routine_presets()
        template = routines.get(name)
        if not template:
            return None

        fresh_tiles = [
            FlowTile(
                deck_id=item.get("deck_id"),
                deck_name=item.get("deck_name", ""),
                deck_path=item.get("deck_path", ""),
                target_cards=item.get("target_cards", 25),
                mode=item.get("mode", "due"),
            )
            for item in template
        ]

        plan = DailyStudyPlan(plan_date=date.today().isoformat(), tiles=fresh_tiles)
        StudyFlowService.save_today_plan(plan)
        return plan
