import unittest
import sys
from PyQt5.QtWidgets import QApplication, QMessageBox
from unittest.mock import patch, MagicMock
from ui.card_browser_dialog import CardBrowserDialog, _clean_text_preview, _extract_plain_text, format_cards_as_csv
from ui.import_cards_dialog import parse_delimited_text


class TestCardBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.mock_cards = [
            {
                "_id": 101,
                "card_type": "text",
                "title": "Yakshagana",
                "question": "Yakshagana Dance",
                "answer": "Karnataka traditional dance form",
                "notes": "Coastal Karnataka",
                "tags": ["folk", "art"],
                "reviews": 2,
                "sched_state": "review"
            },
            {
                "_id": 102,
                "card_type": "text",
                "title": "Bardo Chham",
                "question": "<b>Bardo Chham</b>",
                "answer": "Arunachal Pradesh ritual mask dance",
                "notes": "Sherdukpen community",
                "tags": ["dance"],
                "reviews": 0,
                "sched_state": "new"
            },
            {
                "_id": 103,
                "card_type": "pdf",
                "title": "Indian History Lecture 1",
                "pdf_path": "C:/docs/history.pdf",
                "boxes": [{"box_id": "b1"}, {"box_id": "b2"}],
                "reviews": 1,
                "sched_state": "review"
            }
        ]
        self.mock_deck = {
            "name": "Culture & Heritage",
            "cards": list(self.mock_cards)
        }
        self.mock_data = {
            "decks": [self.mock_deck]
        }

    def test_clean_text_preview(self):
        html_text = "<!DOCTYPE HTML><html><body><p>Hello <b>World</b>!</p></body></html>"
        self.assertEqual(_clean_text_preview(html_text), "Hello World !")
        
        long_text = "A" * 150
        preview = _clean_text_preview(long_text, max_len=50)
        self.assertTrue(len(preview) <= 53)
        self.assertTrue(preview.endswith("..."))

    def test_extract_plain_text(self):
        self.assertEqual(_extract_plain_text("<b>Bold Word</b>"), "Bold Word")
        self.assertEqual(_extract_plain_text("<p>Line 1</p><p>Line 2</p>"), "Line 1\nLine 2")
        self.assertEqual(_extract_plain_text("Salt &amp; Pepper &lt;3"), "Salt & Pepper <3")
        self.assertEqual(_extract_plain_text("Simple Word"), "Simple Word")

    def test_format_cards_as_csv(self):
        csv_text = format_cards_as_csv(self.mock_cards, mode="csv")
        lines = csv_text.strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "Yakshagana Dance,Karnataka traditional dance form,Coastal Karnataka")
        self.assertEqual(lines[1], "Bardo Chham,Arunachal Pradesh ritual mask dance,Sherdukpen community")
        self.assertEqual(lines[2], "Indian History Lecture 1")

    def test_format_cards_with_internal_commas_and_quotes(self):
        special_cards = [
            {
                "card_type": "text",
                "question": "Ubiquitous, or everywhere",
                "answer": "Present, appearing, or found everywhere",
                "notes": ""
            }
        ]
        csv_text = format_cards_as_csv(special_cards, mode="csv")
        self.assertEqual(csv_text.strip(), '"Ubiquitous, or everywhere","Present, appearing, or found everywhere"')
        
        # Verify parse_delimited_text correctly reconstructs it
        parsed = parse_delimited_text(csv_text)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["question"], "Ubiquitous, or everywhere")
        self.assertEqual(parsed[0]["answer"], "Present, appearing, or found everywhere")

    def test_format_cards_words_only(self):
        words_text = format_cards_as_csv(self.mock_cards, mode="words_only")
        lines = words_text.strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "Yakshagana Dance")
        self.assertEqual(lines[1], "Bardo Chham")
        self.assertEqual(lines[2], "Indian History Lecture 1")

    def test_copy_cards_to_clipboard_all_when_none_selected(self):
        dlg = CardBrowserDialog(deck=self.mock_deck, data=self.mock_data)
        fake_clipboard = MagicMock()
        with patch("PyQt5.QtWidgets.QApplication.clipboard", return_value=fake_clipboard):
            dlg._copy_cards_to_clipboard(mode="csv", delimiter=",")
            fake_clipboard.setText.assert_called_once()
            called_text = fake_clipboard.setText.call_args[0][0]
            self.assertIn("Yakshagana Dance", called_text)
            self.assertIn("Bardo Chham", called_text)
            self.assertIn("Indian History Lecture 1", called_text)

    def test_copy_cards_to_clipboard_selected_only(self):
        from PyQt5.QtWidgets import QTableWidgetSelectionRange
        dlg = CardBrowserDialog(deck=self.mock_deck, data=self.mock_data)
        dlg.table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 0, 5), True) # Select row 0 only
        
        fake_clipboard = MagicMock()
        with patch("PyQt5.QtWidgets.QApplication.clipboard", return_value=fake_clipboard):
            dlg._copy_cards_to_clipboard(mode="csv", delimiter=",")
            fake_clipboard.setText.assert_called_once()
            called_text = fake_clipboard.setText.call_args[0][0]
            self.assertIn("Yakshagana Dance", called_text)
            self.assertNotIn("Bardo Chham", called_text)
            self.assertNotIn("Indian History Lecture 1", called_text)

    def test_table_population(self):
        dlg = CardBrowserDialog(deck=self.mock_deck, data=self.mock_data)
        self.assertEqual(dlg.table.rowCount(), 3)
        
        # Check Row 0 (Text card)
        self.assertIn("Text", dlg.table.item(0, 1).text())
        self.assertEqual(dlg.table.item(0, 2).text(), "Yakshagana Dance")
        self.assertEqual(dlg.table.item(0, 3).text(), "Karnataka traditional dance form")
        self.assertEqual(dlg.table.item(0, 4).text(), "Culture & Heritage")
        
        # Check Row 1 (HTML stripped)
        self.assertEqual(dlg.table.item(1, 2).text(), "Bardo Chham")
        
        # Check Row 2 (PDF card)
        self.assertIn("PDF", dlg.table.item(2, 1).text())
        self.assertEqual(dlg.table.item(2, 2).text(), "Indian History Lecture 1")
        self.assertEqual(dlg.table.item(2, 3).text(), "2 occlusion mask(s)")

    def test_search_filter(self):
        dlg = CardBrowserDialog(deck=self.mock_deck, data=self.mock_data)
        
        # Filter by "Arunachal"
        dlg.search_input.setText("Arunachal")
        self.assertEqual(dlg.table.rowCount(), 1)
        self.assertEqual(dlg.table.item(0, 2).text(), "Bardo Chham")
        
        # Filter by "PDF"
        dlg.search_input.setText("PDF")
        self.assertEqual(dlg.table.rowCount(), 1)
        self.assertEqual(dlg.table.item(0, 2).text(), "Indian History Lecture 1")
        
        # Clear filter
        dlg.search_input.setText("")
        self.assertEqual(dlg.table.rowCount(), 3)

    @patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes)
    def test_bulk_delete_cards(self, mock_msgbox):
        from PyQt5.QtWidgets import QTableWidgetSelectionRange
        dlg = CardBrowserDialog(deck=self.mock_deck, data=self.mock_data)
        self.assertEqual(dlg.table.rowCount(), 3)
        
        # Select row 0 and row 1 using range selection
        dlg.table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 1, 5), True)
        
        # Delete selected
        dlg._delete_selected_cards()
        
        # Verify deck has only 1 card remaining (History PDF)
        self.assertEqual(len(self.mock_deck["cards"]), 1)
        self.assertEqual(self.mock_deck["cards"][0]["_id"], 103)
        self.assertEqual(dlg.table.rowCount(), 1)

    def test_review_screen_card_manager_integration(self):
        from ui.review_screen import ReviewScreen
        from PyQt5.QtWidgets import QDialog
        cards = [self.mock_cards[0]]
        review_scr = ReviewScreen(cards=cards, data=self.mock_data)
        
        # Verify button exists on review screen
        self.assertTrue(hasattr(review_scr, "_btn_card_manager"))
        self.assertEqual(review_scr._btn_card_manager.text(), "📋 Card Manager")
        
        # Verify action exists in options menu
        self.assertTrue(hasattr(review_scr, "_act_card_manager"))
        self.assertEqual(review_scr._act_card_manager.text(), "📋 Bulk Card Manager")
        self.assertIn(review_scr._act_card_manager, review_scr._menu_options.actions())
        
        # Test triggering _open_card_browser
        with patch.object(CardBrowserDialog, "exec_", return_value=QDialog.Accepted):
            review_scr._open_card_browser()

    def test_edit_text_card_syncs_with_review_screen(self):
        from PyQt5.QtWidgets import QDialog, QTableWidgetSelectionRange
        mock_review = MagicMock()
        mock_review._text_card_cache = {(101, True): "dummy_cached", (101, False): "dummy_cached"}
        mock_review._items = [(self.mock_cards[0], 0, None)]
        
        dlg = CardBrowserDialog(deck=self.mock_deck, data=self.mock_data, review_screen=mock_review)
        dlg.table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 0, 5), True)
        
        mock_editor = MagicMock()
        mock_editor.exec_.return_value = QDialog.Accepted
        mock_editor.get_card.return_value = {
            "_id": 101,
            "card_type": "text",
            "title": "Yakshagana Updated",
            "question": "Yakshagana Dance Updated",
            "answer": "Karnataka traditional dance form updated",
            "notes": "Coastal Karnataka",
            "tags": ["folk", "art"],
            "reviews": 2,
            "sched_state": "review"
        }
        
        with patch("ui.text_card_editor_dialog.TextCardEditorDialog", return_value=mock_editor):
            dlg._edit_selected_card()
            
        # Verify cache was cleared and _load_item was called on review screen
        self.assertNotIn((101, True), mock_review._text_card_cache)
        self.assertNotIn((101, False), mock_review._text_card_cache)
        mock_review._load_item.assert_called_once()
        self.assertEqual(self.mock_deck["cards"][0]["question"], "Yakshagana Dance Updated")


if __name__ == "__main__":
    unittest.main()


