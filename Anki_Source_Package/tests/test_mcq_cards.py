# -*- coding: utf-8 -*-
import unittest
import json
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

app = QApplication.instance() or QApplication([])

from models import Card
from ui.import_cards_dialog import parse_testbook_or_mcq_json, build_mcq_card, ImportCardsDialog
from ui.mcq_review_widget import MCQReviewWidget, OptionButton
from ui.review_screen import ReviewScreen
import sm2_engine

SAMPLE_DICT = {
    'platform': 'testbook.com',
    'section': 'General Awareness',
    'total_questions': 2,
    'questions': [
        {
            'question_no': '1',
            'section': 'General Awareness',
            'question': 'Arrange the following classical dances:\n1. Bharatanatyam\n2. Mohiniyattam\n3. Kathak\n4. Manipuri',
            'options': [
                {'label': 'A', 'text': '1 - 3 - 2 - 4', 'is_correct': False},
                {'label': 'B', 'text': '1 - 2 - 4 - 3', 'is_correct': False},
                {'label': 'C', 'text': '1 - 3 - 4 - 2', 'is_correct': True},
                {'label': 'D', 'text': '1 - 4 - 3 - 2', 'is_correct': False}
            ],
            'correct_option': {'label': 'C', 'text': '1 - 3 - 4 - 2'},
            'percent_answered_correctly': '22%',
            'marks': '-0.5',
            'solution': {
                'statement': 'The correct answer is 1 - 3 - 4 - 2.',
                'key_points': [
                    'Bharatanatyam is one of the oldest classical dances.',
                    'Kathak originated with traveling bards.'
                ],
                'additional_info': [
                    'Bharatanatyam: Tamil Nadu temples.',
                    'Kathak: North Indian dance.'
                ],
                'important_points': [
                    'Chronological Order: Bharatanatyam -> Kathak -> Manipuri -> Mohiniyattam.'
                ]
            }
        },
        {
            'question_no': '2',
            'section': 'General Awareness',
            'question': 'Which of the following pairs is correctly matched with roof shape?',
            'options': [
                {'label': 'A', 'text': 'Latina — rectangular roof', 'is_correct': False},
                {'label': 'B', 'text': 'Phamsana — slabs rising to a point', 'is_correct': True},
                {'label': 'C', 'text': 'Valabhi — tall curving sharply', 'is_correct': False},
                {'label': 'D', 'text': 'Latina — low and broad', 'is_correct': False}
            ],
            'correct_option': {'label': 'B', 'text': 'Phamsana — slabs rising to a point'},
            'percent_answered_correctly': '9%',
            'solution': {
                'statement': 'The correct answer is Phamsana.',
                'key_points': ['Phamsana roofs rise in a straight slope.']
            }
        }
    ]
}

SAMPLE_TESTBOOK_JSON = json.dumps(SAMPLE_DICT)

