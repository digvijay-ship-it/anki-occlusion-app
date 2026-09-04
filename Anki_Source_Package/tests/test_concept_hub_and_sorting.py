import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_manager import import_json_cards
from PyQt5.QtWidgets import QApplication

if not QApplication.instance():
    app = QApplication(sys.argv)

class TestConceptHubAndSorting(unittest.TestCase):
    def setUp(self):
        self.data = {
            "decks": [
                {"_id": 1, "name": "GK", "cards": [], "children": []}
            ]
        }

    def test_auto_chaining_sequential_cards(self):
        items = [
            {
                "deck_name": "GK::Peninsular",
                "context_anchor": "Peninsular Plateau: Definition",
                "question": "Q1",
                "answer": "A1",
                "chain_order": 1
            },
            {
                "deck_name": "GK::Peninsular",
                "context_anchor": "Peninsular Plateau: Boundaries",
                "question": "Q2",
                "answer": "A2",
                "chain_order": 2
            },
            {
                "deck_name": "GK::Peninsular",
                "context_anchor": "Vindhya Range",
                "question": "Q9",
                "answer": "A9",
                "chain_order": 9
            }
        ]
        
        res = import_json_cards(
            self.data, items, dup_policy="skip", default_deck_id=1
        )
        
        self.assertEqual(res["imported"], 3)
        cards = res["created_cards"]
        self.assertEqual(len(cards), 3)
        # Verify all 3 cards share the same parent_chain_id
        chain_ids = {c.get("parent_chain_id") for c in cards}
        self.assertEqual(len(chain_ids), 1)
        self.assertIsNotNone(list(chain_ids)[0])

    def test_sorting_preserves_step_order(self):
        cards = [
            {"_id": "c9", "chain_order": 9, "parent_chain_id": "chain-1", "question": "Q9", "answer": "A9", "card_type": "text"},
            {"_id": "c1", "chain_order": 1, "parent_chain_id": "chain-1", "question": "Q1", "answer": "A1", "card_type": "text"},
            {"_id": "c2", "chain_order": 2, "parent_chain_id": "chain-1", "question": "Q2", "answer": "A2", "card_type": "text"},
        ]
        
        items = [
            (cards[0], 0, {"sm2_due": "2026-08-29"}),
            (cards[1], 0, {"sm2_due": "2026-08-29"}),
            (cards[2], 0, {"sm2_due": "2026-08-29"}),
        ]
        
        item_order_map = {id(item): idx for idx, item in enumerate(items)}
        chain_earliest_due = {"chain-1": "2026-08-29"}
        
        def _sort_key(item):
            card, box_idx, sm2_obj = item
            c_order = int(card.get("chain_order", 0) or 0)
            orig_idx = item_order_map.get(id(item), 0)
            chain_id = card.get("parent_chain_id")
            c_due = chain_earliest_due.get(chain_id, "")
            return (c_due, c_order if c_order > 0 else 999999, orig_idx)
            
        items.sort(key=_sort_key)
        
        # Verify sorted sequence is c1, c2, c9
        sorted_orders = [it[0]["chain_order"] for it in items]
        self.assertEqual(sorted_orders, [1, 2, 9])

    def test_concept_hub_drawer_init(self):
        from ui.review.concept_hub_drawer import ConceptHubDrawer
        from PyQt5.QtWidgets import QWidget
        dummy_parent = QWidget()
        dummy_parent._items = []
        dummy_parent._idx = 0
        drawer = ConceptHubDrawer(dummy_parent, dummy_parent)
        self.assertIsNotNone(drawer)
        self.assertEqual(drawer.objectName(), "concept_hub_drawer")

    def test_concept_hub_drawer_resizing_and_persistence(self):
        from ui.review.concept_hub_drawer import ConceptHubDrawer
        from PyQt5.QtWidgets import QWidget
        from PyQt5.QtCore import Qt, QPoint, QSettings
        from PyQt5.QtGui import QMouseEvent

        settings = QSettings("AnkiOcclusion", "App")
        settings.setValue(ConceptHubDrawer.SETTINGS_WIDTH_KEY, 450)

        dummy_parent = QWidget()
        dummy_parent.resize(1000, 700)
        dummy_parent._items = []
        dummy_parent._idx = 0
        drawer = ConceptHubDrawer(dummy_parent, dummy_parent)
        
        # Test initial width loaded from QSettings
        self.assertEqual(drawer.width(), 450)

        # Test mouse hover near left border sets resize cursor
        event_hover = QMouseEvent(QMouseEvent.MouseMove, QPoint(4, 50), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        drawer.mouseMoveEvent(event_hover)
        self.assertEqual(drawer.cursor().shape(), Qt.SizeHorCursor)

        # Test mouse hover away from left border restores arrow cursor
        event_away = QMouseEvent(QMouseEvent.MouseMove, QPoint(20, 50), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        drawer.mouseMoveEvent(event_away)
        self.assertEqual(drawer.cursor().shape(), Qt.ArrowCursor)

        # Test mouse press on left border initiates resizing
        event_press = QMouseEvent(QMouseEvent.MouseButtonPress, QPoint(4, 50), QPoint(800, 50), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        drawer.mousePressEvent(event_press)
        self.assertTrue(drawer._resizing)
        self.assertEqual(drawer._drag_start_x, 800)

        # Test mouse move dragging 100px to the left increases width to 550
        event_drag = QMouseEvent(QMouseEvent.MouseMove, QPoint(-96, 50), QPoint(700, 50), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        drawer.mouseMoveEvent(event_drag)
        self.assertEqual(drawer.width(), 550)

        # Test mouse release saves new width to QSettings
        event_release = QMouseEvent(QMouseEvent.MouseButtonRelease, QPoint(-96, 50), QPoint(700, 50), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        drawer.mouseReleaseEvent(event_release)
        self.assertFalse(drawer._resizing)
        self.assertEqual(settings.value(ConceptHubDrawer.SETTINGS_WIDTH_KEY, type=int), 550)

    def test_concept_hub_full_question_and_expanded_peek(self):
        from ui.review.concept_hub_drawer import ConceptHubDrawer
        from PyQt5.QtWidgets import QWidget, QSplitter

        long_q = "पालघाट दर्रे के दक्षिण में अनामलाई जंक्शन से निकलने वाली 3 पर्वत शाखाएं कौन सी हैं और इनके बीच क्या अंतर है?"
        card = {
            "_id": "card_test_long",
            "chain_order": 3,
            "context_anchor": "Southern Hills",
            "question": long_q,
            "answer": "1. Anaimalai 2. Palani 3. Cardamom",
            "trap_note": "Do not confuse with Thal Ghat",
            "notes": "Deep geological note about the Western Ghats."
        }

        dummy_parent = QWidget()
        dummy_parent._items = [(card, 0, {})]
        dummy_parent._idx = 0
        drawer = ConceptHubDrawer(dummy_parent, dummy_parent)
        drawer._current_card = card
        drawer._refresh_content()

        # Check splitter and word wrap
        self.assertIsInstance(drawer.splitter, QSplitter)
        self.assertTrue(drawer.list_chain.wordWrap())

        # Verify full question is present without '...' truncation
        self.assertGreater(drawer.list_chain.count(), 0)
        first_item_text = drawer.list_chain.item(0).text()
        self.assertIn(long_q, first_item_text)
        self.assertNotIn("...", first_item_text)

        # Verify Quick-Peek typography rendered
        drawer._render_peek(card)
        html_out = drawer.txt_peek.toHtml()
        self.assertIn("Anaimalai", html_out)
        self.assertIn("Do not confuse with Thal Ghat", html_out)

    def test_concept_hub_larger_font_sizes(self):
        from ui.review.concept_hub_drawer import ConceptHubDrawer
        from PyQt5.QtWidgets import QWidget
        dummy_parent = QWidget()
        dummy_parent._items = []
        dummy_parent._idx = 0
        drawer = ConceptHubDrawer(dummy_parent, dummy_parent)

        # Verify stylesheet has larger fonts (17px for line edit, 16px for tabs, 15px for list)
        ss = drawer.styleSheet()
        self.assertIn("font-size: 17px", ss)
        self.assertIn("font-size: 16px", ss)
        self.assertIn("font-size: 15px", ss)
        self.assertEqual(drawer.DEFAULT_WIDTH, 460)

    def test_isolated_chain_practice_flow(self):
        from ui.review_screen import ReviewScreen
        from PyQt5.QtWidgets import QWidget

        initial_cards = [
            {"_id": "card_main_1", "question": "Gupta Empire Q1", "answer": "A1"},
            {"_id": "card_main_2", "question": "Gupta Empire Q2", "answer": "A2"},
        ]
        isolated_chain = [
            {"_id": "chain_latina_1", "context_anchor": "Nagara Style", "question": "Latina Q39", "answer": "Curvilinear"},
            {"_id": "chain_latina_2", "context_anchor": "Nagara Style", "question": "Latina Q41", "answer": "Shikhara"},
        ]

        dummy_parent = QWidget()
        rev = ReviewScreen(initial_cards, data={"decks": []}, parent=dummy_parent)
        rev._idx = 0

        # Launch isolated chain practice starting at Latina Q39
        rev.start_isolated_chain_practice(isolated_chain, start_card=isolated_chain[0])

        self.assertTrue(rev.is_practice)
        self.assertEqual(len(rev._items), 2)
        self.assertEqual(rev._items[0][0]["_id"], "chain_latina_1")

        # Simulate finishing isolated practice
        rev._finish()

        # Previous review state must be restored
        self.assertFalse(rev.is_practice)
        self.assertEqual(len(rev._items), 2)
        self.assertEqual(rev._items[0][0]["_id"], "card_main_1")
        self.assertEqual(rev._idx, 0)

    def test_concept_hub_recalculate_related_cards_regex(self):
        from ui.review.concept_hub_drawer import ConceptHubDrawer
        from PyQt5.QtWidgets import QWidget

        dummy_parent = QWidget()
        dummy_parent._items = []
        dummy_parent._idx = 0
        drawer = ConceptHubDrawer(dummy_parent, dummy_parent)
        drawer._current_card = {
            "_id": "card_test_regex",
            "question": "Sample Question",
            "tags": ["history", "ancient_india"],
            "related_concepts": ["Nagara (Rekha-Prasad)", "Dravida Style"]
        }
        # Calling _recalculate_related_cards must succeed without NameError on 're'
        drawer._recalculate_related_cards()
        self.assertIsInstance(drawer._related_cards, list)


class TextCardEditorTests(unittest.TestCase):
    def test_text_card_editor_loads_trap_and_notes(self):
        from ui.text_card_editor_dialog import TextCardEditorDialog
        card = {
            "_id": "card_test_1",
            "card_type": "text",
            "title": "Skandagupta",
            "question": "हूणों के भयानक आक्रमण को विफल करने वाला सम्राट कौन था?",
            "answer": "स्कन्दगुप्त",
            "trap_note": "उसने भी 'विक्रमादित्य' की उपाधि ली।",
            "notes": "उसने भी 'क्रमादित्य' की उपाधि ली।",
            "tags": ["history", "gupta"],
        }

        dlg = TextCardEditorDialog(card=dict(card))
        self.assertEqual(dlg.inp_title.text(), "Skandagupta")
        self.assertIn("हूणों", dlg.inp_question.toPlainText())
        self.assertIn("स्कन्दगुप्त", dlg.inp_answer.toPlainText())
        self.assertEqual(dlg.inp_trap.toPlainText(), "उसने भी 'विक्रमादित्य' की उपाधि ली।")
        self.assertEqual(dlg.inp_notes.toPlainText(), "उसने भी 'क्रमादित्य' की उपाधि ली।")
        self.assertEqual(dlg.inp_tags.text(), "history, gupta")

    def test_text_card_editor_saves_trap_and_notes(self):
        from ui.text_card_editor_dialog import TextCardEditorDialog
        card = {
            "_id": "card_test_2",
            "card_type": "text",
            "question": "Sample Question",
            "answer": "Sample Answer",
            "trap_note": "Old Trap",
            "notes": "Old Note",
        }

        dlg = TextCardEditorDialog(card=dict(card))
        dlg.inp_trap.setPlainText("Updated Exam Trap Note")
        dlg.inp_notes.setPlainText("Updated Deep Study Note")
        dlg._save()

        saved = dlg.get_card()
        self.assertEqual(saved.get("trap_note"), "Updated Exam Trap Note")
        self.assertEqual(saved.get("notes"), "Updated Deep Study Note")


if __name__ == "__main__":
    unittest.main()

