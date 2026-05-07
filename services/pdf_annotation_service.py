import json
import math
import os
import uuid
from collections import Counter

import fitz
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPixmap

from pdf_engine import (
    PAGE_CACHE,
    choose_pdf_render_zoom,
    ensure_pdf_cache_profile,
    pdf_page_to_pixmap,
    render_pdf_pages,
    update_page_hashes,
)


def _to_qpointf_list(points):
    out = []
    for pt in points or []:
        if isinstance(pt, QPointF):
            out.append(QPointF(pt))
        elif isinstance(pt, (tuple, list)) and len(pt) >= 2:
            out.append(QPointF(float(pt[0]), float(pt[1])))
    return out


def _to_point_pairs(points):
    out = []
    for pt in points or []:
        if isinstance(pt, QPointF):
            out.append([float(pt.x()), float(pt.y())])
        elif isinstance(pt, (tuple, list)) and len(pt) >= 2:
            try:
                out.append([float(pt[0]), float(pt[1])])
            except (TypeError, ValueError):
                continue
    return out


def _flatten_annot_vertices(vertices):
    out = []
    for item in vertices or []:
        if isinstance(item, QPointF):
            out.append(QPointF(item))
            continue
        if isinstance(item, (tuple, list)):
            if len(item) >= 2 and not isinstance(item[0], (tuple, list, QPointF)):
                try:
                    out.append(QPointF(float(item[0]), float(item[1])))
                except (TypeError, ValueError):
                    pass
                continue
            out.extend(_flatten_annot_vertices(item))
    return out


def _parse_saved_points(annot) -> list[QPointF]:
    try:
        info = annot.info or {}
        content = info.get("content") or ""
        if not content:
            return []
        payload = json.loads(content)
        if not isinstance(payload, dict):
            return []
        points = payload.get("points") or []
        return _to_qpointf_list(points)
    except Exception:
        return []


def _page_rect_tuple(rect):
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def _rect_contains_point(rect_tuple, point: QPointF, padding: float = 0.0) -> bool:
    rect = QRectF(
        rect_tuple[0] - padding,
        rect_tuple[1] - padding,
        (rect_tuple[2] - rect_tuple[0]) + padding * 2,
        (rect_tuple[3] - rect_tuple[1]) + padding * 2,
    )
    return rect.contains(point)


def _point_segment_distance(point: QPointF, a: QPointF, b: QPointF) -> float:
    px = point.x()
    py = point.y()
    ax = a.x()
    ay = a.y()
    bx = b.x()
    by = b.y()
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx = ax + t * dx
    cy = ay + t * dy
    return math.hypot(px - cx, py - cy)


