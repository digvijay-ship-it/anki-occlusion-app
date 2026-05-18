import gc
import json
import math
import os
import stat
import time
import uuid
from collections import Counter

import fitz
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPixmap

from pdf_engine import (
    PAGE_CACHE,
    choose_pdf_render_zoom,
    ensure_pdf_cache_profile,
    load_pdf_skeleton,
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


def _replace_file_with_retry(
    src_path: str, dst_path: str, attempts: int = 12, delay: float = 0.08
):
    last_error = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            os.replace(src_path, dst_path)
            return
        except PermissionError as ex:
            last_error = ex
            gc.collect()
            time.sleep(delay)
    raise PermissionError(
        f"Windows still has a file handle open after {attempts} replace attempts."
    ) from last_error


def _open_pdf_from_memory(path: str):
    with open(path, "rb") as f:
        data = f.read()
    return fitz.open(stream=data, filetype="pdf")


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
    SELECTABLE_VISUAL_KINDS = {"image", "stamp"}

    TOOL_STYLES = {
        "pen": {"color": "#FF4444", "width": 2.8, "opacity": 1.0},
        "highlight": {"color": "#FFD54A", "width": 12.0, "opacity": 0.30},
    }

    def __init__(self, pdf_path: str, initial_page: int = 0, preload_radius: int = 1):
        self.pdf_path = os.path.abspath(pdf_path)
        self.doc = _open_pdf_from_memory(self.pdf_path)
        if self.doc.is_encrypted:
            self.doc.close()
            raise RuntimeError("PDF is password protected.")

        self.page_count = len(self.doc)
        self.render_zoom = choose_pdf_render_zoom(self.page_count)
        self.render_label = "3x" if self.render_zoom >= 3.0 else "2x"
        self.cache_reset = ensure_pdf_cache_profile(self.pdf_path, self.render_zoom)
        self.skeleton = load_pdf_skeleton(self.pdf_path, zoom=self.render_zoom)
        self.page_pixel_dims = list(getattr(self.skeleton, "page_dims", []) or [])
        self.page_pdf_dims = [
            (
                float(self.doc.load_page(i).rect.width),
                float(self.doc.load_page(i).rect.height),
            )
            for i in range(self.page_count)
        ]
        self.dirty_pages = set()
        self.pending_deleted_xrefs = set()
        self.pending_image_moves = {}
        self.existing_annots = {}
        self.new_items = {}
        from collections import deque

        self._undo_stack = deque(maxlen=100)
        self._redo_stack = deque(maxlen=100)
        self._loaded_existing_pages = set()
        self._preload_radius = max(0, int(preload_radius or 0))
        self.ensure_existing_annotations_loaded(
            center_page=initial_page, radius=self._preload_radius
        )

    def close(self):
        if getattr(self, "doc", None) is not None:
            self.doc.close()
            self.doc = None

    def _debug(self, action: str, **data):
        return

    def _page_scale_factors(self, page_num: int):
        if not (0 <= int(page_num) < self.page_count):
            return 1.0, 1.0
        px_w, px_h = (
            self.page_pixel_dims[page_num]
            if page_num < len(self.page_pixel_dims)
            else (0, 0)
        )
        pdf_w, pdf_h = self.page_pdf_dims[page_num]
        sx = float(px_w) / max(float(pdf_w), 1.0)
        sy = float(px_h) / max(float(pdf_h), 1.0)
        return sx or 1.0, sy or 1.0

    def _canvas_to_pdf_points(self, page_num: int, points):
        sx, sy = self._page_scale_factors(page_num)
        out = []
        for pt in _to_qpointf_list(points):
            out.append((float(pt.x()) / sx, float(pt.y()) / sy))
        return out

    def _pdf_to_canvas_points(self, page_num: int, points):
        sx, sy = self._page_scale_factors(page_num)
        out = []
        for pt in _to_qpointf_list(points):
            out.append(QPointF(float(pt.x()) * sx, float(pt.y()) * sy))
        return out

    def _pdf_rect_to_canvas(self, page_num: int, rect_tuple):
        sx, sy = self._page_scale_factors(page_num)
        return (
            float(rect_tuple[0]) * sx,
            float(rect_tuple[1]) * sy,
            float(rect_tuple[2]) * sx,
            float(rect_tuple[3]) * sy,
        )

    def _canvas_rect_to_pdf_rect(
        self, page_num: int, rect
    ) -> tuple[float, float, float, float]:
        sx, sy = self._page_scale_factors(page_num)
        qrect = rect if isinstance(rect, QRectF) else QRectF(*rect)
        return (
            float(qrect.x()) / sx,
            float(qrect.y()) / sy,
            float(qrect.right()) / sx,
            float(qrect.bottom()) / sy,
        )

    def _canvas_width_to_pdf(self, page_num: int, width: float) -> float:
        sx, sy = self._page_scale_factors(page_num)
        return float(width) / max((sx + sy) / 2.0, 0.01)

    def _pdf_width_to_canvas(self, page_num: int, width: float) -> float:
        sx, sy = self._page_scale_factors(page_num)
        return float(width) * ((sx + sy) / 2.0)

    def _load_existing_annotations(self, page_nums=None):
        if page_nums is None:
            targets = range(self.page_count)
        else:
            targets = sorted(
                {int(pn) for pn in page_nums if 0 <= int(pn) < self.page_count}
            )

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
            self._loaded_existing_pages.add(page_num)

    def _page_window(self, center_page: int, radius: int | None = None):
        radius = self._preload_radius if radius is None else max(0, int(radius))
        total_pages = int(getattr(self, "page_count", 0) or 0)
        if total_pages <= 0:
            return []
        center = max(0, min(int(center_page), total_pages - 1))
        start = max(0, center - radius)
        end = min(total_pages - 1, center + radius)
        return list(range(start, end + 1))

    def ensure_existing_annotations_loaded(
        self, center_page: int | None = None, radius: int | None = None, page_nums=None
    ):
        if not hasattr(self, "_loaded_existing_pages"):
            self._loaded_existing_pages = set()
        total_pages = int(getattr(self, "page_count", 0) or 0)
        if total_pages <= 0 and getattr(self, "doc", None) is None:
            return []
        if page_nums is None:
            if center_page is None:
                return []
            target_pages = self._page_window(center_page, radius=radius)
        else:
            if total_pages > 0:
                target_pages = sorted(
                    {int(pn) for pn in page_nums if 0 <= int(pn) < total_pages}
                )
            else:
                target_pages = sorted({int(pn) for pn in page_nums if int(pn) >= 0})
        missing = [pn for pn in target_pages if pn not in self._loaded_existing_pages]
        if not missing:
            return []
        self._load_existing_annotations(missing)
        return missing

    def _build_existing_item(self, page_num: int, annot):
        subtype = ""
        try:
            subtype = (annot.type[1] or "").lower()
        except Exception:
            subtype = "unknown"

        rect_bounds = self._pdf_rect_to_canvas(page_num, _page_rect_tuple(annot.rect))
        width = 2.0
        try:
            border = annot.border or {}
            width = _safe_float(border.get("width", 2.0), 2.0)
        except Exception:
            width = 2.0

        vertices = []
        try:
            vertices = self._pdf_to_canvas_points(
                page_num,
                _flatten_annot_vertices(getattr(annot, "vertices", None)),
            )
        except Exception:
            vertices = []
        if not vertices:
            vertices = self._pdf_to_canvas_points(page_num, _parse_saved_points(annot))

        info = {}
        try:
            info = annot.info or {}
        except Exception:
            info = {}
        is_app_image = (
            info.get("title") == "AnkiOcclusion"
            and info.get("subject") == "anki_occlusion_image"
        )

        rect = (
            QRectF(
                rect_bounds[0],
                rect_bounds[1],
                max(1.0, rect_bounds[2] - rect_bounds[0]),
                max(1.0, rect_bounds[3] - rect_bounds[1]),
            )
            if is_app_image
            else rect_bounds
        )

        item = {
            "id": f"existing:{annot.xref}",
            "page": page_num,
            "source": "existing",
            "kind": "image" if is_app_image else subtype,
            "xref": int(annot.xref),
            "rect": rect,
            "saved_rect": rect,
            "points": vertices,
            "width": self._pdf_width_to_canvas(page_num, width),
        }
        if is_app_image:
            image_payload = self._image_payload_from_annot(annot)
            if image_payload:
                item.update(image_payload)
        return item

    def get_new_items_for_page(self, page_num: int):
        page_num = int(page_num)
        self.ensure_existing_annotations_loaded(page_nums=[page_num])
        existing_visuals = [
            item
            for item in self.existing_annots.get(page_num, [])
            if item.get("kind") in self.SELECTABLE_VISUAL_KINDS
            and item.get("xref") not in self.pending_deleted_xrefs
        ]
        return existing_visuals + [
            item
            for item in self.new_items.get(page_num, [])
            if not item.get("deleted", False)
        ]

    def add_new_item(
        self, page_num: int, tool: str, points, style_override: dict | None = None
    ):
        if tool not in self.TOOL_STYLES:
            return None
        pts = _to_qpointf_list(points)
        if len(pts) < 2:
            return None
        style = dict(self.TOOL_STYLES[tool])
        if style_override:
            style.update(
                {k: v for k, v in dict(style_override).items() if v is not None}
            )
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
        self._undo_stack.append(
            {"type": "add_new", "page": int(page_num), "item_id": item["id"]}
        )
        self._redo_stack.clear()
        self._debug(
            "add_new",
            page=page_num + 1,
            tool=tool,
            points=len(pts),
            color=item["color"],
            width=item["width"],
        )
        return item

    def add_image_item(
        self, page_num: int, image_bytes: bytes, pixmap: QPixmap, rect: QRectF
    ):
        page_num = int(page_num)
        if not image_bytes or pixmap is None or pixmap.isNull():
            return None
        item = {
            "id": f"image:{uuid.uuid4().hex}",
            "page": page_num,
            "source": "new",
            "kind": "image",
            "image_bytes": bytes(image_bytes),
            "pixmap": QPixmap(pixmap),
            "rect": QRectF(rect),
            "deleted": False,
        }
        self.new_items.setdefault(page_num, []).append(item)
        self.dirty_pages.add(page_num)
        self._undo_stack.append(
            {"type": "add_new", "page": page_num, "item_id": item["id"]}
        )
        self._redo_stack.clear()
        self._debug(
            "image_add",
            page=page_num + 1,
            item=item["id"],
            rect=self._format_rect(item["rect"]),
            bytes=len(image_bytes),
        )
        return item

    def move_image_item(
        self,
        page_num: int,
        item_id: str,
        new_rect: QRectF,
        old_rect: QRectF | None = None,
    ):
        page_num = int(page_num)
        self.ensure_existing_annotations_loaded(page_nums=[page_num])
        item = self._find_new_item(page_num, item_id)
        if item is None:
            item = self._find_existing_item(page_num, item_id)
        if item is None or item.get("kind") != "image" or item.get("deleted", False):
            self._debug(
                "image_move_skip", page=page_num + 1, item=item_id, reason="not_found"
            )
            return False
        old_rect = QRectF(
            old_rect if old_rect is not None else item.get("rect", QRectF())
        )
        rect = QRectF(new_rect)
        item["rect"] = rect
        if item.get("source") == "existing":
            saved_rect = self._rect_from_value(item.get("saved_rect", old_rect))
            if self._rects_close(saved_rect, rect):
                self.pending_image_moves.pop(int(item["xref"]), None)
            else:
                self.pending_image_moves[int(item["xref"])] = QRectF(rect)
        else:
            item["last_saved_rect"] = QRectF(rect)
        self.dirty_pages.add(page_num)
        if self._rects_close(old_rect, rect):
            return True
        self._undo_stack.append(
            {
                "type": "move_image",
                "page": page_num,
                "item_id": item_id,
                "old_rect": old_rect,
                "new_rect": QRectF(rect),
            }
        )
        self._redo_stack.clear()
        self._debug(
            "image_move_apply",
            page=page_num + 1,
            item=item_id,
            rect=self._format_rect(rect),
        )
        return True

    def resize_image_item(
        self,
        page_num: int,
        item_id: str,
        new_rect: QRectF,
        old_rect: QRectF | None = None,
    ) -> bool:
        # Resize = move + dimension change. Reuses move_image_item.
        # Call sites in pdf_annotation_dialog should use this for handle drags
        # so undo history labels the action correctly.
        return self.move_image_item(page_num, item_id, new_rect, old_rect)

    def delete_image_item(self, page_num: int, item_id: str):
        page_num = int(page_num)
        self.ensure_existing_annotations_loaded(page_nums=[page_num])
        item = self._find_new_item(page_num, item_id)
        if (
            item is not None
            and item.get("kind") == "image"
            and not item.get("deleted", False)
        ):
            item["deleted"] = True
            self.dirty_pages.add(page_num)
            self._undo_stack.append(
                {
                    "type": "erase",
                    "page": page_num,
                    "new_ids": [item_id],
                    "existing_xrefs": [],
                }
            )
            self._redo_stack.clear()
            self._debug(
                "image_delete_apply", page=page_num + 1, source="new", item=item_id
            )
            return True

        item = self._find_existing_item(page_num, item_id)
        if item is None or item.get("kind") not in self.SELECTABLE_VISUAL_KINDS:
            self._debug(
                "image_delete_skip", page=page_num + 1, item=item_id, reason="not_found"
            )
            return False
        xref = int(item["xref"])
        if xref in self.pending_deleted_xrefs:
            return False
        self.pending_deleted_xrefs.add(xref)
        self.pending_image_moves.pop(xref, None)
        self.dirty_pages.add(page_num)
        self._undo_stack.append(
            {"type": "erase", "page": page_num, "new_ids": [], "existing_xrefs": [xref]}
        )
        self._redo_stack.clear()
        self._debug(
            "image_delete_apply",
            page=page_num + 1,
            source="existing",
            kind=item.get("kind"),
            xref=xref,
        )
        return True

    def erase_at_point(self, page_num: int, point):
        page_num = int(page_num)
        self.ensure_existing_annotations_loaded(page_nums=[page_num])
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
            if item.get("kind") in self.SELECTABLE_VISUAL_KINDS:
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
            if item.get("kind") in self.SELECTABLE_VISUAL_KINDS:
                continue
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
        if item.get("kind") == "image":
            rect = item.get("rect")
            if rect is None:
                return False
            rect = rect if isinstance(rect, QRectF) else QRectF(*rect)
            return rect.contains(point)
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
        if action["type"] == "move_image":
            item = self._find_new_item(page_num, action.get("item_id"))
            if item is None:
                item = self._find_existing_item(page_num, action.get("item_id"))
            if item is not None:
                item["rect"] = QRectF(action["new_rect"])
                if item.get("source") == "existing":
                    saved_rect = self._rect_from_value(
                        item.get("saved_rect", action["old_rect"])
                    )
                    if self._rects_close(saved_rect, item["rect"]):
                        self.pending_image_moves.pop(int(item["xref"]), None)
                    else:
                        self.pending_image_moves[int(item["xref"])] = QRectF(
                            action["new_rect"]
                        )
                else:
                    item["last_saved_rect"] = QRectF(action["new_rect"])
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
        if action["type"] == "move_image":
            item = self._find_new_item(page_num, action.get("item_id"))
            if item is None:
                item = self._find_existing_item(page_num, action.get("item_id"))
            if item is not None:
                item["rect"] = QRectF(action["old_rect"])
                if item.get("source") == "existing":
                    saved_rect = self._rect_from_value(
                        item.get("saved_rect", action["old_rect"])
                    )
                    if self._rects_close(saved_rect, item["rect"]):
                        self.pending_image_moves.pop(int(item["xref"]), None)
                    else:
                        self.pending_image_moves[int(item["xref"])] = QRectF(
                            action["old_rect"]
                        )
                else:
                    item["last_saved_rect"] = QRectF(action["old_rect"])
                self.dirty_pages.add(page_num)

    def has_unsaved_changes(self) -> bool:
        if self.pending_deleted_xrefs:
            return True
        if self.pending_image_moves:
            return True
        for items in self.new_items.values():
            if any(not item.get("deleted", False) for item in items):
                return True
        return False

    def build_page_preview(self, page_num: int):
        page_num = int(page_num)
        self.ensure_existing_annotations_loaded(page_nums=[page_num])
        page_deletes = [
            item["xref"]
            for item in self.existing_annots.get(page_num, [])
            if item["xref"] in self.pending_deleted_xrefs
        ]
        page_moves = {
            xref: {
                "rect": rect,
                "item": self._find_existing_item(page_num, f"existing:{xref}"),
            }
            for xref, rect in self.pending_image_moves.items()
            if any(
                item.get("xref") == xref
                for item in self.existing_annots.get(page_num, [])
            )
        }
        if not page_deletes and not page_moves:
            cached = PAGE_CACHE.get(self.pdf_path, page_num)
            if cached is not None and not cached.isNull():
                return cached

        temp_doc = None
        try:
            temp_doc = _open_pdf_from_memory(self.pdf_path)
            page = temp_doc.load_page(page_num)
            if page_deletes or page_moves:
                for annot in list(page.annots() or []):
                    xref = int(annot.xref)
                    if xref in page_deletes or xref in page_moves:
                        page.delete_annot(annot)
                for move in page_moves.values():
                    item = dict(move.get("item") or {})
                    if item.get("image_bytes"):
                        item["rect"] = move["rect"]
                        page = self._commit_image_item(page, item, doc=temp_doc)
            pix = pdf_page_to_pixmap(
                page, fitz.Matrix(self.render_zoom, self.render_zoom), show_annots=True
            )
            return pix
        finally:
            if temp_doc is not None:
                temp_doc.close()

    def save(self):
        dirty_pages = sorted(self.dirty_pages)

        if not dirty_pages and not self.has_unsaved_changes():
            return []

        try:
            page = None
            annot = None
            for page_num, items in self.existing_annots.items():
                page = self.doc.load_page(page_num)
                moved_items = []
                for annot in list(page.annots() or []):
                    xref = int(annot.xref)
                    if xref in self.pending_deleted_xrefs:
                        page.delete_annot(annot)
                    elif xref in self.pending_image_moves:
                        moved_item = self._find_existing_item(
                            page_num, f"existing:{xref}"
                        )
                        page.delete_annot(annot)
                        if moved_item is not None and moved_item.get("image_bytes"):
                            moved_copy = dict(moved_item)
                            moved_copy["rect"] = self.pending_image_moves[xref]
                            moved_items.append(moved_copy)
                            self._debug(
                                "image_move_commit",
                                page=page_num + 1,
                                xref=xref,
                                rect=self._format_rect(self.pending_image_moves[xref]),
                            )
                for moved_item in moved_items:
                    page = self._commit_image_item(page, moved_item, doc=self.doc)

            for page_num, items in self.new_items.items():
                page = self.doc.load_page(page_num)
                for item in items:
                    if item.get("deleted", False):
                        continue
                    if item.get("kind") == "image":
                        page = self._commit_image_item(page, item, doc=self.doc)
                for item in items:
                    if item.get("deleted", False) or item.get("kind") == "image":
                        continue
                    self._commit_new_item(page, item)

            page = None
            annot = None
            gc.collect()

            try:
                self.doc.saveIncr()
                self._debug("save_mode", mode="incremental")
            except Exception as incr_ex:
                temp_path = f"{self.pdf_path}.annot_tmp.pdf"
                self._debug("save_mode", mode="replacement", reason=str(incr_ex))
                try:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass
                    self.doc.save(temp_path)
                    self.doc.close()
                    self.doc = None
                    page = None
                    annot = None
                    gc.collect()
                    try:
                        os.chmod(self.pdf_path, stat.S_IWRITE | stat.S_IREAD)
                    except OSError:
                        pass
                    _replace_file_with_retry(temp_path, self.pdf_path)
                    self.doc = _open_pdf_from_memory(self.pdf_path)
                except PermissionError as perm_ex:
                    if self.doc is None:
                        self.doc = _open_pdf_from_memory(self.pdf_path)
                    raise PermissionError(
                        "Windows blocked replacing this PDF even after our own PDF handles were closed. "
                        f"A saved temp copy remains here: {temp_path}"
                    ) from perm_ex
                except Exception:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass
                    if self.doc is None:
                        self.doc = _open_pdf_from_memory(self.pdf_path)
                    raise

            PAGE_CACHE.invalidate_pages(self.pdf_path, dirty_pages)
            rendered = render_pdf_pages(
                self.pdf_path, dirty_pages, zoom=self.render_zoom, show_annots=True
            )
            update_page_hashes(self.pdf_path, dirty_pages)
            self._load_existing_annotations(dirty_pages)
            for page_num in dirty_pages:
                self.new_items[page_num] = []
            self.pending_deleted_xrefs.clear()
            self.pending_image_moves.clear()
            self.dirty_pages.clear()
            self._undo_stack.clear()
            self._redo_stack.clear()
            return dirty_pages
        except Exception:
            raise

    def _commit_new_item(self, page, item):
        if item.get("kind") == "image":
            return
        page_num = int(item.get("page", 0))
        view_points = _to_qpointf_list(item.get("points", []))
        points = self._canvas_to_pdf_points(page_num, view_points)
        if len(points) < 2:
            return
        annot = page.add_ink_annot([points])
        color = item.get("color", "#FF4444").lstrip("#")
        rgb = tuple(int(color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
        try:
            annot.set_colors(stroke=rgb)
        except Exception:
            pass
        try:
            pdf_width = self._canvas_width_to_pdf(
                page_num,
                _safe_float(item.get("width"), 2.0),
            )
            annot.set_border(width=pdf_width)
        except Exception:
            pdf_width = _safe_float(item.get("width"), 2.0)
        try:
            annot.set_info(
                title="AnkiOcclusion",
                subject="anki_occlusion_beta",
                content=json.dumps(
                    {
                        "kind": item.get("kind", "pen"),
                        "points": points,
                    },
                    separators=(",", ":"),
                ),
            )
        except Exception:
            pass
        self._debug(
            "commit_new",
            page=page_num + 1,
            view_points=len(view_points),
            pdf_points=len(points),
            view_first=(
                f"{view_points[0].x():.1f},{view_points[0].y():.1f}"
                if view_points
                else ""
            ),
            pdf_first=(f"{points[0][0]:.1f},{points[0][1]:.1f}" if points else ""),
            view_width=f"{_safe_float(item.get('width'), 2.0):.2f}",
            pdf_width=f"{pdf_width:.2f}",
        )
        try:
            annot.update(opacity=_safe_float(item.get("opacity"), 1.0))
        except Exception:
            try:
                annot.update()
            except Exception:
                pass

    def _commit_image_item(self, page, item, doc=None):
        page_num = int(item.get("page", 0))
        image_bytes = item.get("image_bytes") or b""
        if not image_bytes:
            return page
        pdf_rect = self._canvas_rect_to_pdf_rect(page_num, item.get("rect", QRectF()))
        rect = fitz.Rect(*pdf_rect)
        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
            return page

        # doc is passed explicitly to avoid page.parent returning None
        # in some fitz versions when doc is a memory-stream document.
        if doc is None:
            doc = page.parent
        if doc is None:
            doc = self.doc
        image_xref = self._register_image_xobject(doc, image_bytes)
        if image_xref <= 0:
            return page

        # Registering the image xobject creates and deletes a temp page,
        # which orphans our current `page` object in PyMuPDF. We MUST reload it.
        page = doc.load_page(page_num)

        annot = page.add_rect_annot(rect)
        # Set info BEFORE update() so fitz encodes our metadata
        try:
            annot.set_info(
                title="AnkiOcclusion",
                subject="anki_occlusion_image",
                content=json.dumps(
                    {"kind": "image", "tool": "screenshot", "id": item.get("id")},
                    separators=(",", ":"),
                ),
            )
        except Exception:
            pass
        # Set border width 0 — hide the default blue rectangle border
        try:
            annot.set_border(width=0)
        except Exception:
            pass
        # Build and attach the AP stream BEFORE update() so fitz won't
        # overwrite it with a default appearance.
        self._set_image_annotation_appearance(doc, annot, image_xref, rect)
        # update() with opacity=1 — do NOT let it regenerate the appearance
        try:
            annot.update(opacity=1.0)
        except Exception:
            try:
                annot.update()
            except Exception:
                pass
        # Re-attach AP after update() in case fitz wiped it
        self._set_image_annotation_appearance(doc, annot, image_xref, rect)
        self._debug(
            "image_commit",
            page=page_num + 1,
            item=item.get("id"),
            view_rect=self._format_rect(item.get("rect", QRectF())),
            pdf_rect=",".join(f"{value:.2f}" for value in pdf_rect),
            bytes=len(image_bytes),
        )
        return page

    def _register_image_xobject(self, doc, image_bytes: bytes) -> int:
        """Register image bytes into doc and return the XObject xref.
        Places image at an off-page rect on a temp page within the SAME doc,
        then removes that page. The xref stays valid in doc."""
        try:
            page_count_before = doc.page_count
            tmp_page = doc.new_page(-1, width=10, height=10)
            xref = tmp_page.insert_image(fitz.Rect(0, 0, 10, 10), stream=image_bytes)
            # Remove the temp page — xref remains valid in the doc
            doc.delete_page(doc.page_count - 1)
            return xref
        except Exception:
            return 0

    def _find_new_item(self, page_num: int, item_id: str):
        for item in self.new_items.get(int(page_num), []):
            if item.get("id") == item_id:
                return item
        return None

    def _find_existing_item(self, page_num: int, item_id: str):
        for item in self.existing_annots.get(int(page_num), []):
            if item.get("id") == item_id:
                return item
        return None

    def _image_payload_from_annot(self, annot):
        doc = annot.parent.parent
        try:
            _kind, ap_ref = doc.xref_get_key(annot.xref, "AP/N")
            form_xref = int(str(ap_ref).split()[0])
            _kind, image_ref = doc.xref_get_key(form_xref, "Resources/XObject/Im0")
            image_xref = int(str(image_ref).split()[0])
            extracted = doc.extract_image(image_xref)
            image_bytes = extracted.get("image") or b""
            if not image_bytes:
                return {}
            pixmap = QPixmap()
            pixmap.loadFromData(image_bytes)
            self._debug(
                "image_loaded",
                xref=annot.xref,
                image=image_xref,
                bytes=len(image_bytes),
                pixmap=f"{pixmap.width()}x{pixmap.height()}",
            )
            return {
                "image_xref": image_xref,
                "image_bytes": image_bytes,
                "pixmap": pixmap,
            }
        except Exception as ex:
            self._debug(
                "image_load_failed", xref=getattr(annot, "xref", ""), error=str(ex)
            )
            return {}

    def _set_image_annotation_appearance(
        self, doc, annot, image_xref: int, rect: fitz.Rect
    ):
        width = max(float(rect.width), 1.0)
        height = max(float(rect.height), 1.0)
        form_xref = doc.get_new_xref()
        # Form XObject with BBox matching the annotation rect dimensions.
        # The content stream draws Im0 scaled to fill the BBox exactly.
        # PDF image space: origin bottom-left, y up. The CTM
        #   "w 0 0 h 0 0 cm" scales unit-square image to [0..w] x [0..h].
        # fitz maps the annotation rect to this space when rendering.
        obj = (
            f"<< /Type /XObject /Subtype /Form "
            f"/BBox [0 0 {width:.4f} {height:.4f}] "
            f"/Matrix [1 0 0 1 0 0] "
            f"/Resources << /XObject << /Im0 {int(image_xref)} 0 R >> >> >>"
        )
        doc.update_object(form_xref, obj)
        # Draw image: scale to fill BBox then paint
        stream = f"q {width:.4f} 0 0 {height:.4f} 0 0 cm /Im0 Do Q"
        doc.update_stream(form_xref, stream.encode("ascii"))
        # Set AP — use direct xref_set_key so fitz can't overwrite it
        doc.xref_set_key(annot.xref, "AP", f"<</N {form_xref} 0 R>>")
        # Also clear the default appearance string so no fallback border renders
        try:
            doc.xref_set_key(annot.xref, "BS", "<</W 0>>")
        except Exception:
            pass

    @staticmethod
    def _format_rect(rect) -> str:
        qrect = PdfAnnotationSession._rect_from_value(rect)
        return (
            f"{qrect.x():.1f},{qrect.y():.1f},{qrect.width():.1f},{qrect.height():.1f}"
        )

    @staticmethod
    def _rects_close(a: QRectF, b: QRectF, tolerance: float = 0.01) -> bool:
        a = PdfAnnotationSession._rect_from_value(a)
        b = PdfAnnotationSession._rect_from_value(b)
        return (
            abs(a.x() - b.x()) <= tolerance
            and abs(a.y() - b.y()) <= tolerance
            and abs(a.width() - b.width()) <= tolerance
            and abs(a.height() - b.height()) <= tolerance
        )

    @staticmethod
    def _rect_from_value(rect) -> QRectF:
        if isinstance(rect, QRectF):
            return QRectF(rect)
        return QRectF(*rect)
