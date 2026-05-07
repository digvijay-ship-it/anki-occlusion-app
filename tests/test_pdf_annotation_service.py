import json
import unittest

from PyQt5.QtCore import QPointF

from services.pdf_annotation_service import _flatten_annot_vertices, _parse_saved_points


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


if __name__ == "__main__":
    unittest.main()
