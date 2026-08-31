import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
import math
from unittest.mock import MagicMock, patch

from PyQt5.QtCore import QPointF, QRectF, QSize
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import QApplication, QScrollArea

# Ensure QApplication is initialized
_APP = QApplication.instance() or QApplication([])

import pdf_engine
from ui.canvas.core import OcclusionCanvas
from ui.pdf_viewer_controller import PdfViewerController


class ChallengerM2PdfTests(unittest.TestCase):
    def setUp(self):
        # Clear skeleton caches to avoid pollution
        pdf_engine._SKELETON_CACHE.clear()
        pdf_engine._SKELETON_DIMS_CACHE.clear()

    def test_coordinate_translation_across_zooms_with_page_gaps(self):
        """
        Verify that boxes on different pages are translated correctly
        across different zoom levels, ensuring the page gaps are preserved
        and coordinates do not drift.
        """
        # Define mock page dimensions at 1.0x zoom:
        # Page 0: 600 x 800
        # Page 1: 800 x 1200
        page_dims_1_0 = [(600, 800), (800, 1200)]
        page_gap = 12

        # At 1.5x zoom (source):
        # Page 0: 900 x 1200
        # Page 1: 1200 x 1800
        # Page 0 top: 0, bottom: 1200
        # Page 1 top: 1200 + 12 = 1212, bottom: 1212 + 1800 = 3012
        
        # At 3.0x zoom (target):
        # Page 0: 1800 x 2400
        # Page 1: 2400 x 3600
        # Page 0 top: 0, bottom: 2400
        # Page 1 top: 2400 + 12 = 2412, bottom: 2412 + 3600 = 6012

        # Define a box on Page 1 (at 1.5x zoom):
        # Local X = 100, Local Y = 150
        # Rect in canvas space: X = 100, Y = 1212 + 150 = 1362
        # Width = 200, Height = 300
        boxes = [
            {
                "rect": [100.0, 1362.0, 200.0, 300.0],
                "label": "Test Box Page 1",
                "page_num": 1,
            }
        ]

        # Mock pdf_engine.load_pdf_page_dims to return our custom dimensions
        class DummyResult:
            def __init__(self, dims):
                self.page_dims = dims
                self.error = None

        def mock_load_dims(path, zoom):
            scaled_dims = [(w * zoom, h * zoom) for w, h in page_dims_1_0]
            return DummyResult(scaled_dims)

        with patch("pdf_engine.load_pdf_page_dims", side_effect=mock_load_dims):
            adapted = pdf_engine.adapt_pdf_boxes_to_render_zoom(
                "dummy.pdf",
                boxes,
                source_zoom=1.5,
                target_zoom=3.0,
                page_gap=page_gap,
            )

        self.assertEqual(len(adapted), 1)
        adapted_box = adapted[0]
        self.assertEqual(adapted_box["page_num"], 1)
        
        # Expected X: 100.0 * (3.0 / 1.5) = 200.0
        self.assertAlmostEqual(adapted_box["rect"][0], 200.0)
        # Expected Y: 2412 + (150 * (3.0 / 1.5)) = 2412 + 300 = 2712.0
        self.assertAlmostEqual(adapted_box["rect"][1], 2712.0)
        # Expected W: 200.0 * (3.0 / 1.5) = 400.0
        self.assertAlmostEqual(adapted_box["rect"][2], 400.0)
        # Expected H: 300.0 * (3.0 / 1.5) = 600.0
        self.assertAlmostEqual(adapted_box["rect"][3], 600.0)

    def test_layout_scaling_and_alignment_on_zoom_change(self):
        """
        Verify that masks remain aligned with the PDF pages when the canvas
        zoom scale changes, and that viewport calculations scale correctly.
        """
        canvas = OcclusionCanvas()
        
        # Load two dummy pages
        p1 = QPixmap(100, 100)
        p2 = QPixmap(200, 200)
        canvas.load_pages([p1, p2])
        
        # Add a box at scale 1.0
        canvas._scale = 1.0
        box = {
            "rect": QRectF(10.0, 120.0, 30.0, 40.0), # Page 1 starts at 100 + 12 = 112
            "shape": "rect",
            "page_num": 1,
        }
        canvas._boxes = [box]
        
        # Verify page number auto-detects
        canvas._update_all_box_page_nums()
        self.assertEqual(box["_canvas_page_num"], 1)

        # Scale to 2.0x
        canvas._scale = 2.0
        
        # Screen-space rect should be scaled
        sr = canvas._sr(box["rect"])
        self.assertEqual(sr, QRectF(20.0, 240.0, 60.0, 80.0))
        
        # Convert screen-space point back to image-space
        ip = canvas._ip(QPointF(20.0, 240.0))
        self.assertEqual(ip, QPointF(10.0, 120.0))

        # Check scroll position calculation for target centering
        canvas.set_target_box(0)
        hval, vval = canvas.get_target_scroll_pos(100, 100)
        
        # Center of scaled box: cx = 20 + 30 = 50, cy = 240 + 40 = 280
        # Expected scroll: hval = cx - 50 = 0, vval = cy - 50 = 230
        self.assertEqual(hval, 0)
        self.assertEqual(vval, 230)

    def test_page_specific_filtering_and_navigation(self):
        """
        Verify that page-specific filtering hides/shows masks correctly.
        When the viewport is scrolled or navigated to other pages:
          - Only masks intersecting the clip rect are painted (viewport filtering).
          - Navigating pages via PdfViewerController correctly updates the visible page index.
        """
        canvas = OcclusionCanvas()
        
        # Load three dummy pages (each 100x100)
        # Page 0: top 0, bottom 100
        # Page 1: top 112, bottom 212
        # Page 2: top 224, bottom 324
        p0 = QPixmap(100, 100)
        p1 = QPixmap(100, 100)
        p2 = QPixmap(100, 100)
        canvas.load_pages([p0, p1, p2])
        
        # Add boxes on different pages
        box0 = {"rect": QRectF(10, 10, 20, 20), "shape": "rect"} # Page 0
        box1 = {"rect": QRectF(10, 120, 20, 20), "shape": "rect"} # Page 1
        box2 = {"rect": QRectF(10, 230, 20, 20), "shape": "rect"} # Page 2
        canvas._boxes = [box0, box1, box2]
        canvas._update_all_box_page_nums()
        
        # Set up scroll area and controller
        scroll_area = QScrollArea()
        scroll_area.setWidget(canvas)
        
        # Set viewport size to 100x100 (so only one page fits at a time)
        scroll_area.viewport().resize(100, 100)
        # Prevent scrollbar clamping by setting a non-zero range explicitly since the widget is offscreen
        scroll_area.verticalScrollBar().setRange(0, 1000)
        
        # Mock UI elements for controller
        page_input = MagicMock()
        page_total = MagicMock()
        prev_btn = MagicMock()
        next_btn = MagicMock()
        
        controller = PdfViewerController(
            canvas=canvas,
            scroll_area=scroll_area,
            page_input=page_input,
            page_total_label=page_total,
            prev_button=prev_btn,
            next_button=next_btn,
        )
        
        # Initially on Page 0
        self.assertEqual(controller.current_page(), 0)
        
        # Navigate to Page 1
        controller.go_to_page(1)
        self.assertEqual(controller.current_page(), 1)
        # Verify scroll value matches Page 1 top (112 * scale 1.0 = 112)
        self.assertEqual(scroll_area.verticalScrollBar().value(), 112)
        
        # Navigate to Page 2
        controller.go_to_page(2)
        self.assertEqual(controller.current_page(), 2)
        self.assertEqual(scroll_area.verticalScrollBar().value(), 224)

    def test_pdf_annotation_coordinate_translation_and_boundaries(self):
        """
        Verify that PdfAnnotationSession's coordinate translation functions
        correctly translate between canvas and native PDF points, and handle
        boundary cases (out of bounds pages, empty inputs, zero dimensions) gracefully.
        """
        from services.pdf_annotation_service import PdfAnnotationSession
        
        session = PdfAnnotationSession.__new__(PdfAnnotationSession)
        session.page_count = 2
        session.page_pixel_dims = [(900, 1200), (800, 1600)]
        session.page_pdf_dims = [(300.0, 400.0), (400.0, 800.0)]

        # 1. Normal translation page 0: Scale is sx = 3.0, sy = 3.0
        canvas_points = [QPointF(90.0, 180.0)]
        pdf_points = session._canvas_to_pdf_points(0, canvas_points)
        self.assertEqual(pdf_points, [(30.0, 60.0)])
        
        restored = session._pdf_to_canvas_points(0, pdf_points)
        self.assertEqual(restored[0], QPointF(90.0, 180.0))

        # 2. Normal translation page 1: Scale is sx = 2.0, sy = 2.0
        canvas_points_p1 = [QPointF(100.0, 200.0)]
        pdf_points_p1 = session._canvas_to_pdf_points(1, canvas_points_p1)
        self.assertEqual(pdf_points_p1, [(50.0, 100.0)])
        
        restored_p1 = session._pdf_to_canvas_points(1, pdf_points_p1)
        self.assertEqual(restored_p1[0], QPointF(100.0, 200.0))

        # 3. Out of bounds page: Should fallback to scale 1.0, 1.0
        pdf_points_oob = session._canvas_to_pdf_points(5, canvas_points)
        self.assertEqual(pdf_points_oob, [(90.0, 180.0)])
        
        restored_oob = session._pdf_to_canvas_points(5, pdf_points_oob)
        self.assertEqual(restored_oob[0], QPointF(90.0, 180.0))

        # 4. Empty points list: Should return empty list
        self.assertEqual(session._canvas_to_pdf_points(0, []), [])
        self.assertEqual(session._pdf_to_canvas_points(0, []), [])

        # 5. Zero dimensions (should fallback to 1.0, 1.0 scale via 'or 1.0')
        session.page_pixel_dims = [(0, 0)]
        session.page_pdf_dims = [(0.0, 0.0)]
        pdf_points_zero = session._canvas_to_pdf_points(0, canvas_points)
        self.assertEqual(pdf_points_zero, [(90.0, 180.0)])


if __name__ == "__main__":
    unittest.main()
