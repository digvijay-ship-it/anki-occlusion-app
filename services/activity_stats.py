# -*- coding: utf-8 -*-
"""
services/activity_stats.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Calculates daily study activity, ratings breakdown, retention rates,
and hierarchical deck tree structures with aggregated counts and focus durations.
"""

import os
import json
from datetime import date
from typing import Dict, Any, List, Optional


def format_activity_duration(secs: int) -> str:
    """
    Formats seconds into a clean human-readable duration string.
    Examples: 3665s -> '1h 01m', 120s -> '2m', 45s -> '45s', 0s -> '0s'.
    """
    if not secs or secs <= 0:
        return "0s"
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m" if m > 0 else f"{h}h"
    if m > 0:
        return f"{m}m" if s == 0 else f"{m}m {s}s" if m < 5 else f"{m}m"
    return f"{s}s"


def _get_daily_mask_seconds(date_str: str) -> Dict[str, int]:
    """
    Retrieves mask/card level seconds for the given date.
    Checks in-memory session timer, storage_paths timer state, and default timer state.
    """
    mask_secs = {}

    # 1. From running session timer if date is today
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app and (date_str == date.today().isoformat()):
            seen = set()
            for widget in app.allWidgets():
                st = getattr(widget, "_stimer", None)
                if st is not None and id(st) not in seen:
                    seen.add(id(st))
                    if hasattr(st, "_mask_seconds") and isinstance(st._mask_seconds, dict):
                        for k, v in st._mask_seconds.items():
                            if isinstance(v, (int, float)) and v > 0:
                                mask_secs[str(k)] = max(mask_secs.get(str(k), 0), int(v))
    except Exception:
        pass

    # 2. From timer state files (archive root and default)
    state_files = []
    try:
        import storage_paths
        if hasattr(storage_paths, "current_timer_state_file"):
            state_files.append(storage_paths.current_timer_state_file())
    except Exception:
        pass
    try:
        import session_timer
        sf = getattr(session_timer, "_STATE_FILE", None)
        if sf and sf not in state_files:
            state_files.append(sf)
    except Exception:
        pass
    default_sf = os.path.join(os.path.expanduser("~"), "anki_timer_state.json")
    if default_sf not in state_files:
        state_files.append(default_sf)

    for sf in state_files:
        try:
            if sf and os.path.exists(sf):
                with open(sf, "r", encoding="utf-8") as f:
                    timer_data = json.load(f)
                if timer_data.get("date") == date_str and isinstance(timer_data.get("mask_seconds"), dict):
                    for k, v in timer_data["mask_seconds"].items():
                        if isinstance(v, (int, float)) and v > 0:
                            mask_secs[str(k)] = max(mask_secs.get(str(k), 0), int(v))
        except Exception:
            pass

    return mask_secs


def get_daily_deck_seconds(date_str: str) -> Dict[str, int]:
    """
    Retrieves recorded focus seconds per deck for a given date.
    Checks in-memory session_timer, timer state file, and journal storage.
    """
    deck_secs = {}

    # 1. From Journal file
    try:
        from services.journal_manager import _load_journal
        j_data = _load_journal()
        entry = j_data.get(date_str, {})
        if isinstance(entry, dict) and isinstance(entry.get("deck_seconds"), dict):
            for k, v in entry["deck_seconds"].items():
                if isinstance(v, (int, float)) and v > 0:
                    deck_secs[str(k)] = int(v)
    except Exception:
        pass

    # 2. From timer state files
    state_files = []
    try:
        import storage_paths
        if hasattr(storage_paths, "current_timer_state_file"):
            state_files.append(storage_paths.current_timer_state_file())
    except Exception:
        pass
    try:
        import session_timer
        sf = getattr(session_timer, "_STATE_FILE", None)
        if sf and sf not in state_files:
            state_files.append(sf)
    except Exception:
        pass
    default_sf = os.path.join(os.path.expanduser("~"), "anki_timer_state.json")
    if default_sf not in state_files:
        state_files.append(default_sf)

    for sf in state_files:
        try:
            if sf and os.path.exists(sf):
                with open(sf, "r", encoding="utf-8") as f:
                    timer_data = json.load(f)
                if timer_data.get("date") == date_str and isinstance(timer_data.get("deck_seconds"), dict):
                    for k, v in timer_data["deck_seconds"].items():
                        if isinstance(v, (int, float)) and v > 0:
                            deck_secs[str(k)] = max(deck_secs.get(str(k), 0), int(v))
        except Exception:
            pass

    # 3. From running session timer if date matches today
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app and (date_str == date.today().isoformat()):
            seen = set()
            for widget in app.allWidgets():
                st = getattr(widget, "_stimer", None)
                if st is not None and id(st) not in seen:
                    seen.add(id(st))
                    if hasattr(st, "_deck_seconds") and isinstance(st._deck_seconds, dict):
                        for k, v in st._deck_seconds.items():
                            if isinstance(v, (int, float)) and v > 0:
                                deck_secs[str(k)] = max(deck_secs.get(str(k), 0), int(v))
    except Exception:
        pass

    return deck_secs


