# -*- coding: utf-8 -*-
import sys
import os
import unittest
from PyQt5.QtWidgets import QApplication
from ui.import_cards_dialog import parse_delimited_text, build_text_card, ImportCardsDialog
from data_manager import store, deck_history

app = QApplication.instance() or QApplication(sys.argv)

class TestImportCards(unittest.TestCase):
    def setUp(self):
        deck_history._undo_stack.clear()
        deck_history._redo_stack.clear()

    def test_parse_simple_comma_separated_text(self):
        text = """What is the capital of France?, Paris
What is the boiling point of water?, 100°C
Who wrote Hamlet?, William Shakespeare"""
        cards = parse_delimited_text(text, delimiter=",")
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[0]["question"], "What is the capital of France?")
        self.assertEqual(cards[0]["answer"], "Paris")
        self.assertEqual(cards[1]["question"], "What is the boiling point of water?")
        self.assertEqual(cards[1]["answer"], "100°C")
        self.assertEqual(cards[2]["question"], "Who wrote Hamlet?")
        self.assertEqual(cards[2]["answer"], "William Shakespeare")

    def test_parse_quoted_text_with_internal_commas(self):
        text = """"Who discovered gravity?, and in what year?", Sir Isaac Newton, 1687
"Line 1, part A", "Line 1, part B", Notes here"""
        cards = parse_delimited_text(text, delimiter=",")
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["question"], "Who discovered gravity?, and in what year?")
        self.assertEqual(cards[0]["answer"], "Sir Isaac Newton")
        self.assertEqual(cards[0]["notes"], "1687")
        self.assertEqual(cards[1]["question"], "Line 1, part A")
        self.assertEqual(cards[1]["answer"], "Line 1, part B")
        self.assertEqual(cards[1]["notes"], "Notes here")

    def test_parse_tab_and_semicolon_delimiters(self):
        tsv_text = "Prompt 1\tAnswer 1\nPrompt 2\tAnswer 2"
        cards_tsv = parse_delimited_text(tsv_text, delimiter="\t")
        self.assertEqual(len(cards_tsv), 2)
        self.assertEqual(cards_tsv[0]["question"], "Prompt 1")
        self.assertEqual(cards_tsv[0]["answer"], "Answer 1")

        semi_text = "Prompt A; Answer A\nPrompt B; Answer B"
        cards_semi = parse_delimited_text(semi_text, delimiter=";")
        self.assertEqual(len(cards_semi), 2)
        self.assertEqual(cards_semi[0]["question"], "Prompt A")
        self.assertEqual(cards_semi[0]["answer"], "Answer A")

    def test_skip_header_row(self):
        text = """Front,Back,Notes
Question 1,Answer 1,Note 1
Question 2,Answer 2,Note 2"""
        cards = parse_delimited_text(text, delimiter=",", has_header=True)
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["question"], "Question 1")
        self.assertEqual(cards[1]["question"], "Question 2")

    def test_build_text_card_sm2_initialization(self):
        card = build_text_card(
            question="What is Python?",
            answer="A high-level programming language.",
            notes="Created by Guido van Rossum",
            tags=["programming"]
        )
        self.assertEqual(card["card_type"], "text")
        self.assertEqual(card["question"], "What is Python?")
        self.assertEqual(card["answer"], "A high-level programming language.")
        self.assertEqual(card["notes"], "Created by Guido van Rossum")
        self.assertEqual(card["tags"], ["programming"])
        self.assertEqual(card["sched_state"], "new")
        self.assertEqual(card["reviews"], 0)
        self.assertIsNotNone(card["_id"])

    def test_dialog_import_as_new_deck(self):
        data = {"decks": []}
        dlg = ImportCardsDialog(data=data)
        raw_text = "Card 1 Front, Card 1 Back\nCard 2 Front, Card 2 Back"
        dlg.txt_paste.setPlainText(raw_text)
        dlg._reparse_and_preview()

        self.assertEqual(len(dlg._parsed_rows), 2)
        self.assertEqual(dlg.table_preview.rowCount(), 2)

        dlg.rb_new_deck.setChecked(True)
        dlg.inp_new_deck_name.setText("Physics 101")
        dlg._do_import()

        self.assertEqual(len(data["decks"]), 1)
        new_deck = data["decks"][0]
        self.assertEqual(new_deck["name"], "Physics 101")
        self.assertEqual(len(new_deck["cards"]), 2)
        self.assertEqual(new_deck["cards"][0]["question"], "Card 1 Front")
        self.assertEqual(new_deck["cards"][0]["answer"], "Card 1 Back")
        self.assertEqual(new_deck["cards"][0]["card_type"], "text")

        res = dlg.get_result()
        self.assertEqual(res["count"], 2)
        self.assertTrue(res["is_new_deck"])
        self.assertEqual(res["target_deck_id"], new_deck["_id"])

    def test_dialog_import_into_existing_deck(self):
        existing_deck = {
            "_id": 10,
            "name": "Existing Biology Deck",
            "cards": [],
            "children": [],
            "expanded": False
        }
        data = {"decks": [existing_deck]}
        dlg = ImportCardsDialog(data=data, current_deck=existing_deck)
        dlg.txt_paste.setPlainText("Mitochondria, Powerhouse of the cell\nRibosome, Protein synthesis")
        dlg._reparse_and_preview()

        dlg.rb_existing_deck.setChecked(True)
        dlg._on_dest_mode_changed()
        dlg._do_import()

        self.assertEqual(len(existing_deck["cards"]), 2)
        self.assertEqual(existing_deck["cards"][0]["question"], "Mitochondria")
        self.assertEqual(existing_deck["cards"][0]["answer"], "Powerhouse of the cell")

        res = dlg.get_result()
        self.assertEqual(res["count"], 2)
        self.assertFalse(res["is_new_deck"])
        self.assertEqual(res["target_deck_id"], 10)

    def test_duplicate_detection_and_auto_skip(self):
        existing_card = build_text_card("Abundant", "Existing in large quantities")
        vocab_deck = {
            "_id": 1,
            "name": "Vocabulary",
            "cards": [existing_card],
            "children": [],
            "expanded": False
        }
        data = {"decks": [vocab_deck]}
        dlg = ImportCardsDialog(data=data, current_deck=vocab_deck)
        
        # Paste 1 existing word ('abundant' case-insensitive) and 1 new word ('ephemeral')
        raw_text = "abundant, Plentiful\nEphemeral, Lasting a short time"
        dlg.txt_paste.setPlainText(raw_text)
        dlg._reparse_and_preview()

        # Check that 1 is duplicate, 1 is new
        self.assertEqual(len(dlg._parsed_rows), 2)
        self.assertTrue(dlg._parsed_rows[0]["is_duplicate"])
        self.assertFalse(dlg._parsed_rows[1]["is_duplicate"])

        # Auto-skip duplicates is ON by default
        self.assertTrue(dlg.chk_skip_duplicates.isChecked())
        dlg.rb_existing_deck.setChecked(True)
        dlg._on_dest_mode_changed()
        dlg._do_import()

        # Only 'Ephemeral' should be added (total cards in deck becomes 2: original + 1 new)
        self.assertEqual(len(vocab_deck["cards"]), 2)
        self.assertEqual(vocab_deck["cards"][1]["question"], "Ephemeral")
        
        res = dlg.get_result()
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["skipped_duplicates"], 1)

    def test_internal_batch_duplicate_detection(self):
        data = {"decks": []}
        dlg = ImportCardsDialog(data=data)
        
        # Paste same word twice in the same batch
        raw_text = "Ubiquitous, Found everywhere\nUbiquitous, Present everywhere\nSerendipity, Pleasant surprise"
        dlg.txt_paste.setPlainText(raw_text)
        dlg._reparse_and_preview()

        self.assertEqual(len(dlg._parsed_rows), 3)
        self.assertFalse(dlg._parsed_rows[0]["is_duplicate"])
        self.assertTrue(dlg._parsed_rows[1]["is_duplicate"]) # 2nd occurrence in batch marked dup
        self.assertFalse(dlg._parsed_rows[2]["is_duplicate"])

        dlg.rb_new_deck.setChecked(True)
        dlg.inp_new_deck_name.setText("Gre Vocab")
        dlg._do_import()

        new_deck = data["decks"][0]
        self.assertEqual(len(new_deck["cards"]), 2)
        self.assertEqual(new_deck["cards"][0]["question"], "Ubiquitous")
        self.assertEqual(new_deck["cards"][1]["question"], "Serendipity")

    def test_import_allow_duplicates_when_skip_disabled(self):
        existing_card = build_text_card("Word", "Meaning 1")
        deck = {
            "_id": 1,
            "name": "Vocab",
            "cards": [existing_card],
            "children": [],
            "expanded": False
        }
        data = {"decks": [deck]}
        dlg = ImportCardsDialog(data=data, current_deck=deck)
        dlg.txt_paste.setPlainText("Word, Meaning 2\nNewWord, Meaning 3")
        dlg._reparse_and_preview()

        # Disable skip duplicates
        dlg.chk_skip_duplicates.setChecked(False)
        dlg._reparse_and_preview()

        dlg.rb_existing_deck.setChecked(True)
        dlg._on_dest_mode_changed()
        dlg._do_import()

        # Both cards should be imported
        self.assertEqual(len(deck["cards"]), 3)
        res = dlg.get_result()
        self.assertEqual(res["count"], 2)
        self.assertEqual(res["skipped_duplicates"], 0)

if __name__ == "__main__":
    unittest.main()

