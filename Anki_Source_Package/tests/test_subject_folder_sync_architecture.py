# -*- coding: utf-8 -*-
import sys
import os
import json
import tempfile
import unittest
from PyQt5.QtWidgets import QApplication

from data_manager import (
    scan_and_parse_data_folder,
    sync_deck_from_source_folder,
    get_or_create_deck_by_path,
    deck_history
)

app = QApplication.instance() or QApplication(sys.argv)

class TestSubjectFolderSyncArchitecture(unittest.TestCase):
    def setUp(self):
        deck_history._undo_stack.clear()
        deck_history._redo_stack.clear()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_folder_sync_with_deck_uid_matching_and_sm2_preservation(self):
        root = self.temp_dir.name
        
        # 1. Create a subject folder with a topic JSON file
        # Topic: 16 Banking System
        topic_json_path = os.path.join(root, 'Banking_System_App_Import.json')
        cards_v1 = [
            {
                'card_uid': 'uid-bank-001',
                'deck_name': '16 Banking System',
                'deck_uid': 'topic-eco-16-banking-system',
                'question': 'भारत में स्थापित होने वाला सबसे पहला बैंक कौन-सा था?',
                'answer': 'बैंक ऑफ हिंदुस्तान',
                'notes': '1770 में कलकत्ता में।'
            },
            {
                'card_uid': 'uid-bank-002',
                'deck_name': '16 Banking System',
                'deck_uid': 'topic-eco-16-banking-system',
                'question': 'अवध कमर्शियल बैंक किस वर्ष स्थापित हुआ?',
                'answer': '1881 में',
                'notes': 'फैजाबाद में।'
            }
        ]
        with open(topic_json_path, 'w', encoding='utf-8') as f:
            json.dump(cards_v1, f, ensure_ascii=False)

        # 2. Build parent subject deck in app data (🏦 Economics)
        data = {'decks': []}
        parent_deck = {
            '_id': 205,
            'name': '🏦 Economics',
            'source_folder_path': root,
            'cards': [],
            'children': []
        }
        data['decks'].append(parent_deck)

        # 3. Initial folder sync on parent deck
        res1 = sync_deck_from_source_folder(data, deck=parent_deck)
        self.assertEqual(res1['new_count'], 2)
        self.assertEqual(res1['updated_count'], 0)

        # Verify: child subdeck '16 Banking System' created under parent
        self.assertEqual(len(parent_deck['children']), 1)
        subdeck = parent_deck['children'][0]
        self.assertEqual(subdeck['name'], '16 Banking System')
        self.assertEqual(subdeck['deck_uid'], 'topic-eco-16-banking-system')
        self.assertEqual(len(subdeck['cards']), 2)
        self.assertEqual(len(parent_deck['cards']), 0) # Parent has zero cards

        # 4. Simulate user studying card 1 (accumulating SM-2 reviews)
        card1 = subdeck['cards'][0]
        self.assertEqual(card1['card_uid'], 'uid-bank-001')
        card1['reviews'] = 7
        card1['sm2_interval'] = 14
        card1['sm2_repetitions'] = 5
        card1['sm2_ease'] = 2.6
        card1['sched_state'] = 'review'

        # 5. Simulate updating topic file:
        # - Card 1 edited (clarified text)
        # - Card 2 unchanged
        # - Card 3 added (split companion card)
        cards_v2 = [
            {
                'card_uid': 'uid-bank-001', # SAME UID
                'deck_name': '16 Banking System',
                'deck_uid': 'topic-eco-16-banking-system',
                'question': 'भारत में आधुनिक बैंकिंग का पहला बैंक बैंक ऑफ हिंदुस्तान किस वर्ष स्थापित हुआ?',
                'answer': '1770 में (कलकत्ता)',
                'notes': 'अलेक्जेंडर एंड कंपनी द्वारा।'
            },
            {
                'card_uid': 'uid-bank-002', # SAME UID
                'deck_name': '16 Banking System',
                'deck_uid': 'topic-eco-16-banking-system',
                'question': 'अवध कमर्शियल बैंक किस वर्ष स्थापित हुआ?',
                'answer': '1881 में',
                'notes': 'फैजाबाद में।'
            },
            {
                'card_uid': 'uid-bank-003', # NEW UID
                'deck_name': '16 Banking System',
                'deck_uid': 'topic-eco-16-banking-system',
                'question': 'अवध कमर्शियल बैंक का मुख्यालय कहाँ था?',
                'answer': 'फैजाबाद',
                'notes': 'उत्तर प्रदेश में।'
            }
        ]
        with open(topic_json_path, 'w', encoding='utf-8') as f:
            json.dump(cards_v2, f, ensure_ascii=False)

        # 6. Re-sync folder on parent deck
        res2 = sync_deck_from_source_folder(data, deck=parent_deck)
        self.assertEqual(res2['new_count'], 1)       # Card 3 is added
        self.assertEqual(res2['updated_count'], 1)   # Card 1 is updated
        self.assertEqual(res2['unchanged_count'], 1) # Card 2 is unchanged

        # Verify: NO duplicate subdeck was created!
        self.assertEqual(len(parent_deck['children']), 1)
        self.assertEqual(len(subdeck['cards']), 3)

        # Verify: Card 1 SM-2 progress was 100% PRESERVED!
        updated_card1 = [c for c in subdeck['cards'] if c['card_uid'] == 'uid-bank-001'][0]
        self.assertEqual(updated_card1['reviews'], 7)
        self.assertEqual(updated_card1['sm2_interval'], 14)
        self.assertEqual(updated_card1['sm2_repetitions'], 5)
        self.assertEqual(updated_card1['sm2_ease'], 2.6)
        self.assertEqual(updated_card1['sched_state'], 'review')
        self.assertEqual(updated_card1['answer'], '1770 में (कलकत्ता)')

        # 7. Add a SECOND topic file to the folder:
        # Topic: 17 Inflation and Unemployment
        topic2_path = os.path.join(root, 'Inflation_App_Import.json')
        cards_topic2 = [
            {
                'card_uid': 'uid-inf-001',
                'deck_name': '17 Inflation and Unemployment',
                'deck_uid': 'topic-eco-17-inflation',
                'question': 'मुद्रास्फीति (Inflation) की गणना हेतु मुख्य सूचकांक कौन-सा है?',
                'answer': 'उपभोक्ता मूल्य सूचकांक (CPI)',
                'notes': 'NSO द्वारा जारी किया जाता है।'
            }
        ]
        with open(topic2_path, 'w', encoding='utf-8') as f:
            json.dump(cards_topic2, f, ensure_ascii=False)

        # Re-sync parent folder
        res3 = sync_deck_from_source_folder(data, deck=parent_deck)
        self.assertEqual(res3['new_count'], 1) # Topic 2 card added
        
        # Verify: Parent now has 2 cleanly nested subdecks
        self.assertEqual(len(parent_deck['children']), 2)
        subdeck_names = {ch['name'] for ch in parent_deck['children']}
        self.assertIn('16 Banking System', subdeck_names)
        self.assertIn('17 Inflation and Unemployment', subdeck_names)
        
        sub2 = next(ch for ch in parent_deck['children'] if ch['name'] == '17 Inflation and Unemployment')
        self.assertEqual(sub2['deck_uid'], 'topic-eco-17-inflation')
        self.assertEqual(len(sub2['cards']), 1)

if __name__ == '__main__':
    unittest.main()
