import unittest
from models import Card
from ui.text_review_widget import TextReviewWidget

class TestTextCards(unittest.TestCase):
    def test_card_model_text_fields(self):
        # 1. Create a card with text fields
        card = Card(
            _id="text_card_1",
            title="Python Dataclasses",
            card_type="text",
            question="What is a dataclass?",
            answer="A class decorator that automates boilerplate like __init__ and __repr__.",
            notes="Introduced in Python 3.7",
            tags=["python", "oop"]
        )
        
        # 2. Convert to dictionary
        data_dict = card.to_dict()
        self.assertEqual(data_dict["card_type"], "text")
        self.assertEqual(data_dict["question"], "What is a dataclass?")
        self.assertEqual(data_dict["answer"], "A class decorator that automates boilerplate like __init__ and __repr__.")
        
        # 3. Load back from dict
        loaded_card = Card.from_dict(data_dict)
        self.assertEqual(loaded_card.card_type, "text")
        self.assertEqual(loaded_card.question, "What is a dataclass?")
        self.assertEqual(loaded_card.answer, "A class decorator that automates boilerplate like __init__ and __repr__.")
        self.assertEqual(loaded_card.notes, "Introduced in Python 3.7")
        self.assertEqual(loaded_card.tags, ["python", "oop"])

    def test_text_review_widget_load_and_reveal(self):
        import sys
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        
        widget = TextReviewWidget()
        card = {
            "card_type": "text",
            "question": "What is 2+2?",
            "answer": "4",
            "notes": "Basic addition"
        }
        
        widget.load_card(card)
        self.assertFalse(widget.is_revealed)
        self.assertTrue(widget.answer_container.isHidden())
        self.assertIn("What is 2+2?", widget.q_browser.toPlainText())
        
        widget.reveal_answer()
        self.assertTrue(widget.is_revealed)
        self.assertFalse(widget.answer_container.isHidden())
        self.assertIn("4", widget.a_browser.toPlainText())
        self.assertIn("Basic addition", widget.notes_browser.toPlainText())

    def test_text_review_widget_hide_answer_toggle(self):
        import sys
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        
        widget = TextReviewWidget()
        card = {
            "card_type": "text",
            "question": "What is the capital of India?",
            "answer": "New Delhi",
            "trap_note": "Don't confuse with Mumbai",
            "notes": "Established in 1911"
        }
        
        widget.load_card(card)
        self.assertFalse(widget.is_revealed)
        self.assertTrue(widget.answer_container.isHidden())
        
        # 1. Reveal
        widget.reveal_answer()
        self.assertTrue(widget.is_revealed)
        self.assertFalse(widget.answer_container.isHidden())
        self.assertIn("New Delhi", widget.a_browser.toPlainText())
        self.assertIn("Mumbai", widget.trap_browser.toPlainText())
        
        # 2. Hide (toggle back on space)
        widget.hide_answer()
        self.assertFalse(widget.is_revealed)
        self.assertTrue(widget.answer_container.isHidden())
        self.assertEqual(widget.a_browser.toPlainText().strip(), "")
        self.assertEqual(widget.trap_browser.toPlainText().strip(), "")
        self.assertEqual(widget.notes_browser.toPlainText().strip(), "")
        
        # 3. Reveal again
        widget.reveal_answer()
        self.assertTrue(widget.is_revealed)
        self.assertFalse(widget.answer_container.isHidden())
        self.assertIn("New Delhi", widget.a_browser.toPlainText())
        self.assertIn("Mumbai", widget.trap_browser.toPlainText())

    def test_image_scaling_replaces_with_pixel_width(self):
        import sys
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        
        widget = TextReviewWidget()
        html_input = '<p>Check this image:</p><img src="images/test.png" style="max-width: 100%;" />'
        widget._scale_and_load_html(widget.q_browser, html_input, 1200)
        
        # Verify the HTML in the browser has style removed from img tags
        html_output = widget.q_browser.toHtml()
        self.assertNotIn('max-width', html_output)
        self.assertIn('test.png', html_output)

    def test_text_card_zoom_persistence(self):
        import sys
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        
        # Reset and verify default
        TextReviewWidget.save_zoom_factor(1.0)
        widget1 = TextReviewWidget()
        self.assertAlmostEqual(widget1._zoom_factor, 1.0)

        # Zoom in twice (1.0 -> 1.1 -> 1.2)
        widget1.zoom_in()
        widget1.zoom_in()
        self.assertAlmostEqual(widget1._zoom_factor, 1.2)
        self.assertAlmostEqual(TextReviewWidget.get_saved_zoom_factor(), 1.2)

        # Create a new widget (simulating opening another deck or next review session)
        widget2 = TextReviewWidget()
        self.assertAlmostEqual(widget2._zoom_factor, 1.2)

        card = {
            "card_type": "text",
            "question": "What is Python?",
            "answer": "A programming language."
        }
        widget2.load_card(card)
        self.assertAlmostEqual(widget2._zoom_factor, 1.2)

        # Test zoom reset
        widget2.zoom_reset()
        self.assertAlmostEqual(widget2._zoom_factor, 1.0)
        self.assertAlmostEqual(TextReviewWidget.get_saved_zoom_factor(), 1.0)

    def test_wide_image_bounds_to_container_width(self):
        import sys
        import os
        import tempfile
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QImage, QColor
        app = QApplication.instance() or QApplication(sys.argv)
        
        # Create a mock 1920x1080 wide image
        temp_img_path = os.path.join(tempfile.gettempdir(), "test_wide_instrument_banner.png")
        img = QImage(1920, 1080, QImage.Format_RGB32)
        img.fill(QColor("blue"))
        img.save(temp_img_path, "PNG")

        try:
            widget = TextReviewWidget()
            target_container_w = 750
            html_input = f'<p>Musical instruments:</p><img src="{temp_img_path}" />'
            widget._scale_and_load_html(widget.a_browser, html_input, target_container_w)
            
            # Verify the HTML output explicitly sizes the image to <= target_container_w
            html_output = widget.a_browser.toHtml()
            self.assertIn(f'width="{target_container_w}"', html_output)
            self.assertIn('test_wide_instrument_banner.png', html_output)
        finally:
            if os.path.exists(temp_img_path):
                try:
                    os.remove(temp_img_path)
                except Exception:
                    pass

    def test_markdown_image_conversion(self):
        import sys
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        widget = TextReviewWidget()
        md_input = "Look at this: ![diagram](images/diagram.png)"
        card = {
            "card_type": "text",
            "question": md_input,
            "answer": "Answer with ![result](images/result.png)"
        }
        widget.load_card(card)
        widget.reveal_answer()

        # Both question and answer browser should contain <img> tags instead of raw markdown
        self.assertIn('<img', widget.q_browser.toHtml())
        self.assertIn('images/diagram.png', widget.q_browser.toHtml())
        self.assertIn('<img', widget.a_browser.toHtml())
        self.assertIn('images/result.png', widget.a_browser.toHtml())


    def test_text_card_editor_typography_and_80_percent_screen_sizing(self):
        import sys
        from PyQt5.QtWidgets import QApplication
        from ui.text_card_editor_dialog import TextCardEditorDialog

        app = QApplication.instance() or QApplication(sys.argv)
        screen = app.primaryScreen()
        geo = screen.availableGeometry()

        card = {
            "card_type": "text",
            "title": "SPMCIL Presses",
            "question": "Where are SPMCIL presses located?",
            "answer": "Nashik and Dewas",
            "trap_note": "Not owned by RBI",
            "notes": "Security Printing and Minting Corp",
            "tags": ["Economics", "Currency"]
        }

        dlg = TextCardEditorDialog(card=card)
        try:
            # 1. Verify 80% screen dimensions
            expected_w = max(1100, int(geo.width() * 0.80))
            expected_h = max(750, int(geo.height() * 0.80))
            self.assertEqual(dlg.width(), expected_w)
            self.assertEqual(dlg.height(), expected_h)

            # 2. Verify +10px enlarged font sizes across all fields (23px - 26px)
            for widget in (dlg.inp_title, dlg.inp_question, dlg.inp_answer, dlg.inp_trap, dlg.inp_notes, dlg.inp_tags, dlg.chk_formula):
                sz = widget.font().pixelSize() if widget.font().pixelSize() > 0 else widget.font().pointSize()
                self.assertGreaterEqual(sz, 23, f"{widget} font size must be at least 23px")

            # 3. Verify user's trap_note is properly loaded into editor
            self.assertEqual(dlg.inp_trap.toPlainText().strip(), "Not owned by RBI")

            # 4. Verify save preserves trap_note and enlarged content
            dlg.inp_trap.setPlainText("Updated TRAP: Governed by Ministry of Finance")
            dlg._save()
            self.assertEqual(dlg.card.get("trap_note"), "Updated TRAP: Governed by Ministry of Finance")
        finally:
            dlg.close()

    def test_notes_html_span_renders_cleanly_without_raw_code(self):
        import sys
        from PyQt5.QtWidgets import QApplication
        from ui.text_card_editor_dialog import TextCardEditorDialog

        app = QApplication.instance() or QApplication(sys.argv)
        card = {
            "card_type": "text",
            "title": "Appertain Test",
            "question": "Belong as a proper part",
            "answer": "Appertain",
            "notes": "### 🗂️ Options Breakdown\n• **(A) <span style=\"color: #FF79C6;\">Appertain</span>**: <span style=\"color: #67E8F9;\">सम्बन्ध रखना</span> — <span style=\"color: #F1FA8C;\">Be appropriate</span>"
        }
        dlg = TextCardEditorDialog(card=card)
        try:
            visible_text = dlg.inp_notes.toPlainText()
            # Must NOT display raw HTML tags in visible text
            self.assertNotIn("<span", visible_text)
            self.assertIn("Appertain", visible_text)
            self.assertIn("सम्बन्ध रखना", visible_text)
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()