def get_daily_activity_stats(date_str: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Computes review activity for a given date (YYYY-MM-DD).
    Returns total reviews, rating counts, retention percentage,
    a hierarchical deck tree with aggregated review numbers and time spent, and a flat deck map.
    """
    if data is None:
        try:
            from data_manager import store
            data = store.get()
        except Exception:
            data = {}

    total = 0
    ratings = {
        "again": 0,
        "hard": 0,
        "good": 0,
        "easy": 0,
        "perfect": 0,
    }
    deck_flat = {}
    deck_self_counts = {}

    # Pass 1: Count total reviews and reviews per deck
    def _count_reviews(deck: Dict[str, Any], parent_path: str):
        nonlocal total
        name = deck.get("name", "Unnamed Deck")
        full_path = f"{parent_path} / {name}" if parent_path else name
        self_count = 0

        for card in deck.get("cards", []) or []:
            if not isinstance(card, dict):
                continue
            rat = card.get("reviewed_at")
            if rat and str(rat).startswith(date_str):
                total += 1
                self_count += 1
                q = card.get("last_quality", -1)
                if q == 1:
                    ratings["again"] += 1
                elif q == 3:
                    ratings["hard"] += 1
                elif q == 4:
                    ratings["good"] += 1
                elif q == 5:
                    ratings["easy"] += 1
                elif q == 6:
                    ratings["perfect"] += 1

            seen_box_groups = set()
            for box in card.get("boxes", []) or []:
                if not isinstance(box, dict):
                    continue
                brat = box.get("reviewed_at")
                if brat and str(brat).startswith(date_str):
                    gid = box.get("group_id", "")
                    if gid:
                        if gid in seen_box_groups:
                            continue
                        seen_box_groups.add(gid)
                    total += 1
                    self_count += 1
                    q = box.get("last_quality", -1)
                    if q == 1:
                        ratings["again"] += 1
                    elif q == 3:
                        ratings["hard"] += 1
                    elif q == 4:
                        ratings["good"] += 1
                    elif q == 5:
                        ratings["easy"] += 1
                    elif q == 6:
                        ratings["perfect"] += 1

        deck_self_counts[full_path] = self_count
        if self_count > 0:
            deck_flat[full_path] = self_count

        for child in deck.get("children", []) or deck.get("subdecks", []) or []:
            if isinstance(child, dict):
                _count_reviews(child, full_path)

    for top_deck in data.get("decks", []) or []:
        if isinstance(top_deck, dict):
            _count_reviews(top_deck, "")

    focus_secs = get_daily_focus_seconds(date_str)
    mask_seconds = _get_daily_mask_seconds(date_str)
    total_mask_secs = sum(mask_seconds.values())
    has_mask_data = total_mask_secs > 0

    def _get_deck_direct_mask_seconds(deck: Dict[str, Any]) -> int:
        if not has_mask_data:
            return 0
        s = 0
        for card in deck.get("cards", []) or []:
            if not isinstance(card, dict):
                continue
            cid = str(card.get("_id") or card.get("id") or "")
            s += mask_seconds.get(f"{cid}_card", 0)
            s += mask_seconds.get(cid, 0)
            seen_grps = set()
            for box in card.get("boxes", []) or []:
                if not isinstance(box, dict):
                    continue
                bid = box.get("box_id") or ""
                if bid:
                    s += mask_seconds.get(f"{cid}_{bid}", 0)
                gid = box.get("group_id") or ""
                if gid and gid not in seen_grps:
                    seen_grps.add(gid)
                    s += mask_seconds.get(f"{cid}_grp_{gid}", 0)
        return s

    # Fallback to explicit deck seconds if no mask seconds
    recorded_deck_seconds = get_daily_deck_seconds(date_str)
    unallocated_focus = max(0, focus_secs - sum(recorded_deck_seconds.values()))
    unrecorded_reviews_sum = sum(
        count for path, count in deck_self_counts.items()
        if count > 0 and not (recorded_deck_seconds.get(path.split(" / ")[-1], 0) or recorded_deck_seconds.get(path, 0))
    )

    # Pass 2: Build tree structure with aggregated counts & seconds
    def _process_deck(deck: Dict[str, Any], parent_path: str) -> Dict[str, Any]:
        name = deck.get("name", "Unnamed Deck")
        full_path = f"{parent_path} / {name}" if parent_path else name
        self_total = deck_self_counts.get(full_path, 0)

        # Rating breakdown for this deck's direct cards
        self_ratings = {"again": 0, "hard": 0, "good": 0, "easy": 0, "perfect": 0}
        for card in deck.get("cards", []) or []:
            if not isinstance(card, dict):
                continue
            rat = card.get("reviewed_at")
            if rat and str(rat).startswith(date_str):
                q = card.get("last_quality", -1)
                if q == 1: self_ratings["again"] += 1
                elif q == 3: self_ratings["hard"] += 1
                elif q == 4: self_ratings["good"] += 1
                elif q == 5: self_ratings["easy"] += 1
                elif q == 6: self_ratings["perfect"] += 1

            seen_box_groups = set()
            for box in card.get("boxes", []) or []:
                if not isinstance(box, dict):
                    continue
                brat = box.get("reviewed_at")
                if brat and str(brat).startswith(date_str):
                    gid = box.get("group_id", "")
                    if gid:
                        if gid in seen_box_groups:
                            continue
                        seen_box_groups.add(gid)
                    q = box.get("last_quality", -1)
                    if q == 1: self_ratings["again"] += 1
                    elif q == 3: self_ratings["hard"] += 1
                    elif q == 4: self_ratings["good"] += 1
                    elif q == 5: self_ratings["easy"] += 1
                    elif q == 6: self_ratings["perfect"] += 1

        # Calculate self_secs directly from exact mask/card time, or fallback
        if has_mask_data:
            self_secs = _get_deck_direct_mask_seconds(deck)
            if self_secs == 0 and self_total > 0 and focus_secs > total_mask_secs:
                untracked = focus_secs - total_mask_secs
                self_secs = round(untracked * (self_total / total)) if total > 0 else 0
        elif recorded_deck_seconds:
            dname = name
            rec = recorded_deck_seconds.get(dname, 0) or recorded_deck_seconds.get(full_path, 0)
            if rec > 0:
                self_secs = rec
            elif unallocated_focus > 0 and unrecorded_reviews_sum > 0:
                self_secs = round(unallocated_focus * (self_total / unrecorded_reviews_sum))
            else:
                self_secs = 0
        else:
            self_secs = round(focus_secs * (self_total / total)) if (total > 0 and focus_secs > 0) else 0

        # Sub-decks / children
        children_nodes = []
        sub_reviews = 0
        sub_seconds = 0
        sub_ratings = {"again": 0, "hard": 0, "good": 0, "easy": 0, "perfect": 0}

        for child in deck.get("children", []) or deck.get("subdecks", []) or []:
            if isinstance(child, dict):
                child_node = _process_deck(child, full_path)
                if child_node["total_reviews"] > 0 or child_node.get("total_seconds", 0) > 0:
                    children_nodes.append(child_node)
                    sub_reviews += child_node["total_reviews"]
                    sub_seconds += child_node.get("total_seconds", 0)
                    for k in sub_ratings:
                        sub_ratings[k] += child_node["ratings"][k]

        combined_reviews = self_total + sub_reviews
        combined_seconds = self_secs + sub_seconds
        combined_ratings = {k: self_ratings[k] + sub_ratings[k] for k in self_ratings}

        return {
            "name": name,
            "full_path": full_path,
            "self_reviews": self_total,
            "total_reviews": combined_reviews,
            "self_seconds": self_secs,
            "total_seconds": combined_seconds,
            "time_str": format_activity_duration(combined_seconds),
            "ratings": combined_ratings,
            "children": children_nodes,
        }

    tree_nodes = []
    for top_deck in data.get("decks", []) or []:
        if isinstance(top_deck, dict):
            node = _process_deck(top_deck, "")
            if node["total_reviews"] > 0 or node.get("total_seconds", 0) > 0:
                tree_nodes.append(node)

    # Calculate overall retention
    correct = ratings["good"] + ratings["easy"] + ratings["perfect"]
    total_rated = (
        ratings["again"]
        + ratings["hard"]
        + ratings["good"]
        + ratings["easy"]
        + ratings["perfect"]
    )
    retention = round((correct / total_rated) * 100) if total_rated > 0 else 0

    return {
        "date": date_str,
        "total": total,
        "again": ratings["again"],
        "hard": ratings["hard"],
        "good": ratings["good"],
        "easy": ratings["easy"],
        "perfect": ratings["perfect"],
        "retention": retention,
        "focus_seconds": focus_secs,
        "focus_formatted": format_activity_duration(focus_secs),
        "tree": tree_nodes,
        "decks": deck_flat,
    }


def get_daily_focus_seconds(date_str: str) -> int:
    """
    Retrieves the total focus seconds recorded for the given date.
    Checks in-memory session_timer, timer state files, journal storage, and card mask timings.
    """
    focus_secs = 0

    # 1. From Journal files (archive root and default)
    journal_files = []
    try:
        import storage_paths
        if hasattr(storage_paths, "current_journal_file"):
            journal_files.append(storage_paths.current_journal_file())
    except Exception:
        pass
    try:
        import services.journal_manager as jm
        if hasattr(jm, "JOURNAL_FILE") and jm.JOURNAL_FILE not in journal_files:
            journal_files.append(jm.JOURNAL_FILE)
    except Exception:
        pass
    default_jf = os.path.join(os.path.expanduser("~"), "anki_journal.json")
    if default_jf not in journal_files:
        journal_files.append(default_jf)

    for jf in journal_files:
        try:
            if jf and os.path.exists(jf):
                with open(jf, "r", encoding="utf-8") as f:
                    j_data = json.load(f)
                entry = j_data.get(date_str, {})
                if isinstance(entry, dict):
                    focus_secs = max(focus_secs, int(entry.get("focus_seconds", 0)))
        except Exception:
            pass

    # 2. From running session timer if date matches today
    try:
        from PyQt5.QtWidgets import QApplication
        active_seconds = None
        app = QApplication.instance()
        if app and (date_str == date.today().isoformat()):
            seen = set()
            for widget in app.allWidgets():
                st = getattr(widget, "_stimer", None)
                if st is not None and id(st) not in seen:
                    seen.add(id(st))
                    if hasattr(st, "elapsed_seconds"):
                        active_seconds = st.elapsed_seconds
                        break
        if active_seconds is not None:
            focus_secs = max(focus_secs, active_seconds)
    except Exception:
        pass

    # 3. From timer state files (archive root and default)
    state_files = []
    try:
        import storage_paths
        if hasattr(storage_paths, "current_timer_state_file"):
            state_files.append(storage_paths.current_timer_state_file())
    except Exception:
        pass
    try:
        import session_timer
        sf = getattr(session_timer, "_STATE_FILE", None)
        if sf and sf not in state_files:
            state_files.append(sf)
    except Exception:
        pass
    default_sf = os.path.join(os.path.expanduser("~"), "anki_timer_state.json")
    if default_sf not in state_files:
        state_files.append(default_sf)

    for sf in state_files:
        try:
            if sf and os.path.exists(sf):
                with open(sf, "r", encoding="utf-8") as f:
                    timer_data = json.load(f)
                if timer_data.get("date") == date_str:
                    focus_secs = max(focus_secs, int(timer_data.get("seconds", 0)))
        except Exception:
            pass

    # 4. From card mask seconds if present
    try:
        mask_secs = _get_daily_mask_seconds(date_str)
        if mask_secs:
            focus_secs = max(focus_secs, sum(mask_secs.values()))
    except Exception:
        pass

    return focus_secs


def calculate_study_rank(total_cards: int, retention_pct: int) -> Dict[str, str]:
    """
    Returns a thematic Ninja/Master study rank badge based on cards studied and retention.
    """
    if total_cards == 0:
        return {"rank": "REST DAY", "title": "Meditation", "color": "#5F627D"}
    
    if retention_pct >= 90 and total_cards >= 50:
        return {"rank": "S-RANK", "title": "Hokage / Grandmaster", "color": "#72FF4F"}
    elif retention_pct >= 80 or (retention_pct >= 75 and total_cards >= 100):
        return {"rank": "A-RANK", "title": "Jonin / Master", "color": "#50FA7B"}
    elif retention_pct >= 70 or total_cards >= 30:
        return {"rank": "B-RANK", "title": "Chunin / Scholar", "color": "#F1FA8C"}
    elif retention_pct >= 50 or total_cards >= 10:
        return {"rank": "C-RANK", "title": "Genin / Apprentice", "color": "#FFB86C"}
    else:
        return {"rank": "D-RANK", "title": "Initiate", "color": "#FF5555"}

