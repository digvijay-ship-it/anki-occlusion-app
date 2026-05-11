import os
import shutil
import sys
import uuid
from pathlib import Path


APP_SETTINGS_ORG = "AnkiOcclusion"
APP_SETTINGS_APP = "App"
MISSION_ARCHIVE_KEY = "mission_archive_dir"
CACHE_DIR_KEY = "cache_dir"

DATA_DIR_NAME = "data"
PDF_DIR_NAME = "pdfs"
IMAGE_DIR_NAME = "images"
CACHE_DIR_NAME = "cache"
BACKUP_DIR_NAME = "backups"

DATA_FILE_NAME = "anki_occlusion_data.json"
TIMER_STATE_FILE_NAME = "anki_timer_state.json"
JOURNAL_FILE_NAME = "anki_journal.json"


def _settings():
    from PyQt5.QtCore import QSettings

    return QSettings(APP_SETTINGS_ORG, APP_SETTINGS_APP)


def _normalize_path(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


def _normalize_root(root: str) -> str:
    return _normalize_path(root.strip()) if root else ""


def _current_archive_root(root: str | None = None) -> str:
    if root is not None:
        return _normalize_root(root)
    return get_mission_archive_root()


def _home_file(name: str) -> str:
    return os.path.join(os.path.expanduser("~"), name)


def app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            return _normalize_path(meipass)
        return _normalize_path(os.path.dirname(sys.executable))
    return _normalize_path(os.path.dirname(os.path.abspath(__file__)))


def app_resource_path(*parts: str) -> str:
    clean_parts = [str(part).strip("\\/") for part in (parts or []) if str(part).strip("\\/")]
    if not clean_parts:
        return app_base_dir()
    return _normalize_path(os.path.join(app_base_dir(), *clean_parts))


def app_resource_url(*parts: str) -> str:
    return app_resource_path(*parts).replace("\\", "/")


def get_mission_archive_root() -> str:
    try:
        raw = _settings().value(MISSION_ARCHIVE_KEY, "", type=str)
    except TypeError:
        raw = _settings().value(MISSION_ARCHIVE_KEY, "")
    return _normalize_root(raw or "")


def set_mission_archive_root(root: str) -> str:
    root = _normalize_root(root)
    _settings().setValue(MISSION_ARCHIVE_KEY, root)
    print(f"[DEBUG][mission_archive] settings_saved root={root}")
    return root


def has_mission_archive() -> bool:
    return bool(get_mission_archive_root())


def archive_data_dir(root: str | None = None) -> str:
    root = _current_archive_root(root)
    return os.path.join(root, DATA_DIR_NAME) if root else ""


def archive_pdf_dir(root: str | None = None) -> str:
    root = _current_archive_root(root)
    return os.path.join(root, PDF_DIR_NAME) if root else ""


def archive_image_dir(root: str | None = None) -> str:
    root = _current_archive_root(root)
    return os.path.join(root, IMAGE_DIR_NAME) if root else ""


def archive_cache_dir(root: str | None = None) -> str:
    root = _current_archive_root(root)
    return os.path.join(root, CACHE_DIR_NAME) if root else ""


def archive_backup_dir(root: str | None = None) -> str:
    root = _current_archive_root(root)
    return os.path.join(root, BACKUP_DIR_NAME) if root else ""


def current_backup_dir(root: str | None = None) -> str:
    root = _current_archive_root(root)
    if root:
        return archive_backup_dir(root)
    return os.path.join(os.path.dirname(current_data_file(root)) or ".", "anki_occlusion_data.backups")


def current_data_file(root: str | None = None) -> str:
    root = _current_archive_root(root)
    if root:
        return os.path.join(archive_data_dir(root), DATA_FILE_NAME)
    return _home_file(DATA_FILE_NAME)


def current_timer_state_file(root: str | None = None) -> str:
    root = _current_archive_root(root)
    if root:
        return os.path.join(archive_data_dir(root), TIMER_STATE_FILE_NAME)
    return _home_file(TIMER_STATE_FILE_NAME)


def current_journal_file(root: str | None = None) -> str:
    root = _current_archive_root(root)
    if root:
        return os.path.join(archive_data_dir(root), JOURNAL_FILE_NAME)
    return _home_file(JOURNAL_FILE_NAME)


def current_cache_dir(root: str | None = None) -> str:
    root = _current_archive_root(root)
    if root:
        return archive_cache_dir(root)
    try:
        raw = _settings().value(CACHE_DIR_KEY, "", type=str)
    except TypeError:
        raw = _settings().value(CACHE_DIR_KEY, "")
    if raw:
        return _normalize_root(raw)
    return os.path.join(os.path.expanduser("~"), ".cache", "anki_occlusion")


def ensure_archive_dirs(root: str | None = None) -> dict:
    root = _current_archive_root(root)
    if not root:
        return {}
    paths = {
        "root": root,
        "data": archive_data_dir(root),
        "pdfs": archive_pdf_dir(root),
        "images": archive_image_dir(root),
        "cache": archive_cache_dir(root),
        "backups": archive_backup_dir(root),
    }
    for path in paths.values():
        os.makedirs(path, exist_ok=True)
    return paths


def archive_label() -> str:
    root = get_mission_archive_root()
    if root:
        return os.path.basename(root) or root
    return os.path.basename(current_data_file())


def archive_tooltip() -> str:
    root = get_mission_archive_root()
    if root:
        return root
    return current_data_file()


def is_relative_archive_path(path: str) -> bool:
    return bool(path) and not os.path.isabs(str(path))


def resolve_asset_path(path: str, archive_root: str | None = None) -> str:
    if not path:
        return ""
    raw = str(path).strip()
    if not raw:
        return ""
    if os.path.isabs(raw):
        return _normalize_path(raw)
    root = _current_archive_root(archive_root)
    if root:
        return _normalize_path(os.path.join(root, raw.replace("/", os.sep)))
    return _normalize_path(raw)


def is_within_directory(path: str, directory: str) -> bool:
    if not path or not directory:
        return False
    try:
        return os.path.commonpath([_normalize_path(path), _normalize_path(directory)]) == _normalize_path(directory)
    except ValueError:
        return False


def to_archive_relative(path: str, root: str | None = None) -> str:
    root = _current_archive_root(root)
    if not root or not path:
        return path
    abs_path = _normalize_path(path)
    if not is_within_directory(abs_path, root):
        return path
    return Path(os.path.relpath(abs_path, root)).as_posix()


def _sanitize_stem(stem: str, fallback: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (stem or ""))
    cleaned = cleaned.strip("._")
    return cleaned or fallback


def _sanitize_segment(segment: str, fallback: str = "deck") -> str:
    return _sanitize_stem(segment, fallback)


def sanitize_deck_segments(deck_segments) -> list[str]:
    result = []
    for idx, segment in enumerate(deck_segments or []):
        cleaned = _sanitize_segment(str(segment or "").strip(), f"deck_{idx + 1}")
        if cleaned:
            result.append(cleaned)
    return result


def find_deck_segments(data: dict, deck_id) -> list[str]:
    def _walk(decks, trail):
        for deck in decks or []:
            if not isinstance(deck, dict):
                continue
            name = str(deck.get("name", "")).strip() or f"deck_{deck.get('_id', 'x')}"
            current = trail + [name]
            if deck.get("_id") == deck_id:
                return current
            found = _walk(deck.get("children", []) or deck.get("subdecks", []) or [], current)
            if found:
                return found
        return None

    return _walk((data or {}).get("decks", []) or [], []) or []


def _archive_dir_for_kind(kind: str, root: str | None = None, deck_segments=None) -> str:
    root = _current_archive_root(root)
    if kind == "pdfs":
        base = archive_pdf_dir(root)
        parts = sanitize_deck_segments(deck_segments)
        return os.path.join(base, *parts) if parts else base
    if kind == "images":
        return archive_image_dir(root)
    raise ValueError(f"Unsupported archive kind: {kind}")


def build_archive_asset_path(kind: str, source_name: str, root: str | None = None, deck_segments=None) -> tuple[str, str]:
    root = _current_archive_root(root)
    if not root:
        raise RuntimeError("Mission archive is not configured.")
    ensure_archive_dirs(root)
    folder = _archive_dir_for_kind(kind, root, deck_segments=deck_segments)
    os.makedirs(folder, exist_ok=True)
    stem = _sanitize_stem(os.path.splitext(os.path.basename(source_name))[0], kind[:-1])
    ext = os.path.splitext(source_name)[1] or (".png" if kind == "images" else "")
    candidate = os.path.join(folder, f"{stem}{ext}")
    if os.path.exists(candidate):
        candidate = os.path.join(folder, f"{stem}_{uuid.uuid4().hex[:8]}{ext}")
    return candidate, to_archive_relative(candidate, root)


def import_asset_into_archive(
    source_path: str,
    kind: str,
    root: str | None = None,
    deck_segments=None,
    move_existing: bool = False,
) -> str:
    root = _current_archive_root(root)
    if not root:
        return _normalize_path(source_path)
    source_abs = resolve_asset_path(source_path)
    if not os.path.exists(source_abs):
        raise FileNotFoundError(source_abs)
    target_dir = _archive_dir_for_kind(kind, root, deck_segments=deck_segments)
    ensure_archive_dirs(root)
    if is_within_directory(source_abs, target_dir):
        return to_archive_relative(source_abs, root)
    dest_abs, dest_rel = build_archive_asset_path(
        kind,
        os.path.basename(source_abs),
        root,
        deck_segments=deck_segments,
    )
    if move_existing and is_within_directory(source_abs, root):
        os.makedirs(os.path.dirname(dest_abs) or ".", exist_ok=True)
        shutil.move(source_abs, dest_abs)
        print(
            "[DEBUG][mission_archive] asset_moved "
            f"kind={kind} source={source_abs} dest={dest_abs}"
        )
    else:
        shutil.copy2(source_abs, dest_abs)
        print(
            "[DEBUG][mission_archive] asset_copied "
            f"kind={kind} source={source_abs} dest={dest_abs}"
        )
    return dest_rel


def iter_cards(data: dict):
    def _walk(decks):
        for deck in decks or []:
            if not isinstance(deck, dict):
                continue
            for card in deck.get("cards", []) or []:
                if isinstance(card, dict):
                    yield card
            children = deck.get("children", []) or deck.get("subdecks", []) or []
            yield from _walk(children)

    if isinstance(data, dict):
        yield from _walk(data.get("decks", []) or [])


def iter_cards_with_deck_segments(data: dict):
    def _walk(decks, trail):
        for deck in decks or []:
            if not isinstance(deck, dict):
                continue
            name = str(deck.get("name", "")).strip() or f"deck_{deck.get('_id', 'x')}"
            current = trail + [name]
            for card in deck.get("cards", []) or []:
                if isinstance(card, dict):
                    yield card, current
            children = deck.get("children", []) or deck.get("subdecks", []) or []
            yield from _walk(children, current)

    if isinstance(data, dict):
        yield from _walk(data.get("decks", []) or [], [])


def relocate_pdf_for_deck(card: dict, deck_segments, root: str | None = None) -> str:
    stored_path = (card or {}).get("pdf_path", "")
    if not stored_path:
        return ""
    new_value = import_asset_into_archive(
        stored_path,
        "pdfs",
        root=root,
        deck_segments=deck_segments,
        move_existing=True,
    )
    card["pdf_path"] = new_value
    print(
        "[DEBUG][mission_archive] pdf_relocated_for_deck "
        f"deck={'/'.join(sanitize_deck_segments(deck_segments))} stored={new_value}"
    )
    return new_value


def flush_runtime_state():
    print("[DEBUG][mission_archive] flush_runtime_state start")
    try:
        import data_manager

        data_manager.store.save_force()
    except Exception as ex:
        print(f"[DEBUG][mission_archive] store_flush_failed error={ex}")
    try:
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        seen = set()
        for widget in app.allWidgets():
            timer = getattr(widget, "_stimer", None)
            if timer is None or id(timer) in seen or not hasattr(timer, "flush_to_journal"):
                continue
            seen.add(id(timer))
            was_running = bool(getattr(timer, "_running", False))
            print(f"[DEBUG][mission_archive] timer_flush running={was_running}")
            try:
                if was_running and hasattr(timer, "stop"):
                    timer.stop()
                timer.flush_to_journal()
                if was_running and hasattr(timer, "start"):
                    timer.start()
            except Exception as ex:
                print(f"[DEBUG][mission_archive] timer_flush_failed error={ex}")
    except Exception as ex:
        print(f"[DEBUG][mission_archive] widget_flush_failed error={ex}")


def _copy_file_if_present(source: str, target: str) -> bool:
    if not source or not os.path.exists(source):
        return False
    if _normalize_path(source) == _normalize_path(target):
        return False
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    shutil.copy2(source, target)
    return True


def _copy_dir_contents(source: str, target: str) -> int:
    if not source or not os.path.isdir(source):
        return 0
    if _normalize_path(source) == _normalize_path(target):
        return 0
    os.makedirs(target, exist_ok=True)
    copied = 0
    for name in os.listdir(source):
        src_path = os.path.join(source, name)
        dst_path = os.path.join(target, name)
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
        else:
            shutil.copy2(src_path, dst_path)
        copied += 1
    return copied


def apply_mission_archive(root: str | None = None) -> dict:
    root = _current_archive_root(root)
    if root:
        ensure_archive_dirs(root)
    import data_manager
    import session_timer

    data_manager.DATA_FILE = current_data_file(root)
    session_timer._STATE_FILE = current_timer_state_file(root)
    session_timer._JOURNAL_FILE = current_journal_file(root)

    try:
        from services import journal_manager

        journal_manager.JOURNAL_FILE = current_journal_file(root)
    except Exception as ex:
        print(f"[DEBUG][mission_archive] journal_module_apply_failed error={ex}")

    try:
        import cache_manager

        cache_manager.COMBINED_CACHE._dir = current_cache_dir(root)
        os.makedirs(cache_manager.COMBINED_CACHE._dir, exist_ok=True)
        cache_manager.COMBINED_CACHE._index.clear()
        cache_manager.COMBINED_CACHE._rebuild_index()
    except Exception as ex:
        print(f"[DEBUG][mission_archive] cache_apply_failed error={ex}")

    applied = {
        "root": root,
        "data_file": data_manager.DATA_FILE,
        "timer_file": session_timer._STATE_FILE,
        "journal_file": session_timer._JOURNAL_FILE,
        "cache_dir": current_cache_dir(root),
    }
    print(
        "[DEBUG][mission_archive] apply "
        f"root={applied['root'] or '<legacy>'} "
        f"data={applied['data_file']} "
        f"cache={applied['cache_dir']}"
    )
    return applied


def initialize_mission_archive() -> dict:
    return apply_mission_archive(get_mission_archive_root())


def migrate_to_mission_archive(new_root: str, data: dict | None = None) -> dict:
    new_root = _normalize_root(new_root)
    if not new_root:
        raise ValueError("Mission archive directory is required.")

    old_root = get_mission_archive_root()
    source_data_file = current_data_file(old_root)
    source_timer_file = current_timer_state_file(old_root)
    source_journal_file = current_journal_file(old_root)
    source_cache_dir = current_cache_dir(old_root)
    source_backup_dir = current_backup_dir(old_root)

    print(
        "[DEBUG][mission_archive] migrate_start "
        f"from_root={old_root or '<legacy>'} to_root={new_root}"
    )
    flush_runtime_state()
    ensure_archive_dirs(new_root)

    summary = {
        "cards_rewritten": 0,
        "pdfs_copied": 0,
        "images_copied": 0,
        "assets_skipped": 0,
        "state_files_copied": 0,
        "cache_entries_copied": 0,
        "backup_entries_copied": 0,
    }

    if isinstance(data, dict):
        for card, deck_segments in iter_cards_with_deck_segments(data):
            changed = False
            for field, kind in (("pdf_path", "pdfs"), ("image_path", "images")):
                stored_path = card.get(field, "")
                if not stored_path:
                    continue
                try:
                    target_segments = deck_segments if field == "pdf_path" else None
                    new_value = import_asset_into_archive(
                        stored_path,
                        kind,
                        root=new_root,
                        deck_segments=target_segments,
                    )
                    if new_value != stored_path:
                        card[field] = new_value
                        changed = True
                        summary["pdfs_copied" if field == "pdf_path" else "images_copied"] += 1
                        print(
                            "[DEBUG][mission_archive] asset_rewritten "
                            f"field={field} stored={stored_path} new={new_value}"
                        )
                except Exception as ex:
                    summary["assets_skipped"] += 1
                    print(
                        "[DEBUG][mission_archive] asset_copy_failed "
                        f"field={field} path={stored_path} error={ex}"
                    )
            if changed:
                summary["cards_rewritten"] += 1

    if not isinstance(data, dict):
        if _copy_file_if_present(source_data_file, current_data_file(new_root)):
            summary["state_files_copied"] += 1

    if _copy_file_if_present(source_timer_file, current_timer_state_file(new_root)):
        summary["state_files_copied"] += 1
    if _copy_file_if_present(source_journal_file, current_journal_file(new_root)):
        summary["state_files_copied"] += 1

    summary["backup_entries_copied"] = _copy_dir_contents(source_backup_dir, archive_backup_dir(new_root))
    summary["cache_entries_copied"] = _copy_dir_contents(source_cache_dir, archive_cache_dir(new_root))

    set_mission_archive_root(new_root)
    apply_mission_archive(new_root)

    if isinstance(data, dict):
        import data_manager

        data_manager.store.save_force()

    print(f"[DEBUG][mission_archive] migrate_done summary={summary}")
    return summary