def _safe_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class PdfAnnotationSession:
    TOOL_STYLES = {
        "pen": {"color": "#FF4444", "width": 2.8, "opacity": 1.0},
        "highlight": {"color": "#FFD54A", "width": 12.0, "opacity": 0.30},
    }

    def __init__(self, pdf_path: str):
        self.pdf_path = os.path.abspath(pdf_path)
        self.doc = fitz.open(self.pdf_path)
        if self.doc.is_encrypted:
            self.doc.close()
            raise RuntimeError("PDF is password protected.")

        self.page_count = len(self.doc)
        self.render_zoom = choose_pdf_render_zoom(self.page_count)
        self.render_label = "3x" if self.render_zoom >= 3.0 else "2x"
        self.cache_reset = ensure_pdf_cache_profile(self.pdf_path, self.render_zoom)
        self.dirty_pages = set()
        self.pending_deleted_xrefs = set()
        self.existing_annots = {}
        self.new_items = {}
        self._undo_stack = []
        self._redo_stack = []
        self._load_existing_annotations()

    def close(self):
        if getattr(self, "doc", None) is not None:
            self.doc.close()
            self.doc = None

    def _debug(self, action: str, **data):
        parts = " ".join(f"{key}={value}" for key, value in data.items())
        print(f"[DEBUG][pdf_annotation] {action} {parts}".rstrip())

    def _load_existing_annotations(self, page_nums=None):
        if page_nums is None:
            targets = range(self.page_count)
        else:
            targets = sorted({int(pn) for pn in page_nums if 0 <= int(pn) < self.page_count})

        for page_num in targets:
            page = self.doc.load_page(page_num)
            items = []
            annots = page.annots()
            if annots:
                for annot in annots:
                    item = self._build_existing_item(page_num, annot)
                    if item is not None:
                        items.append(item)
            self.existing_annots[page_num] = items
            if items:
                kind_counts = Counter(item.get("kind", "unknown") for item in items)
                with_points = sum(1 for item in items if item.get("points"))
                self._debug(
                    "page_scan",
                    page=page_num + 1,
                    total=len(items),
                    kinds=dict(sorted(kind_counts.items())),
                    with_points=with_points,
                )

    def _build_existing_item(self, page_num: int, annot):
        subtype = ""
        try:
            subtype = (annot.type[1] or "").lower()
        except Exception:
            subtype = "unknown"

        rect = _page_rect_tuple(annot.rect)
        width = 2.0
        try:
            border = annot.border or {}
            width = _safe_float(border.get("width", 2.0), 2.0)
        except Exception:
            width = 2.0

        vertices = []
        try:
            vertices = _flatten_annot_vertices(getattr(annot, "vertices", None))
        except Exception:
            vertices = []
        if not vertices:
            vertices = _parse_saved_points(annot)

        item = {
            "id": f"existing:{annot.xref}",
            "page": page_num,
            "source": "existing",
            "kind": subtype,
            "xref": int(annot.xref),
            "rect": rect,
            "points": vertices,
            "width": width,
        }
        return item

    def get_new_items_for_page(self, page_num: int):
        return [
            item for item in self.new_items.get(page_num, [])
            if not item.get("deleted", False)
        ]

    def add_new_item(self, page_num: int, tool: str, points):
        if tool not in self.TOOL_STYLES:
            return None
        pts = _to_qpointf_list(points)
        if len(pts) < 2:
            return None
        style = self.TOOL_STYLES[tool]
        item = {
            "id": f"new:{uuid.uuid4().hex}",
            "page": int(page_num),
            "source": "new",
            "kind": tool,
            "points": pts,
            "color": style["color"],
            "width": style["width"],
            "opacity": style["opacity"],
            "deleted": False,
        }
        self.new_items.setdefault(int(page_num), []).append(item)
        self.dirty_pages.add(int(page_num))
        self._undo_stack.append({"type": "add_new", "page": int(page_num), "item_id": item["id"]})
        self._redo_stack.clear()
        self._debug("add_new", page=page_num + 1, tool=tool, points=len(pts))
        return item

    def erase_at_point(self, page_num: int, point):
        page_num = int(page_num)
        point = point if isinstance(point, QPointF) else QPointF(point[0], point[1])
        self._debug(
            "erase_probe",
            page=page_num + 1,
            x=f"{point.x():.1f}",
            y=f"{point.y():.1f}",
        )
        deleted_new = []
        deleted_existing = []

        for item in self.new_items.get(page_num, []):
            if item.get("deleted", False):
                continue
            if self._new_item_hit(item, point):
                item["deleted"] = True
                deleted_new.append(item["id"])
                self._debug(
                    "erase_hit",
                    page=page_num + 1,
                    source="new",
                    kind=item.get("kind", "unknown"),
                    item_id=item["id"],
                )

        for item in self.existing_annots.get(page_num, []):
            xref = item["xref"]
            if xref in self.pending_deleted_xrefs:
                continue
            if self._existing_item_hit(item, point):
                self.pending_deleted_xrefs.add(xref)
                deleted_existing.append(xref)
                self._debug(
                    "erase_hit",
                    page=page_num + 1,
                    source="existing",
                    kind=item.get("kind", "unknown"),
                    xref=xref,
                    points=len(item.get("points") or []),
                )

        if not deleted_new and not deleted_existing:
            self._debug(
                "erase_miss",
                page=page_num + 1,
                x=f"{point.x():.1f}",
                y=f"{point.y():.1f}",
            )
            return False

        self.dirty_pages.add(page_num)
        self._undo_stack.append(
            {
                "type": "erase",
                "page": page_num,
                "new_ids": deleted_new,
                "existing_xrefs": deleted_existing,
            }
        )
        self._redo_stack.clear()
        self._debug(
            "erase_apply",
            page=page_num + 1,
            new=len(deleted_new),
            existing=len(deleted_existing),
        )
        return True

    def _new_item_hit(self, item, point: QPointF) -> bool:
        points = item.get("points") or []
        width = max(3.0, _safe_float(item.get("width"), 3.0))
        for idx in range(1, len(points)):
            if _point_segment_distance(point, points[idx - 1], points[idx]) <= width:
                return True
        return False

    def _existing_item_hit(self, item, point: QPointF) -> bool:
        kind = item.get("kind", "")
        if kind == "ink" and item.get("points"):
            tolerance = max(3.0, _safe_float(item.get("width"), 2.0) * 1.8)
            pts = item["points"]
            for idx in range(1, len(pts)):
                if _point_segment_distance(point, pts[idx - 1], pts[idx]) <= tolerance:
                    return True
        return _rect_contains_point(item["rect"], point, padding=3.0)

    def undo(self):
        if not self._undo_stack:
            return False
        action = self._undo_stack.pop()
        self._apply_inverse_action(action)
        self._redo_stack.append(action)
        return True

    def redo(self):
        if not self._redo_stack:
            return False
        action = self._redo_stack.pop()
        self._apply_action(action)
        self._undo_stack.append(action)
        return True

    def _apply_action(self, action):
        page_num = action.get("page", 0)
        if action["type"] == "add_new":
            for item in self.new_items.get(page_num, []):
                if item["id"] == action["item_id"]:
                    item["deleted"] = False
                    self.dirty_pages.add(page_num)
                    return
        if action["type"] == "erase":
            for item_id in action.get("new_ids", []):
                for item in self.new_items.get(page_num, []):
                    if item["id"] == item_id:
                        item["deleted"] = True
            for xref in action.get("existing_xrefs", []):
                self.pending_deleted_xrefs.add(xref)
            self.dirty_pages.add(page_num)

    def _apply_inverse_action(self, action):
        page_num = action.get("page", 0)
        if action["type"] == "add_new":
            for item in self.new_items.get(page_num, []):
                if item["id"] == action["item_id"]:
                    item["deleted"] = True
                    self.dirty_pages.add(page_num)
                    return
        if action["type"] == "erase":
            for item_id in action.get("new_ids", []):
                for item in self.new_items.get(page_num, []):
                    if item["id"] == item_id:
                        item["deleted"] = False
            for xref in action.get("existing_xrefs", []):
                self.pending_deleted_xrefs.discard(xref)
            self.dirty_pages.add(page_num)

    def has_unsaved_changes(self) -> bool:
        if self.pending_deleted_xrefs:
            return True
        for items in self.new_items.values():
            if any(not item.get("deleted", False) for item in items):
                return True
        return False

    def build_page_preview(self, page_num: int):
        page_num = int(page_num)
        page_deletes = [
            item["xref"]
            for item in self.existing_annots.get(page_num, [])
            if item["xref"] in self.pending_deleted_xrefs
        ]
        if not page_deletes:
            cached = PAGE_CACHE.get(self.pdf_path, page_num)
            if cached is not None and not cached.isNull():
                return cached

        temp_doc = None
        try:
            temp_doc = fitz.open(self.pdf_path)
            page = temp_doc.load_page(page_num)
            if page_deletes:
                for annot in list(page.annots() or []):
                    if annot.xref in page_deletes:
                        page.delete_annot(annot)
            pix = pdf_page_to_pixmap(page, fitz.Matrix(self.render_zoom, self.render_zoom), show_annots=True)
            return pix
        finally:
            if temp_doc is not None:
                temp_doc.close()

    def save(self):
        dirty_pages = sorted(self.dirty_pages)
        self._debug("save_start", dirty_pages=dirty_pages, zoom=self.render_label)
        if not dirty_pages and not self.has_unsaved_changes():
            self._debug("save_skip", reason="no_changes")
            return []

        try:
            for page_num, items in self.existing_annots.items():
                page = self.doc.load_page(page_num)
                for annot in list(page.annots() or []):
                    if annot.xref in self.pending_deleted_xrefs:
                        page.delete_annot(annot)

            for page_num, items in self.new_items.items():
                page = self.doc.load_page(page_num)
                for item in items:
                    if item.get("deleted", False):
                        continue
                    self._commit_new_item(page, item)

            try:
                self.doc.saveIncr()
            except Exception:
                temp_path = f"{self.pdf_path}.annot_tmp.pdf"
                self.doc.save(temp_path)
                self.doc.close()
                os.replace(temp_path, self.pdf_path)
                self.doc = fitz.open(self.pdf_path)

            PAGE_CACHE.invalidate_pages(self.pdf_path, dirty_pages)
            rendered = render_pdf_pages(self.pdf_path, dirty_pages, zoom=self.render_zoom, show_annots=True)
            update_page_hashes(self.pdf_path, dirty_pages)
            self._load_existing_annotations(dirty_pages)
            for page_num in dirty_pages:
                self.new_items[page_num] = []
            self.pending_deleted_xrefs.clear()
            self.dirty_pages.clear()
            self._undo_stack.clear()
            self._redo_stack.clear()
            self._debug("save_success", dirty_pages=dirty_pages, rendered=len(rendered))
            return dirty_pages
        except Exception as ex:
            self._debug("save_error", message=str(ex))
            raise

    def _commit_new_item(self, page, item):
        points = [(pt.x(), pt.y()) for pt in item.get("points", [])]
        if len(points) < 2:
            return
        annot = page.add_ink_annot([points])
        color = item.get("color", "#FF4444").lstrip("#")
        rgb = tuple(int(color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        try:
            annot.set_colors(stroke=rgb)
        except Exception:
            pass
        try:
            annot.set_border(width=_safe_float(item.get("width"), 2.0))
        except Exception:
            pass
        try:
            annot.set_info(
                title="AnkiOcclusion",
                subject="anki_occlusion_beta",
                content=json.dumps(
                    {
                        "kind": item.get("kind", "pen"),
                        "points": _to_point_pairs(item.get("points", [])),
                    },
                    separators=(",", ":"),
                ),
            )
        except Exception:
            pass
        try:
            annot.update(opacity=_safe_float(item.get("opacity"), 1.0))
        except Exception:
            try:
                annot.update()
            except Exception:
                pass
