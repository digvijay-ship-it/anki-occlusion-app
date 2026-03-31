import unittest
import sys
import uuid
from datetime import datetime, timedelta
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QPointF, QRectF

# Import the functions and classes from your main app script
# Make sure your original file is named 'anki_occlusion.py'
import anki_occlusion_v17 as ao

# Create a global QApplication instance needed for testing PyQt widgets
app = QApplication(sys.argv)

class TestSM2Engine(unittest.TestCase):
    def setUp(self):
        # Create a fresh, empty card for each test
        self.card = {}

    def test_sched_init(self):
        """Test that a new card gets the correct default scheduling fields."""
        ao.sched_init(self.card)
        self.assertEqual(self.card["sched_state"], "new")
        self.assertEqual(self.card["sched_step"], 0)
        self.assertEqual(self.card["sm2_interval"], 1)
        self.assertEqual(self.card["sm2_ease"], 2.5)

    def test_learning_progression_good(self):
        """Test that pressing 'Good' (4) advances learning steps and graduates."""
        # Press 1: Enters learning, step 1
        ao.sched_update(self.card, 4)
        self.assertEqual(self.card["sched_state"], "learning")
        self.assertEqual(self.card["sched_step"], 1)
        
        # Fast forward through remaining learning steps (assuming defaults: 1, 6, 10, 15)
        ao.sched_update(self.card, 4) # Step 2
        ao.sched_update(self.card, 4) # Step 3
        ao.sched_update(self.card, 4) # Graduates
        
        self.assertEqual(self.card["sched_state"], "review")
        self.assertEqual(self.card["sm2_interval"], ao.GRADUATING_IV)

    def test_easy_graduates_immediately(self):
        """Test that pressing 'Easy' (5) on a new card skips learning steps."""
        ao.sched_update(self.card, 5)
        self.assertEqual(self.card["sched_state"], "review")
        self.assertEqual(self.card["sm2_interval"], ao.EASY_IV)

    def test_again_resets_learning(self):
        """Test that pressing 'Again' (1) resets the learning step."""
        ao.sched_update(self.card, 4) # Moves to step 1
        ao.sched_update(self.card, 1) # Fails, back to step 0
        self.assertEqual(self.card["sched_state"], "learning")
        self.assertEqual(self.card["sched_step"], 0)


class TestDeckTreeHelpers(unittest.TestCase):
    def setUp(self):
        self.data = {
            "decks": [
                {
                    "_id": 1,
                    "name": "Biology",
                    "children": [
                        {"_id": 2, "name": "Cells", "children": []}
                    ]
                },
                {"_id": 3, "name": "History", "children": []}
            ]
        }

    def test_find_deck_by_id(self):
        """Test finding decks at various nesting levels."""
        decks = self.data["decks"]
        self.assertEqual(ao.find_deck_by_id(1, decks)["name"], "Biology")
        self.assertEqual(ao.find_deck_by_id(2, decks)["name"], "Cells")
        self.assertIsNone(ao.find_deck_by_id(99, decks))

    def test_next_deck_id(self):
        """Test that the next ID is always max(id) + 1."""
        next_id = ao.next_deck_id(self.data)
        self.assertEqual(next_id, 4)


class TestMathHelpers(unittest.TestCase):
    def test_point_in_rotated_box(self):
        """Test hit-detection for rotated rectangles."""
        cx, cy, w, h = 0, 0, 10, 10
        # Point inside unrotated box
        self.assertTrue(ao._point_in_rotated_box(0, 0, cx, cy, w, h, 0))
        self.assertTrue(ao._point_in_rotated_box(4, 4, cx, cy, w, h, 0))
        self.assertFalse(ao._point_in_rotated_box(6, 6, cx, cy, w, h, 0))

        # Test with 45 degree rotation
        # A point at (0, 6) is outside an unrotated 10x10 box, but inside if rotated 45 deg
        self.assertTrue(ao._point_in_rotated_box(0, 6, cx, cy, w, h, 45))


class TestGUIComponents(unittest.TestCase):
    """
    Basic initialization tests to ensure the UI components 
    build without throwing syntax or import errors.
    """
    def test_occlusion_canvas_init(self):
        canvas = ao.OcclusionCanvas()
        self.assertIsNotNone(canvas)
        self.assertEqual(canvas._mode, "edit")

    def test_toolbar_init(self):
        toolbar = ao.ToolBar()
        self.assertEqual(toolbar.width(), 50)
        
    def test_box_id_generation(self):
        # Test UUID generator for boxes
        box_id = ao.new_box_id()
        self.assertTrue(isinstance(box_id, str))
        self.assertTrue(len(box_id) > 10)

if __name__ == '__main__':
    unittest.main()