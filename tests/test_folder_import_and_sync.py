# -*- coding: utf-8 -*-
import sys
import os
import tempfile
import unittest
from PyQt5.QtWidgets import QApplication

from data_manager import (
    scan_and_parse_data_folder,
    sync_deck_from_source_folder,
    get_or_create_deck_by_path,
    store,
    deck_history
)
from sm2_engine import sm2_init
from ui.text_review_widget import TextReviewWidget

app = QApplication.instance() or QApplication(sys.argv)

class TestFolderImportAndSync(unittest.TestCase):
    def setUp(self):
        deck_history._undo_stack.clear()
        deck_history._redo_stack.clear()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scan_and_parse_multiple_csv_files(self):
        root = self.temp_dir.name
        
        # Create file A.csv
        file_a = os.path.join(root, "A.csv")
        with open(file_a, "w", encoding="utf-8") as f:
            f.write('"Abate (V.)","To reduce in severity<br><br><b>💡 Mnemonics:</b><br>ab-ate"\n')
            f.write('"Abbot (N.)","Head of a monastery"\n')

        # Create subfolder and file B.csv
        sub = os.path.join(root, "Section_B")
        os.makedirs(sub, exist_ok=True)
        file_b = os.path.join(sub, "B.csv")
        with open(file_b, "w", encoding="utf-8") as f:
            f.write('"Benevolent (Adj.)","Well-meaning and kindly"\n')

        # Scan with create_subdecks=True
        res = scan_and_parse_data_folder(root, base_deck_path="BlackBook", create_subdecks=True)
        self.assertEqual(res["total_files"], 2)
        self.assertEqual(res["total_cards"], 3)

        deck_paths = [c["deck_path"] for c in res["cards"]]
        self.assertIn("BlackBook::A", deck_paths)
        self.assertIn("BlackBook::Section_B::B", deck_paths)

        # Verify card content
        c_abate = next(c for c in res["cards"] if "Abate" in c["question"])
        self.assertEqual(c_abate["question"], "Abate (V.)")
        self.assertIn("💡 Mnemonics:", c_abate["answer"])

    def test_scan_and_parse_flat_mode_with_tags(self):
        root = self.temp_dir.name
        file_a = os.path.join(root, "A.csv")
        with open(file_a, "w", encoding="utf-8") as f:
            f.write('"Acumen (N.)","Quick insight"\n')

        res = scan_and_parse_data_folder(root, base_deck_path="Vocab Master", create_subdecks=False)
        self.assertEqual(len(res["cards"]), 1)
        self.assertEqual(res["cards"][0]["deck_path"], "Vocab Master")
        self.assertIn("file:A", res["cards"][0]["tags"])

    def test_incremental_sync_preserves_sm2_learning_progress(self):
        root = self.temp_dir.name
        file_a = os.path.join(root, "A.csv")
        with open(file_a, "w", encoding="utf-8") as f:
            f.write('"Abate (V.)","Old definition 1"\n')

        data = {"decks": []}
        deck = {
            "_id": 101,
            "name": "Vocab",
            "source_folder_path": root,
            "cards": [],
            "children": []
        }
        data["decks"].append(deck)

        # 1. Initial sync -> imports 1 card
        res1 = sync_deck_from_source_folder(data, deck=deck)
        self.assertEqual(res1["new_count"], 1)
        self.assertEqual(res1["updated_count"], 0)

        subdeck_a = get_or_create_deck_by_path(data, "Vocab::A", context_deck=deck)
        self.assertEqual(len(subdeck_a["cards"]), 1)
        card_abate = subdeck_a["cards"][0]

        # 2. Simulate learning progress on card_abate (user studied it!)
        card_abate["sm2_interval"] = 20
        card_abate["sm2_repetitions"] = 4
        card_abate["sm2_ease"] = 2.7
        card_abate["sm2_due"] = "2026-09-15"
        card_abate["sched_state"] = "review"
        card_abate["reviews"] = 5
        card_abate["last_quality"] = 4

        # 3. User updates file A.csv: edits Abate definition AND adds a new word "Abhor"
        with open(file_a, "w", encoding="utf-8") as f:
            f.write('"Abate (V.)","Updated definition with mnemonics<br><b>💡 Mnemonics:</b> rebate"\n')
            f.write('"Abhor (V.)","Regard with disgust and hatred"\n')

        # 4. Re-sync deck from folder
        res2 = sync_deck_from_source_folder(data, deck=deck)
        self.assertEqual(res2["new_count"], 1)       # Abhor is newly added
        self.assertEqual(res2["updated_count"], 1)   # Abate definition updated

        # 5. VERIFY: Abate's learning progress is 100% INTACT!
        self.assertEqual(card_abate["sm2_interval"], 20)
        self.assertEqual(card_abate["sm2_repetitions"], 4)
        self.assertEqual(card_abate["sm2_ease"], 2.7)
        self.assertEqual(card_abate["sm2_due"], "2026-09-15")
        self.assertEqual(card_abate["sched_state"], "review")
        self.assertEqual(card_abate["reviews"], 5)
        self.assertEqual(card_abate["last_quality"], 4)
        # Content was updated
        self.assertIn("Updated definition", card_abate["answer"])

        # 6. VERIFY: Abhor is fresh new card
        card_abhor = next(c for c in subdeck_a["cards"] if "Abhor" in c["question"])
        self.assertEqual(card_abhor["sched_state"], "new")
        self.assertEqual(card_abhor["sm2_interval"], 1)
        self.assertEqual(card_abhor["sm2_repetitions"], 0)

    def test_rich_html_and_mnemonic_rendering_in_review_widget(self):
        widget = TextReviewWidget()
        card = {
            "card_type": "text",
            "question": "Abate (V.)",
            "answer": "कम होना — Become less intense<br><br><b>💡 Mnemonics:</b><br>Sounds like ab-ate.<br><br><b>📝 Example:</b><br>Storm abated.",
            "notes": ""
        }
        widget.load_card(card)
        widget.reveal_answer()

        answer_html = widget.a_browser.toHtml()
        # Verify raw escaped tags like &lt;b&gt; are NOT present
        self.assertNotIn("&lt;b&gt;", answer_html)
        self.assertNotIn("&lt;br&gt;", answer_html)
        # Verify HTML rendered content contains the mnemonic and example texts
        self.assertIn("💡 Mnemonics:", answer_html)
        self.assertIn("📝 Example:", answer_html)
        self.assertIn("कम होना", answer_html)

if __name__ == "__main__":
    unittest.main()
