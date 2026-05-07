import json
import unittest

from PyQt5.QtCore import QPointF, QRectF

from services.pdf_annotation_service import (
    PdfAnnotationSession,
    _flatten_annot_vertices,
    _parse_saved_points,
)


class _FakeAnnot:
    def __init__(self, *, vertices=None, info=None):
        self.vertices = vertices
        self.info = info or {}


class PdfAnnotationServiceTests(unittest.TestCase):
    def test_flatten_annot_vertices_handles_nested_ink_paths(self):
        annot = _FakeAnnot(
            vertices=[
                [(10, 20), (30, 40)],
                [QPointF(50, 60), QPointF(70, 80)],
            ]
        )
        points = _flatten_annot_vertices(annot.vertices)
        coords = [(round(pt.x()), round(pt.y())) for pt in points]
        self.assertEqual(coords, [(10, 20), (30, 40), (50, 60), (70, 80)])

    def test_parse_saved_points_reads_anki_saved_metadata(self):
        annot = _FakeAnnot(
            info={
                "content": json.dumps(
                    {"kind": "pen", "points": [[11.5, 22.5], [33.0, 44.0]]}
                )
            }
        )
        points = _parse_saved_points(annot)
        coords = [(pt.x(), pt.y()) for pt in points]
        self.assertEqual(coords, [(11.5, 22.5), (33.0, 44.0)])

    def test_canvas_pdf_point_conversion_round_trips(self):
        session = PdfAnnotationSession.__new__(PdfAnnotationSession)
        session.page_count = 1
        session.page_pixel_dims = [(900, 1200)]
        session.page_pdf_dims = [(300.0, 400.0)]

        canvas_points = [QPointF(90.0, 180.0), QPointF(300.0, 600.0)]
        pdf_points = session._canvas_to_pdf_points(0, canvas_points)
        self.assertEqual(pdf_points, [(30.0, 60.0), (100.0, 200.0)])

        restored = session._pdf_to_canvas_points(0, pdf_points)
        coords = [(pt.x(), pt.y()) for pt in restored]
        self.assertEqual(coords, [(90.0, 180.0), (300.0, 600.0)])

    def test_canvas_pdf_rect_conversion_for_pasted_image(self):
        session = PdfAnnotationSession.__new__(PdfAnnotationSession)
        session.page_count = 1
        session.page_pixel_dims = [(900, 1200)]
        session.page_pdf_dims = [(300.0, 400.0)]

        pdf_rect = session._canvas_rect_to_pdf_rect(0, QRectF(90.0, 120.0, 300.0, 240.0))
        self.assertEqual(pdf_rect, (30.0, 40.0, 130.0, 120.0))

    def test_existing_pdf_rect_bounds_become_image_width_height_rect(self):
        session = PdfAnnotationSession.__new__(PdfAnnotationSession)
        session.page_count = 1
        session.page_pixel_dims = [(900, 1200)]
        session.page_pdf_dims = [(300.0, 400.0)]

        bounds = session._pdf_rect_to_canvas(0, (10.0, 20.0, 110.0, 80.0))
        image_rect = QRectF(
            bounds[0],
            bounds[1],
            bounds[2] - bounds[0],
            bounds[3] - bounds[1],
        )

        self.assertEqual(image_rect, QRectF(30.0, 60.0, 300.0, 180.0))

    def test_move_image_item_keeps_undo_rect(self):
        session = PdfAnnotationSession.__new__(PdfAnnotationSession)
        session.new_items = {
            0: [
                {
                    "id": "image:test",
                    "kind": "image",
                    "rect": QRectF(10.0, 20.0, 100.0, 80.0),
                    "deleted": False,
                }
            ]
        }
        session.dirty_pages = set()
        session._undo_stack = []
        session._redo_stack = []
        session._debug = lambda *args, **kwargs: None

        moved = session.move_image_item(
            0,
            "image:test",
            QRectF(40.0, 60.0, 100.0, 80.0),
            old_rect=QRectF(10.0, 20.0, 100.0, 80.0),
        )

        self.assertTrue(moved)
        self.assertEqual(session.new_items[0][0]["rect"], QRectF(40.0, 60.0, 100.0, 80.0))
        self.assertEqual(session._undo_stack[-1]["old_rect"], QRectF(10.0, 20.0, 100.0, 80.0))

    def test_delete_image_item_uses_delete_flow_not_eraser(self):
        session = PdfAnnotationSession.__new__(PdfAnnotationSession)
        session.new_items = {
            0: [
                {
                    "id": "image:test",
                    "kind": "image",
                    "rect": QRectF(10.0, 20.0, 100.0, 80.0),
                    "deleted": False,
                }
            ]
        }
        session.existing_annots = {}
        session.pending_deleted_xrefs = set()
        session.pending_image_moves = {}
        session.dirty_pages = set()
        session._undo_stack = []
        session._redo_stack = []
        session._debug = lambda *args, **kwargs: None

        self.assertFalse(session.erase_at_point(0, QPointF(20.0, 30.0)))
        self.assertFalse(session.new_items[0][0]["deleted"])

        self.assertTrue(session.delete_image_item(0, "image:test"))
        self.assertTrue(session.new_items[0][0]["deleted"])

    def test_delete_existing_stamp_with_delete_flow(self):
        session = PdfAnnotationSession.__new__(PdfAnnotationSession)
        session.new_items = {}
        session.existing_annots = {
            0: [
                {
                    "id": "existing:42",
                    "kind": "stamp",
                    "xref": 42,
                    "rect": (10.0, 20.0, 110.0, 80.0),
                }
            ]
        }
        session.pending_deleted_xrefs = set()
        session.pending_image_moves = {}
        session.dirty_pages = set()
        session._undo_stack = []
        session._redo_stack = []
        session._debug = lambda *args, **kwargs: None

        self.assertTrue(session.delete_image_item(0, "existing:42"))
        self.assertEqual(session.pending_deleted_xrefs, {42})
        self.assertEqual(session.dirty_pages, {0})


if __name__ == "__main__":
    unittest.main()
