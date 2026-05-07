import json
import unittest

from PyQt5.QtCore import QPointF

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


if __name__ == "__main__":
    unittest.main()