class TestMCQCards(unittest.TestCase):
    def test_testbook_json_parser(self):
        cards, suggested_deck = parse_testbook_or_mcq_json(SAMPLE_TESTBOOK_JSON)
        self.assertEqual(len(cards), 2)
        self.assertEqual(suggested_deck, 'Testbook::General Awareness')

        c1 = cards[0]
        self.assertTrue(c1['is_mcq'])
        self.assertIn('Arrange the following classical dances', c1['question'])
        self.assertEqual(len(c1['options']), 4)
        self.assertEqual(c1['correct_option']['label'], 'C')
        self.assertEqual(c1['percent_answered_correctly'], '22%')
        self.assertEqual(len(c1['solution_data']['key_points']), 2)
        self.assertEqual(len(c1['solution_data']['additional_info']), 2)
        self.assertEqual(len(c1['solution_data']['important_points']), 1)
        self.assertEqual(c1['exam_meta']['marks'], '-0.5')

        c2 = cards[1]
        self.assertTrue(c2['is_mcq'])
        self.assertEqual(c2['correct_option']['label'], 'B')
        self.assertEqual(c2['percent_answered_correctly'], '9%')

    def test_build_mcq_card_sm2(self):
        cards, _ = parse_testbook_or_mcq_json(SAMPLE_TESTBOOK_JSON)
        c_dict = cards[0]
        card = build_mcq_card(
            question=c_dict['question'],
            options=c_dict['options'],
            correct_option=c_dict['correct_option'],
            solution_data=c_dict['solution_data'],
            percent_answered_correctly=c_dict['percent_answered_correctly'],
            exam_meta=c_dict['exam_meta'],
            notes=c_dict['notes'],
            trap_note=c_dict['trap_note'],
            context_anchor=c_dict['context_anchor'],
            chain_order=c_dict['chain_order']
        )

        self.assertEqual(card['card_type'], 'mcq')
        self.assertEqual(len(card['options']), 4)
        self.assertIn('sm2_interval', card)
        self.assertIn('sm2_ease', card)
        self.assertIn('sm2_due', card)
        self.assertIn('sched_state', card)
        self.assertEqual(card['sm2_ease'], 2.5)

    def test_card_model_dataclass(self):
        c = Card(
            _id='test-123',
            card_type='mcq',
            title='Dance Chronology',
            question='Which dance is oldest?',
            options=[{'label': 'A', 'text': 'Bharatanatyam', 'is_correct': True}],
            correct_option={'label': 'A', 'text': 'Bharatanatyam'},
            solution_data={'statement': 'Bharatanatyam is oldest.'},
            percent_answered_correctly='80%'
        )
        d = c.to_dict()
        self.assertEqual(d['card_type'], 'mcq')
        self.assertEqual(len(d['options']), 1)
        self.assertEqual(d['percent_answered_correctly'], '80%')

        restored = Card.from_dict(d)
        self.assertEqual(restored.card_type, 'mcq')
        self.assertEqual(restored.percent_answered_correctly, '80%')
        self.assertEqual(restored.options[0]['label'], 'A')

    def test_option_button_widget(self):
        btn = OptionButton('A', 'Kathak')
        self.assertEqual(btn.label, 'A')
        self.assertEqual(btn.text_content, 'Kathak')

        btn.apply_incorrect_style()
        self.assertIn('Your Attempt', btn.status_pill.text())

        btn2 = OptionButton('B', 'Bharatanatyam')
        btn2.apply_correct_style('22% answered correctly')
        self.assertIn('22%', btn2.status_pill.text())

    def test_mcq_review_widget_lifecycle(self):
        widget = MCQReviewWidget()
        cards, _ = parse_testbook_or_mcq_json(SAMPLE_TESTBOOK_JSON)
        card = build_mcq_card(
            question=cards[0]['question'],
            options=cards[0]['options'],
            correct_option=cards[0]['correct_option'],
            solution_data=cards[0]['solution_data'],
            percent_answered_correctly=cards[0]['percent_answered_correctly'],
            exam_meta=cards[0]['exam_meta']
        )

        widget.load_card(card)
        self.assertFalse(widget.is_revealed)
        self.assertEqual(len(widget._option_buttons), 4)
        self.assertTrue(widget.solution_container.isHidden())

        selected_signal = []
        widget.option_selected.connect(lambda lbl, corr: selected_signal.append((lbl, corr)))
        
        widget.select_option('C')
        self.assertTrue(widget.is_revealed)
        self.assertEqual(widget.selected_label, 'C')
        self.assertFalse(widget.solution_container.isHidden())
        self.assertEqual(len(selected_signal), 1)
        self.assertEqual(selected_signal[0], ('C', True))

    def test_import_cards_dialog_mcq_flow(self):
        data = {'decks': []}
        dlg = ImportCardsDialog(data=data)
        
        dlg.tabs.setCurrentIndex(3)
        dlg.txt_mcq_json.setPlainText(SAMPLE_TESTBOOK_JSON)
        dlg._reparse_and_preview()

        self.assertEqual(len(dlg._parsed_rows), 2)
        self.assertTrue(dlg._parsed_rows[0]['is_mcq'])
        self.assertEqual(dlg.table_preview.rowCount(), 2)

        dlg._do_import()
        
        # Testbook deck hierarchy was created
        self.assertGreaterEqual(len(data['decks']), 1)
        # Find all cards across created decks
        all_cards = []
        def _collect(decks):
            for d in decks:
                all_cards.extend(d.get('cards', []))
                _collect(d.get('children', []))
        _collect(data['decks'])

        self.assertEqual(len(all_cards), 2)
        imported_c1 = all_cards[0]
        self.assertEqual(imported_c1['card_type'], 'mcq')
        self.assertEqual(len(imported_c1['options']), 4)
        self.assertEqual(imported_c1['percent_answered_correctly'], '22%')

    def test_font_zoom_controls(self):
        widget = MCQReviewWidget()
        cards, _ = parse_testbook_or_mcq_json(SAMPLE_TESTBOOK_JSON)
        card = build_mcq_card(
            question=cards[0]['question'],
            options=cards[0]['options'],
            correct_option=cards[0]['correct_option'],
            solution_data=cards[0]['solution_data']
        )
        widget.load_card(card)
        
        # Initial zoom
        widget.zoom_reset()
        self.assertEqual(widget._zoom_factor, 1.0)
        self.assertEqual(widget.btn_font_reset.text(), '100%')

        # Zoom in
        widget.zoom_in()
        self.assertAlmostEqual(widget._zoom_factor, 1.1)
        self.assertEqual(widget.btn_font_reset.text(), '110%')

        # Zoom out
        widget.zoom_out()
        widget.zoom_out()
        self.assertAlmostEqual(widget._zoom_factor, 0.9)
        self.assertEqual(widget.btn_font_reset.text(), '90%')

        # Reset
        widget.zoom_reset()
        self.assertEqual(widget._zoom_factor, 1.0)
        self.assertEqual(widget.btn_font_reset.text(), '100%')

    def test_import_into_user_selected_existing_deck(self):
        # User has an existing mock test deck: "SSC CGL 2025 (HELD ON: 12 SEPT, 2025 SHIFT 1)"
        mock_deck = {
            '_id': 'mock-deck-1',
            'name': 'SSC CGL 2025 (HELD ON: 12 SEPT, 2025 SHIFT 1)',
            'cards': [],
            'children': [],
            'expanded': False
        }
        data = {'decks': [mock_deck]}
        
        dlg = ImportCardsDialog(data=data, current_deck=mock_deck)
        self.assertTrue(dlg.rb_existing_deck.isChecked())
        
        dlg.tabs.setCurrentIndex(3)
        dlg.txt_mcq_json.setPlainText(SAMPLE_TESTBOOK_JSON)
        dlg._reparse_and_preview()

        # Ensure suggested deck did NOT override the radio button or selected existing deck
        self.assertTrue(dlg.rb_existing_deck.isChecked())
        
        dlg._do_import()

        # Check that cards went DIRECTLY into the user's selected deck
        self.assertEqual(len(mock_deck['cards']), 2)
        self.assertEqual(len(data['decks']), 1)
        self.assertEqual(data['decks'][0]['name'], 'SSC CGL 2025 (HELD ON: 12 SEPT, 2025 SHIFT 1)')


if __name__ == '__main__':
    unittest.main()
